#!/usr/local/bin/python3

import json
import os
import signal
import sqlite3
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


BROKER_HOST = "127.0.0.1"
BROKER_PORT = 9783
DATA_DIR = Path("/var/db/openwrt-admin")
DB_PATH = DATA_DIR / "state.sqlite"
KEY_DIR = DATA_DIR / "keys"
KNOWN_HOSTS_PATH = DATA_DIR / "known_hosts"
CONFIG_XML_PATH = Path("/conf/config.xml")
LOG_PREFIX = "[openwrt-admind]"
POLL_INTERVAL_SECONDS = 60
SSH_CONNECT_TIMEOUT_SECONDS = 1
SSH_COMMAND_TIMEOUT_SECONDS = 4
MAX_PARALLEL_POLLS = 8
MANAGED_KEY_REF = "managed:openwrt-admin"
MANAGED_KEY_PATH = KEY_DIR / "managed_ed25519"


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def format_uptime(seconds):
    try:
        total_seconds = max(0, int(seconds))
    except (TypeError, ValueError):
        return None

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def normalize_openwrt_load(value):
    try:
        return max(0.0, float(value) / 65535.0)
    except (TypeError, ValueError):
        return None


def classify_ssh_error(message):
    text = (message or "").strip()
    lowered = text.lower()

    if "no route to host" in lowered:
        return "No route to host"
    if "operation timed out" in lowered or "connection timed out" in lowered:
        return "Connection timed out"
    if "connection refused" in lowered:
        return "Connection refused"
    if "permission denied" in lowered:
        return "SSH auth failed"
    if "host key verification failed" in lowered:
        return "Host key verification failed"
    if "network is unreachable" in lowered:
        return "Network unreachable"
    if "could not resolve hostname" in lowered or "name or service not known" in lowered:
        return "DNS resolution failed"
    if text:
        return "SSH connection error"

    return "Offline"


def compact_json(data):
    return json.dumps(data, separators=(",", ":"))


class BrokerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.shutdown_event = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=MAX_PARALLEL_POLLS)
        self.current_poll = None
        self.last_poll_started = None
        self.last_poll_finished = None
        self.last_poll_summary = {"status": "idle"}
        self._ensure_paths()
        self._init_db()

    def _ensure_paths(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        KEY_DIR.mkdir(parents=True, exist_ok=True)
        KNOWN_HOSTS_PATH.touch(mode=0o600, exist_ok=True)
        os.chmod(KNOWN_HOSTS_PATH, 0o600)

    def _db(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS router_status (
                    router_uuid TEXT PRIMARY KEY,
                    address TEXT NOT NULL,
                    configured_hostname TEXT,
                    description TEXT,
                    ssh_key_ref TEXT,
                    reachable INTEGER NOT NULL DEFAULT 0,
                    status_text TEXT,
                    version TEXT,
                    detected_hostname TEXT,
                    load_1m REAL,
                    uptime_seconds INTEGER,
                    memory_used_pct INTEGER,
                    wifi_clients INTEGER,
                    best_signal_dbm INTEGER,
                    worst_signal_dbm INTEGER,
                    signal_histogram TEXT,
                    latency_ms INTEGER,
                    last_seen TEXT,
                    last_error TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn, "router_status", "load_1m", "REAL")
            self._ensure_column(conn, "router_status", "uptime_seconds", "INTEGER")
            self._ensure_column(conn, "router_status", "memory_used_pct", "INTEGER")
            self._ensure_column(conn, "router_status", "wifi_clients", "INTEGER")
            self._ensure_column(conn, "router_status", "best_signal_dbm", "INTEGER")
            self._ensure_column(conn, "router_status", "worst_signal_dbm", "INTEGER")
            self._ensure_column(conn, "router_status", "signal_histogram", "TEXT")

    def _ensure_column(self, conn, table_name, column_name, definition):
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def load_config(self):
        tree = ET.parse(CONFIG_XML_PATH)
        root = tree.getroot()
        opnsense = root.find("./OPNsense")
        app = opnsense.find("./OpenWrtAdmin") if opnsense is not None else None
        if app is None:
            return {"settings": {}, "routers": []}

        settings_node = app.find("./settings")
        settings = {
            "managed_private_key": "",
            "managed_public_key": "",
            "managed_key_comment": "",
        }
        if settings_node is not None:
            for key in settings.keys():
                settings[key] = (settings_node.findtext(key) or "").strip()

        routers = []
        routers_node = app.find("./routers")
        if routers_node is not None:
            for router in routers_node.findall("./router"):
                router_uuid = (router.attrib.get("uuid") or "").strip()
                if not router_uuid:
                    continue
                routers.append(
                    {
                        "router_uuid": router_uuid,
                        "address": (router.findtext("address") or "").strip(),
                        "hostname": (router.findtext("hostname") or "").strip(),
                        "description": (router.findtext("description") or "").strip(),
                        "ssh_key_ref": (router.findtext("ssh_key_ref") or "").strip(),
                    }
                )

        return {"settings": settings, "routers": routers}

    def ensure_managed_key(self, settings):
        private_key = settings.get("managed_private_key", "").strip()
        if not private_key:
            return None

        MANAGED_KEY_PATH.write_text(private_key + "\n", encoding="utf-8")
        os.chmod(MANAGED_KEY_PATH, 0o600)
        return str(MANAGED_KEY_PATH)

    def resolve_private_key(self, ssh_key_ref, settings):
        if ssh_key_ref == MANAGED_KEY_REF:
            return self.ensure_managed_key(settings)
        if ssh_key_ref.startswith("system:"):
            path = ssh_key_ref[7:]
            if os.path.isfile(path):
                return path[:-4] if path.endswith(".pub") else path
        return None

    def sync_router_rows(self, routers):
        keep = {router["router_uuid"] for router in routers}
        with self._db() as conn:
            for router in routers:
                conn.execute(
                    """
                    INSERT INTO router_status (
                        router_uuid, address, configured_hostname, description, ssh_key_ref,
                        reachable, status_text, version, detected_hostname, load_1m,
                        uptime_seconds, memory_used_pct, wifi_clients, best_signal_dbm,
                        worst_signal_dbm, signal_histogram, latency_ms,
                        last_seen, last_error, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, 'Pending', '', '', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?)
                    ON CONFLICT(router_uuid) DO UPDATE SET
                        address=excluded.address,
                        configured_hostname=excluded.configured_hostname,
                        description=excluded.description,
                        ssh_key_ref=excluded.ssh_key_ref,
                        updated_at=excluded.updated_at
                    """,
                    (
                        router["router_uuid"],
                        router["address"],
                        router["hostname"],
                        router["description"],
                        router["ssh_key_ref"],
                        now_iso(),
                    ),
                )
            if keep:
                placeholders = ",".join("?" for _ in keep)
                conn.execute(
                    f"DELETE FROM router_status WHERE router_uuid NOT IN ({placeholders})",
                    tuple(sorted(keep)),
                )
            else:
                conn.execute("DELETE FROM router_status")

    def parse_health(self, system_info):
        load_values = system_info.get("load") or []
        load_1m = normalize_openwrt_load(load_values[0]) if load_values else None

        memory = system_info.get("memory") or {}
        total_memory = memory.get("total")
        available_memory = memory.get("available")
        memory_available_pct = None
        if total_memory not in (None, 0) and available_memory is not None:
            try:
                memory_available_pct = max(0, min(100, round((float(available_memory) / float(total_memory)) * 100)))
            except (TypeError, ValueError, ZeroDivisionError):
                memory_available_pct = None

        root = system_info.get("root") or {}
        root_total = root.get("total")
        root_used = root.get("used")
        root_used_pct = None
        if root_total not in (None, 0) and root_used is not None:
            try:
                root_used_pct = max(0, min(100, round((float(root_used) / float(root_total)) * 100)))
            except (TypeError, ValueError, ZeroDivisionError):
                root_used_pct = None

        health = "Healthy"
        if (
            (memory_available_pct is not None and memory_available_pct < 10)
            or (root_used_pct is not None and root_used_pct >= 95)
            or (load_1m is not None and load_1m >= 4.0)
        ):
            health = "Critical"
        elif (
            (memory_available_pct is not None and memory_available_pct < 20)
            or (root_used_pct is not None and root_used_pct >= 85)
            or (load_1m is not None and load_1m >= 2.0)
        ):
            health = "Warning"

        parts = [health]

        uptime_text = format_uptime(system_info.get("uptime"))
        if uptime_text:
            parts.append(f"{uptime_text} up")

        if load_1m is not None:
            parts.append(f"load {load_1m:.2f}")

        if memory_available_pct is not None:
            parts.append(f"mem {memory_available_pct}% free")

        return {
            "status_text": " | ".join(parts),
            "load_1m": load_1m,
            "uptime_seconds": system_info.get("uptime"),
            "memory_used_pct": None if memory_available_pct is None else max(0, min(100, 100 - memory_available_pct)),
        }

    def parse_wifi_clients(self, hostapd_outputs):
        total_clients = 0
        for payload in hostapd_outputs:
            clients = payload.get("clients") or {}
            if isinstance(clients, dict):
                total_clients += len(clients)
        return total_clients

    def parse_signal_stats(self, hostapd_outputs):
        signals = []
        histogram = {
            "excellent": 0,
            "good": 0,
            "fair": 0,
            "weak": 0,
        }

        for payload in hostapd_outputs:
            clients = payload.get("clients") or {}
            if not isinstance(clients, dict):
                continue
            for client in clients.values():
                if not isinstance(client, dict):
                    continue
                signal = client.get("signal")
                if not isinstance(signal, (int, float)):
                    continue
                signal = int(signal)
                signals.append(signal)
                if signal >= -55:
                    histogram["excellent"] += 1
                elif signal >= -67:
                    histogram["good"] += 1
                elif signal >= -75:
                    histogram["fair"] += 1
                else:
                    histogram["weak"] += 1

        if not signals:
            return {
                "best_signal_dbm": None,
                "worst_signal_dbm": None,
                "signal_histogram": None,
            }

        return {
            "best_signal_dbm": max(signals),
            "worst_signal_dbm": min(signals),
            "signal_histogram": compact_json(histogram),
        }

    def ssh_base_command(self, address, private_key):
        return [
            "ssh",
            "-i",
            private_key,
            "-o",
            f"ConnectTimeout={SSH_CONNECT_TIMEOUT_SECONDS}",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "BatchMode=yes",
            "-o",
            "PreferredAuthentications=publickey",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=0",
            "-o",
            "ServerAliveInterval=1",
            "-o",
            "ServerAliveCountMax=1",
            "-o",
            f"UserKnownHostsFile={KNOWN_HOSTS_PATH}",
            "-o",
            "StrictHostKeyChecking=accept-new",
            f"root@{address}",
        ]

    def run_ssh(self, address, private_key, remote_args):
        command = self.ssh_base_command(address, private_key) + remote_args
        started = time.monotonic()
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=SSH_COMMAND_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            latency = int((time.monotonic() - started) * 1000)
            return {
                "ok": False,
                "timed_out": True,
                "returncode": None,
                "stdout": "",
                "stderr": "",
                "latency_ms": latency,
            }

        latency = int((time.monotonic() - started) * 1000)
        return {
            "ok": proc.returncode == 0,
            "timed_out": False,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
            "latency_ms": latency,
        }

    def poll_router(self, router, settings):
        address = router["address"]
        private_key = self.resolve_private_key(router["ssh_key_ref"], settings)
        updated_at = now_iso()

        if not address:
            return {
                "router_uuid": router["router_uuid"],
                "reachable": 0,
                "status_text": "Invalid",
                "version": "",
                "detected_hostname": "",
                "load_1m": None,
                "uptime_seconds": None,
                "memory_used_pct": None,
                "wifi_clients": None,
                "best_signal_dbm": None,
                "worst_signal_dbm": None,
                "signal_histogram": None,
                "latency_ms": None,
                "last_seen": None,
                "last_error": "Missing router address.",
                "updated_at": updated_at,
            }

        if not private_key:
            return {
                "router_uuid": router["router_uuid"],
                "reachable": 0,
                "status_text": "Key error",
                "version": "",
                "detected_hostname": "",
                "load_1m": None,
                "uptime_seconds": None,
                "memory_used_pct": None,
                "wifi_clients": None,
                "best_signal_dbm": None,
                "worst_signal_dbm": None,
                "signal_histogram": None,
                "latency_ms": None,
                "last_seen": None,
                "last_error": "No usable SSH private key available.",
                "updated_at": updated_at,
            }

        board_result = self.run_ssh(address, private_key, ["ubus", "call", "system", "board"])
        if board_result["timed_out"]:
            return {
                "router_uuid": router["router_uuid"],
                "reachable": 0,
                "status_text": "Connection timed out",
                "version": "",
                "detected_hostname": "",
                "load_1m": None,
                "uptime_seconds": None,
                "memory_used_pct": None,
                "wifi_clients": None,
                "best_signal_dbm": None,
                "worst_signal_dbm": None,
                "signal_histogram": None,
                "latency_ms": board_result["latency_ms"],
                "last_seen": None,
                "last_error": "SSH status command timed out.",
                "updated_at": updated_at,
            }

        if not board_result["ok"]:
            last_error = board_result["stderr"] or board_result["stdout"] or f"ssh exited with code {board_result['returncode']}"
            return {
                "router_uuid": router["router_uuid"],
                "reachable": 0,
                "status_text": classify_ssh_error(last_error),
                "version": "",
                "detected_hostname": "",
                "load_1m": None,
                "uptime_seconds": None,
                "memory_used_pct": None,
                "wifi_clients": None,
                "best_signal_dbm": None,
                "worst_signal_dbm": None,
                "signal_histogram": None,
                "latency_ms": board_result["latency_ms"],
                "last_seen": None,
                "last_error": last_error,
                "updated_at": updated_at,
            }

        system_info_result = self.run_ssh(address, private_key, ["ubus", "call", "system", "info"])
        if system_info_result["timed_out"]:
            return {
                "router_uuid": router["router_uuid"],
                "reachable": 0,
                "status_text": "Connection timed out",
                "version": "",
                "detected_hostname": "",
                "load_1m": None,
                "uptime_seconds": None,
                "memory_used_pct": None,
                "wifi_clients": None,
                "best_signal_dbm": None,
                "worst_signal_dbm": None,
                "signal_histogram": None,
                "latency_ms": board_result["latency_ms"] + system_info_result["latency_ms"],
                "last_seen": None,
                "last_error": "SSH status command timed out.",
                "updated_at": updated_at,
            }

        if not system_info_result["ok"]:
            last_error = system_info_result["stderr"] or system_info_result["stdout"] or f"ssh exited with code {system_info_result['returncode']}"
            return {
                "router_uuid": router["router_uuid"],
                "reachable": 0,
                "status_text": classify_ssh_error(last_error),
                "version": "",
                "detected_hostname": "",
                "load_1m": None,
                "uptime_seconds": None,
                "memory_used_pct": None,
                "wifi_clients": None,
                "best_signal_dbm": None,
                "worst_signal_dbm": None,
                "signal_histogram": None,
                "latency_ms": board_result["latency_ms"] + system_info_result["latency_ms"],
                "last_seen": None,
                "last_error": last_error,
                "updated_at": updated_at,
            }

        try:
            payload = json.loads(board_result["stdout"])
            system_info = json.loads(system_info_result["stdout"])
        except json.JSONDecodeError:
            return {
                "router_uuid": router["router_uuid"],
                "reachable": 0,
                "status_text": "Protocol error",
                "version": "",
                "detected_hostname": "",
                "load_1m": None,
                "uptime_seconds": None,
                "memory_used_pct": None,
                "wifi_clients": None,
                "best_signal_dbm": None,
                "worst_signal_dbm": None,
                "signal_histogram": None,
                "latency_ms": board_result["latency_ms"] + system_info_result["latency_ms"],
                "last_seen": None,
                "last_error": "Unable to parse OpenWrt ubus output.",
                "updated_at": updated_at,
            }

        wifi_clients = None
        signal_stats = {
            "best_signal_dbm": None,
            "worst_signal_dbm": None,
            "signal_histogram": None,
        }
        latency = board_result["latency_ms"] + system_info_result["latency_ms"]
        hostapd_list_result = self.run_ssh(address, private_key, ["ubus", "list", "hostapd.*"])
        latency += hostapd_list_result["latency_ms"]
        if hostapd_list_result["timed_out"]:
            wifi_clients = None
        elif hostapd_list_result["ok"]:
            hostapd_outputs = []
            interfaces = [line.strip() for line in hostapd_list_result["stdout"].splitlines() if line.strip()]
            for iface in interfaces:
                clients_result = self.run_ssh(address, private_key, ["ubus", "call", iface, "get_clients"])
                latency += clients_result["latency_ms"]
                if not clients_result["ok"] or clients_result["timed_out"] or not clients_result["stdout"]:
                    continue
                try:
                    hostapd_outputs.append(json.loads(clients_result["stdout"]))
                except json.JSONDecodeError:
                    continue
            wifi_clients = self.parse_wifi_clients(hostapd_outputs)
            signal_stats = self.parse_signal_stats(hostapd_outputs)
        elif "Command failed: Not found" in (hostapd_list_result["stderr"] or hostapd_list_result["stdout"]):
            wifi_clients = None

        health = self.parse_health(system_info)
        release = payload.get("release") or {}
        return {
            "router_uuid": router["router_uuid"],
            "reachable": 1,
            "status_text": health["status_text"],
            "version": str(release.get("description") or release.get("version") or ""),
            "detected_hostname": str(payload.get("hostname") or ""),
            "load_1m": health["load_1m"],
            "uptime_seconds": health["uptime_seconds"],
            "memory_used_pct": health["memory_used_pct"],
            "wifi_clients": wifi_clients,
            "best_signal_dbm": signal_stats["best_signal_dbm"],
            "worst_signal_dbm": signal_stats["worst_signal_dbm"],
            "signal_histogram": signal_stats["signal_histogram"],
            "latency_ms": latency,
            "last_seen": now_iso(),
            "last_error": "",
            "updated_at": updated_at,
        }

    def write_poll_results(self, routers, results):
        router_map = {router["router_uuid"]: router for router in routers}
        with self._db() as conn:
            for item in results:
                router = router_map[item["router_uuid"]]
                conn.execute(
                    """
                    UPDATE router_status
                    SET reachable=?, status_text=?, version=?, detected_hostname=?, load_1m=?,
                        uptime_seconds=?, memory_used_pct=?, wifi_clients=?, best_signal_dbm=?,
                        worst_signal_dbm=?, signal_histogram=?, latency_ms=?,
                        last_seen=?, last_error=?, updated_at=?
                    WHERE router_uuid=?
                    """,
                    (
                        item["reachable"],
                        item["status_text"],
                        item["version"],
                        item["detected_hostname"],
                        item["load_1m"],
                        item["uptime_seconds"],
                        item["memory_used_pct"],
                        item["wifi_clients"],
                        item["best_signal_dbm"],
                        item["worst_signal_dbm"],
                        item["signal_histogram"],
                        item["latency_ms"],
                        item["last_seen"],
                        item["last_error"],
                        item["updated_at"],
                        item["router_uuid"],
                    ),
                )

    def poll_all(self):
        config = self.load_config()
        routers = config["routers"]
        settings = config["settings"]
        self.sync_router_rows(routers)

        if not routers:
            return {"status": "ok", "routers": 0, "reachable": 0}

        futures = [self.executor.submit(self.poll_router, router, settings) for router in routers]
        results = [future.result() for future in as_completed(futures)]
        self.write_poll_results(routers, results)

        reachable = sum(1 for item in results if item["reachable"])
        return {
            "status": "ok",
            "routers": len(results),
            "reachable": reachable,
            "unreachable": len(results) - reachable,
        }

    def trigger_poll(self):
        with self.lock:
            if self.current_poll is not None and self.current_poll.is_alive():
                return False
            thread = threading.Thread(target=self._poll_worker, daemon=True)
            self.current_poll = thread
            thread.start()
            return True

    def _poll_worker(self):
        with self.lock:
            self.last_poll_started = now_iso()
            self.last_poll_summary = {"status": "running"}
        try:
            summary = self.poll_all()
        except Exception as exc:
            summary = {"status": "error", "message": str(exc)}
        with self.lock:
            self.last_poll_finished = now_iso()
            self.last_poll_summary = summary

    def scheduler(self):
        self.trigger_poll()
        while not self.shutdown_event.wait(POLL_INTERVAL_SECONDS):
            self.trigger_poll()

    def close(self):
        self.shutdown_event.set()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def status_payload(self):
        with self.lock:
            running = self.current_poll is not None and self.current_poll.is_alive()
            return {
                "status": "ok",
                "listening": f"{BROKER_HOST}:{BROKER_PORT}",
                "poll_running": running,
                "last_poll_started": self.last_poll_started,
                "last_poll_finished": self.last_poll_finished,
                "last_poll_summary": self.last_poll_summary,
            }

    def router_rows(self):
        with self._db() as conn:
            rows = conn.execute(
                """
                SELECT router_uuid, address, configured_hostname, description, ssh_key_ref,
                       reachable, status_text, version, detected_hostname, load_1m,
                       uptime_seconds, memory_used_pct, wifi_clients, best_signal_dbm,
                       worst_signal_dbm, signal_histogram, latency_ms,
                       last_seen, last_error, updated_at
                FROM router_status
                ORDER BY address COLLATE NOCASE
                """
            ).fetchall()
        return [dict(row) for row in rows]


STATE = BrokerState()


class BrokerHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


class BrokerHandler(BaseHTTPRequestHandler):
    server_version = "OpenWrtAdminBroker/0.1"

    def _send(self, status_code, payload):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.path == "/v1/status":
            self._send(200, STATE.status_payload())
        elif self.path == "/v1/routers":
            self._send(200, {"status": "ok", "routers": STATE.router_rows()})
        else:
            self._send(404, {"status": "error", "message": "Not found"})

    def do_POST(self):
        if self.path == "/v1/poll-now":
            accepted = STATE.trigger_poll()
            self._send(200, {"status": "ok", "accepted": accepted})
        else:
            self._send(404, {"status": "error", "message": "Not found"})


def main():
    scheduler_thread = threading.Thread(target=STATE.scheduler, daemon=True)
    scheduler_thread.start()

    httpd = BrokerHTTPServer((BROKER_HOST, BROKER_PORT), BrokerHandler)

    def shutdown_handler(signum, frame):
        STATE.shutdown_event.set()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    print(f"{LOG_PREFIX} listening on {BROKER_HOST}:{BROKER_PORT}", flush=True)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        STATE.close()


if __name__ == "__main__":
    main()
