#!/usr/local/bin/python3

import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


BROKER_HOST = "127.0.0.1"
BROKER_PORT = 9783
DATA_DIR = Path("/var/db/openwrt-admin")
DB_PATH = DATA_DIR / "state.sqlite"
KEY_DIR = DATA_DIR / "keys"
CONTROL_SOCKET_DIR = DATA_DIR / "control"
KNOWN_HOSTS_PATH = DATA_DIR / "known_hosts"
CONFIG_XML_PATH = Path("/conf/config.xml")
LOG_PREFIX = "[openwrt-admind]"
# Defaults — all overridden at runtime by values in config.xml settings.
DEFAULT_POLL_INTERVAL_SECONDS = 60
DEFAULT_SSH_CONNECT_TIMEOUT_SECONDS = 5
DEFAULT_SSH_COMMAND_TIMEOUT_SECONDS = 15
SSH_CONTROL_PERSIST_SECONDS = 120
DEFAULT_MAX_PARALLEL_POLLS = 8
DEFAULT_CONFIG_BACKUP_LIMIT = 8
MANAGED_KEY_REF = "managed:openwrt-admin"
MANAGED_KEY_PATH = KEY_DIR / "managed_ed25519"
WIRELESS_CONFIG_PATH = "/etc/config/wireless"
SYSTEM_CONFIG_PATH = "/etc/config/system"
FIREWALL_CONFIG_PATH = "/etc/config/firewall"
DHCP_CONFIG_PATH = "/etc/config/dhcp"
RPCD_CONFIG_PATH = "/etc/config/rpcd"
CONFIG_TYPES = ("wifi", "system", "firewall", "dhcp", "rpcd")


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


def normalize_mac(value):
    if not isinstance(value, str):
        return ""
    cleaned = value.strip().lower().replace("-", ":")
    return cleaned


def integer_or_none(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class BrokerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.shutdown_event = threading.Event()
        self.current_poll = None
        self.last_poll_started = None
        self.last_poll_finished = None
        self.last_poll_summary = {"status": "idle"}
        self._ensure_paths()
        self._load_tuning()
        self.executor = ThreadPoolExecutor(max_workers=self._max_parallel_polls)
        self._init_db()

    def _load_tuning(self):
        """Read tunable values from config.xml; fall back to defaults if absent or invalid."""
        try:
            config = self.load_config()
            s = config.get("settings", {})

            def _int(key, default, lo, hi):
                try:
                    return max(lo, min(hi, int(s.get(key) or default)))
                except (TypeError, ValueError):
                    return default

            self._poll_interval = _int("poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS, 10, 3600)
            self._ssh_connect_timeout = _int("ssh_connect_timeout_seconds", DEFAULT_SSH_CONNECT_TIMEOUT_SECONDS, 1, 30)
            self._ssh_command_timeout = _int("ssh_command_timeout_seconds", DEFAULT_SSH_COMMAND_TIMEOUT_SECONDS, 2, 120)
            self._max_parallel_polls = _int("max_parallel_polls", DEFAULT_MAX_PARALLEL_POLLS, 1, 64)
            self._config_backup_limit = _int("config_backup_limit", DEFAULT_CONFIG_BACKUP_LIMIT, 1, 50)
        except Exception:
            self._poll_interval = DEFAULT_POLL_INTERVAL_SECONDS
            self._ssh_connect_timeout = DEFAULT_SSH_CONNECT_TIMEOUT_SECONDS
            self._ssh_command_timeout = DEFAULT_SSH_COMMAND_TIMEOUT_SECONDS
            self._max_parallel_polls = DEFAULT_MAX_PARALLEL_POLLS
            self._config_backup_limit = DEFAULT_CONFIG_BACKUP_LIMIT

    def _ensure_paths(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        KEY_DIR.mkdir(parents=True, exist_ok=True)
        CONTROL_SOCKET_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(CONTROL_SOCKET_DIR, 0o700)
        KNOWN_HOSTS_PATH.touch(mode=0o600, exist_ok=True)
        os.chmod(KNOWN_HOSTS_PATH, 0o600)

    def _db(self):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _db_context(self):
        conn = self._db()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        with self._db_context() as conn:
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
                    hardware_model TEXT,
                    detected_hostname TEXT,
                    load_1m REAL,
                    uptime_seconds INTEGER,
                    memory_used_pct INTEGER,
                    wifi_clients INTEGER,
                    wifi_clients_by_radio TEXT,
                    wifi_clients_by_network TEXT,
                    best_signal_dbm INTEGER,
                    worst_signal_dbm INTEGER,
                    signal_histogram TEXT,
                    rx_bps INTEGER,
                    tx_bps INTEGER,
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
            self._ensure_column(conn, "router_status", "wifi_clients_by_radio", "TEXT")
            self._ensure_column(conn, "router_status", "wifi_clients_by_network", "TEXT")
            self._ensure_column(conn, "router_status", "hardware_model", "TEXT")
            self._ensure_column(conn, "router_status", "best_signal_dbm", "INTEGER")
            self._ensure_column(conn, "router_status", "worst_signal_dbm", "INTEGER")
            self._ensure_column(conn, "router_status", "signal_histogram", "TEXT")
            self._ensure_column(conn, "router_status", "rx_bps", "INTEGER")
            self._ensure_column(conn, "router_status", "tx_bps", "INTEGER")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS router_wireless_state (
                    router_uuid TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    content TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS router_wireless_backup (
                    router_uuid TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    PRIMARY KEY (router_uuid, content_hash)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS router_config_state (
                    router_uuid TEXT NOT NULL,
                    config_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    content TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY (router_uuid, config_type)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS router_config_backup (
                    router_uuid TEXT NOT NULL,
                    config_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    PRIMARY KEY (router_uuid, config_type, content_hash)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS router_client_status (
                    router_uuid TEXT NOT NULL,
                    client_mac TEXT NOT NULL,
                    ip_address TEXT,
                    network_name TEXT,
                    radio_name TEXT,
                    signal_dbm INTEGER,
                    rx_bytes INTEGER,
                    tx_bytes INTEGER,
                    rx_bps INTEGER,
                    tx_bps INTEGER,
                    connected_seconds INTEGER,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (router_uuid, client_mac, network_name, radio_name)
                )
                """
            )
            self._ensure_column(conn, "router_client_status", "ip_address", "TEXT")
            self._ensure_column(conn, "router_client_status", "rx_bps", "INTEGER")
            self._ensure_column(conn, "router_client_status", "tx_bps", "INTEGER")

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
            "poll_interval_seconds": "",
            "ssh_connect_timeout_seconds": "",
            "ssh_command_timeout_seconds": "",
            "max_parallel_polls": "",
            "config_backup_limit": "",
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
                        "ssh_username": (router.findtext("ssh_username") or "root").strip() or "root",
                        "ssh_key_ref": (router.findtext("ssh_key_ref") or "").strip(),
                        "sync_wifi_config_from": (router.findtext("sync_wifi_config_from") or "").strip(),
                        "sync_system_config_from": (router.findtext("sync_system_config_from") or "").strip(),
                        "sync_firewall_config_from": (router.findtext("sync_firewall_config_from") or "").strip(),
                        "sync_dhcp_config_from": (router.findtext("sync_dhcp_config_from") or "").strip(),
                        "sync_rpcd_config_from": (router.findtext("sync_rpcd_config_from") or "").strip(),
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
        with self._db_context() as conn:
            for router in routers:
                conn.execute(
                    """
                    INSERT INTO router_status (
                        router_uuid, address, configured_hostname, description, ssh_key_ref,
                        reachable, status_text, version, hardware_model, detected_hostname, load_1m,
                        uptime_seconds, memory_used_pct, wifi_clients, wifi_clients_by_radio, wifi_clients_by_network, best_signal_dbm,
                        worst_signal_dbm, signal_histogram, latency_ms,
                        last_seen, last_error, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, 'Pending', '', '', '', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?)
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
        by_radio = {}
        by_network = {}
        for entry in hostapd_outputs:
            radio = entry.get("radio") or "unknown"
            network = entry.get("network") or radio
            payload = entry.get("payload") or {}
            clients = payload.get("clients") or {}
            if isinstance(clients, dict):
                count = len(clients)
                total_clients += count
                by_radio[radio] = by_radio.get(radio, 0) + count
                by_network[network] = by_network.get(network, 0) + count
        if not by_radio:
            by_radio = None
        if not by_network:
            by_network = None
        return {
            "total": total_clients,
            "by_radio": None if by_radio is None else compact_json(by_radio),
            "by_network": None if by_network is None else compact_json(by_network),
        }

    def parse_signal_stats(self, hostapd_outputs):
        signals = []
        histogram = {
            "excellent": 0,
            "good": 0,
            "fair": 0,
            "weak": 0,
        }

        for entry in hostapd_outputs:
            payload = entry.get("payload") or {}
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

    def parse_client_associations(self, hostapd_outputs):
        associations = []
        for entry in hostapd_outputs:
            radio = entry.get("radio") or "unknown"
            network = entry.get("network") or radio
            payload = entry.get("payload") or {}
            clients = payload.get("clients") or {}
            if not isinstance(clients, dict):
                continue

            for client_mac, client in clients.items():
                if not isinstance(client, dict):
                    continue
                byte_counters = client.get("bytes") if isinstance(client.get("bytes"), dict) else {}

                associations.append(
                    {
                        "client_mac": normalize_mac(client_mac),
                        "ip_address": str(client.get("ipaddr") or "").strip() or None,
                        "network_name": str(network),
                        "radio_name": str(radio),
                        "signal_dbm": integer_or_none(client.get("signal")),
                        "rx_bytes": integer_or_none(client.get("rx_bytes"))
                        if integer_or_none(client.get("rx_bytes")) is not None
                        else integer_or_none(byte_counters.get("rx")),
                        "tx_bytes": integer_or_none(client.get("tx_bytes"))
                        if integer_or_none(client.get("tx_bytes")) is not None
                        else integer_or_none(byte_counters.get("tx")),
                        "connected_seconds": integer_or_none(
                            client.get("connected_time") or client.get("connected_seconds")
                        ),
                    }
                )

        return [item for item in associations if item["client_mac"]]

    def control_socket_path(self, address, private_key, username="root"):
        digest = hashlib.sha1(f"{username}@{address}|{private_key}".encode("utf-8")).hexdigest()[:20]
        return CONTROL_SOCKET_DIR / f"cm-{digest}"

    def ssh_base_command(self, address, private_key, control_path, username="root"):
        return [
            "ssh",
            "-i",
            private_key,
            "-o",
            f"ConnectTimeout={self._ssh_connect_timeout}",
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
            "-o",
            "ControlMaster=auto",
            "-o",
            f"ControlPersist={SSH_CONTROL_PERSIST_SECONDS}",
            "-o",
            f"ControlPath={control_path}",
            f"{username}@{address}",
        ]

    def should_reset_control_socket(self, message, control_path):
        if not control_path.is_socket() and not control_path.exists():
            return False

        lowered = (message or "").lower()
        markers = [
            "control socket",
            "master died",
            "mux_client",
            "stale session",
            "session open refused",
            "permission denied while connecting to multiplexed socket",
        ]
        return any(marker in lowered for marker in markers)

    def remove_control_socket(self, control_path):
        try:
            if control_path.exists() or control_path.is_socket():
                control_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def run_ssh(
        self,
        address,
        private_key,
        remote_args,
        allow_retry=True,
        input_text=None,
        strip_output=True,
        username="root",
        timeout_seconds=None,
    ):
        control_path = self.control_socket_path(address, private_key, username)
        command = self.ssh_base_command(address, private_key, control_path, username) + remote_args
        started = time.monotonic()
        timeout_seconds = self._ssh_command_timeout if timeout_seconds is None else timeout_seconds
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                input=input_text,
                timeout=timeout_seconds,
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
        result = {
            "ok": proc.returncode == 0,
            "timed_out": False,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "").strip() if strip_output else (proc.stdout or ""),
            "stderr": (proc.stderr or "").strip() if strip_output else (proc.stderr or ""),
            "latency_ms": latency,
        }
        error_text = result["stderr"] or result["stdout"]
        if not result["ok"] and allow_retry and self.should_reset_control_socket(error_text, control_path):
            self.remove_control_socket(control_path)
            retry_result = self.run_ssh(
                address,
                private_key,
                remote_args,
                allow_retry=False,
                input_text=input_text,
                strip_output=strip_output,
                username=username,
                timeout_seconds=timeout_seconds,
            )
            retry_result["latency_ms"] += latency
            return retry_result

        return result

    def _make_error_result(self, router_uuid, status_text, last_error, latency_ms=None):
        return {
            "router_uuid": router_uuid,
            "reachable": 0,
            "status_text": status_text,
            "version": "",
            "hardware_model": "",
            "detected_hostname": "",
            "load_1m": None,
            "uptime_seconds": None,
            "memory_used_pct": None,
            "wifi_clients": None,
            "wifi_clients_by_radio": None,
            "wifi_clients_by_network": None,
            "best_signal_dbm": None,
            "worst_signal_dbm": None,
            "signal_histogram": None,
            "latency_ms": latency_ms,
            "last_seen": None,
            "last_error": last_error,
            "updated_at": now_iso(),
            "client_associations": [],
        }

    def poll_router(self, router, settings):
        address = router["address"]
        username = router.get("ssh_username") or "root"
        private_key = self.resolve_private_key(router["ssh_key_ref"], settings)
        router_uuid = router["router_uuid"]

        if not address:
            return self._make_error_result(router_uuid, "Invalid", "Missing router address.")

        if not private_key:
            return self._make_error_result(router_uuid, "Key error", "No usable SSH private key available.")

        board_result = self.run_ssh(address, private_key, ["ubus", "call", "system", "board"], username=username)
        if board_result["timed_out"]:
            return self._make_error_result(router_uuid, "Connection timed out", "SSH status command timed out.", board_result["latency_ms"])

        if not board_result["ok"]:
            last_error = board_result["stderr"] or board_result["stdout"] or f"ssh exited with code {board_result['returncode']}"
            return self._make_error_result(router_uuid, classify_ssh_error(last_error), last_error, board_result["latency_ms"])

        system_info_result = self.run_ssh(address, private_key, ["ubus", "call", "system", "info"], username=username)
        latency = board_result["latency_ms"] + system_info_result["latency_ms"]
        if system_info_result["timed_out"]:
            return self._make_error_result(router_uuid, "Connection timed out", "SSH status command timed out.", latency)

        if not system_info_result["ok"]:
            last_error = system_info_result["stderr"] or system_info_result["stdout"] or f"ssh exited with code {system_info_result['returncode']}"
            return self._make_error_result(router_uuid, classify_ssh_error(last_error), last_error, latency)

        try:
            payload = json.loads(board_result["stdout"])
            system_info = json.loads(system_info_result["stdout"])
        except json.JSONDecodeError:
            return self._make_error_result(router_uuid, "Protocol error", "Unable to parse OpenWrt ubus output.", latency)

        wifi_clients = None
        wifi_clients_by_radio = None
        wifi_clients_by_network = None
        signal_stats = {
            "best_signal_dbm": None,
            "worst_signal_dbm": None,
            "signal_histogram": None,
        }
        client_associations = []
        hostapd_list_result = self.run_ssh(address, private_key, ["ubus", "list", "hostapd.*"], username=username)
        latency += hostapd_list_result["latency_ms"]
        if hostapd_list_result["timed_out"]:
            wifi_clients = None
        elif hostapd_list_result["ok"]:
            hostapd_outputs = []
            interfaces = [line.strip() for line in hostapd_list_result["stdout"].splitlines() if line.strip()]
            for iface in interfaces:
                network_name = iface.split(".", 1)[1] if "." in iface else iface
                status_result = self.run_ssh(address, private_key, ["ubus", "call", iface, "get_status"], username=username)
                latency += status_result["latency_ms"]
                if status_result["ok"] and not status_result["timed_out"] and status_result["stdout"]:
                    try:
                        status_payload = json.loads(status_result["stdout"])
                        network_name = str(status_payload.get("ssid") or network_name)
                    except json.JSONDecodeError:
                        pass
                clients_result = self.run_ssh(address, private_key, ["ubus", "call", iface, "get_clients"], username=username)
                latency += clients_result["latency_ms"]
                if not clients_result["ok"] or clients_result["timed_out"] or not clients_result["stdout"]:
                    continue
                try:
                    hostapd_outputs.append(
                        {
                            "radio": iface.split(".", 1)[1] if "." in iface else iface,
                            "network": network_name,
                            "payload": json.loads(clients_result["stdout"]),
                        }
                    )
                except json.JSONDecodeError:
                    continue
            wifi_stats = self.parse_wifi_clients(hostapd_outputs)
            wifi_clients = wifi_stats["total"]
            wifi_clients_by_radio = wifi_stats["by_radio"]
            wifi_clients_by_network = wifi_stats["by_network"]
            signal_stats = self.parse_signal_stats(hostapd_outputs)
            client_associations = self.parse_client_associations(hostapd_outputs)
        elif "Command failed: Not found" in (hostapd_list_result["stderr"] or hostapd_list_result["stdout"]):
            wifi_clients = None

        health = self.parse_health(system_info)
        release = payload.get("release") or {}
        return {
            "router_uuid": router["router_uuid"],
            "reachable": 1,
            "status_text": health["status_text"],
            "version": str(release.get("description") or release.get("version") or ""),
            "hardware_model": str(payload.get("model") or payload.get("system") or payload.get("board_name") or ""),
            "detected_hostname": str(payload.get("hostname") or ""),
            "load_1m": health["load_1m"],
            "uptime_seconds": health["uptime_seconds"],
            "memory_used_pct": health["memory_used_pct"],
            "wifi_clients": wifi_clients,
            "wifi_clients_by_radio": wifi_clients_by_radio,
            "wifi_clients_by_network": wifi_clients_by_network,
            "best_signal_dbm": signal_stats["best_signal_dbm"],
            "worst_signal_dbm": signal_stats["worst_signal_dbm"],
            "signal_histogram": signal_stats["signal_histogram"],
            "client_associations": client_associations,
            "latency_ms": latency,
            "last_seen": now_iso(),
            "last_error": "",
            "updated_at": updated_at,
        }

    def write_poll_results(self, routers, results):
        router_map = {router["router_uuid"]: router for router in routers}
        with self._db_context() as conn:
            for item in results:
                router = router_map[item["router_uuid"]]
                previous_clients = {
                    (
                        str(row["client_mac"] or ""),
                        str(row["network_name"] or ""),
                        str(row["radio_name"] or ""),
                    ): dict(row)
                    for row in conn.execute(
                        """
                        SELECT client_mac, network_name, radio_name, rx_bytes, tx_bytes, updated_at
                        FROM router_client_status
                        WHERE router_uuid=?
                        """,
                        (item["router_uuid"],),
                    ).fetchall()
                }

                router_rx_bps = 0
                router_tx_bps = 0
                client_associations = item.get("client_associations") or []
                for client in client_associations:
                    key = (
                        str(client.get("client_mac") or ""),
                        str(client.get("network_name") or ""),
                        str(client.get("radio_name") or ""),
                    )
                    previous = previous_clients.get(key)
                    rx_bps = None
                    tx_bps = None
                    if previous is not None:
                        try:
                            previous_ts = datetime.fromisoformat(str(previous.get("updated_at") or ""))
                            current_ts = datetime.fromisoformat(str(item["updated_at"]))
                            elapsed = max(0.0, (current_ts - previous_ts).total_seconds())
                        except ValueError:
                            elapsed = 0.0

                        if elapsed > 0:
                            current_rx = client.get("rx_bytes")
                            previous_rx = previous.get("rx_bytes")
                            current_tx = client.get("tx_bytes")
                            previous_tx = previous.get("tx_bytes")
                            if (
                                isinstance(current_rx, int)
                                and previous_rx is not None
                                and int(previous_rx) >= 0
                                and current_rx >= int(previous_rx)
                            ):
                                rx_bps = int((current_rx - int(previous_rx)) / elapsed)
                            if (
                                isinstance(current_tx, int)
                                and previous_tx is not None
                                and int(previous_tx) >= 0
                                and current_tx >= int(previous_tx)
                            ):
                                tx_bps = int((current_tx - int(previous_tx)) / elapsed)

                    client["rx_bps"] = rx_bps
                    client["tx_bps"] = tx_bps
                    if isinstance(rx_bps, int):
                        router_rx_bps += rx_bps
                    if isinstance(tx_bps, int):
                        router_tx_bps += tx_bps

                conn.execute(
                    """
                    UPDATE router_status
                    SET reachable=?, status_text=?, version=?, hardware_model=?, detected_hostname=?, load_1m=?,
                        uptime_seconds=?, memory_used_pct=?, wifi_clients=?, wifi_clients_by_radio=?, wifi_clients_by_network=?, best_signal_dbm=?,
                        worst_signal_dbm=?, signal_histogram=?, rx_bps=?, tx_bps=?, latency_ms=?,
                        last_seen=?, last_error=?, updated_at=?
                    WHERE router_uuid=?
                    """,
                    (
                        item["reachable"],
                        item["status_text"],
                        item["version"],
                        item["hardware_model"],
                        item["detected_hostname"],
                        item["load_1m"],
                        item["uptime_seconds"],
                        item["memory_used_pct"],
                        item["wifi_clients"],
                        item["wifi_clients_by_radio"],
                        item["wifi_clients_by_network"],
                        item["best_signal_dbm"],
                        item["worst_signal_dbm"],
                        item["signal_histogram"],
                        router_rx_bps if client_associations else None,
                        router_tx_bps if client_associations else None,
                        item["latency_ms"],
                        item["last_seen"],
                        item["last_error"],
                        item["updated_at"],
                        item["router_uuid"],
                    ),
                )
                conn.execute("DELETE FROM router_client_status WHERE router_uuid=?", (item["router_uuid"],))
                for client in item.get("client_associations") or []:
                    conn.execute(
                        """
                        INSERT INTO router_client_status (
                            router_uuid, client_mac, ip_address, network_name, radio_name, signal_dbm,
                            rx_bytes, tx_bytes, rx_bps, tx_bps, connected_seconds, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item["router_uuid"],
                            client["client_mac"],
                            client.get("ip_address"),
                            client.get("network_name"),
                            client.get("radio_name"),
                            client.get("signal_dbm"),
                            client.get("rx_bytes"),
                            client.get("tx_bytes"),
                            client.get("rx_bps"),
                            client.get("tx_bps"),
                            client.get("connected_seconds"),
                            item["updated_at"],
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

    def router_action_command(self, action):
        if action == "reboot":
            return ["sh", "-c", "(reboot >/dev/null 2>&1 &)"]
        if action == "radios_on":
            return ["ubus", "call", "network.wireless", "up"]
        if action == "radios_off":
            return ["ubus", "call", "network.wireless", "down"]
        return None

    def apply_roaming_baseline(self, router, settings):
        address = router["address"]
        username = router.get("ssh_username") or "root"
        private_key = self.resolve_private_key(router["ssh_key_ref"], settings)

        if not address:
            return {
                "router_uuid": router["router_uuid"],
                "address": "",
                "ok": False,
                "message": "Missing router address.",
            }

        if not private_key:
            return {
                "router_uuid": router["router_uuid"],
                "address": address,
                "ok": False,
                "message": "No usable SSH private key available.",
            }

        script = r"""
set -eu
stamp="$(date +%Y%m%d-%H%M%S)"
cp /etc/config/wireless "/etc/config/wireless.pre-openwrt-admin-$stamp"
[ -f /etc/config/usteer ] && cp /etc/config/usteer "/etc/config/usteer.pre-openwrt-admin-$stamp" || true
if ! command -v usteerd >/dev/null 2>&1; then
  apk update >/tmp/apk-update.log 2>&1
  apk add usteer >/tmp/apk-add-usteer.log 2>&1
fi
if ! uci -q get usteer.@usteer[0] >/dev/null 2>&1; then
  uci add usteer usteer >/dev/null
fi
uci batch <<'UCI'
set wireless.radio0.channel='auto'
set wireless.radio1.channel='auto'
set wireless.wifinet0.ieee80211r='1'
set wireless.wifinet1.ieee80211r='1'
set wireless.wifinet0.ieee80211k='1'
set wireless.wifinet1.ieee80211k='1'
set wireless.wifinet0.ft_over_ds='0'
set wireless.wifinet1.ft_over_ds='0'
set wireless.wifinet0.bss_transition='1'
set wireless.wifinet1.bss_transition='1'
set wireless.wifinet0.wnm_sleep_mode='1'
set wireless.wifinet1.wnm_sleep_mode='1'
set wireless.wifinet0.wnm_sleep_mode_no_keys='1'
set wireless.wifinet1.wnm_sleep_mode_no_keys='1'
set usteer.@usteer[0].network='lan'
set usteer.@usteer[0].syslog='1'
set usteer.@usteer[0].local_mode='0'
set usteer.@usteer[0].ipv6='0'
set usteer.@usteer[0].debug_level='2'
set usteer.@usteer[0].assoc_steering='1'
set usteer.@usteer[0].probe_steering='1'
set usteer.@usteer[0].load_balancing_threshold='2'
set usteer.@usteer[0].signal_diff_threshold='8'
set usteer.@usteer[0].band_steering_interval='120000'
set usteer.@usteer[0].band_steering_min_snr='-60'
set usteer.@usteer[0].roam_scan_snr='-70'
set usteer.@usteer[0].roam_scan_tries='3'
set usteer.@usteer[0].roam_scan_interval='10000'
set usteer.@usteer[0].roam_trigger_snr='-75'
set usteer.@usteer[0].roam_trigger_interval='60000'
set usteer.@usteer[0].link_measurement_interval='30000'
del usteer.@usteer[0].ssid_list
add_list usteer.@usteer[0].ssid_list='KGMobile'
commit wireless
commit usteer
UCI
wifi reload
/etc/init.d/usteer enable
/etc/init.d/usteer restart
sleep 2
ubus call network.wireless status | grep -q '"up": true'
pgrep -af usteer >/dev/null 2>&1
"""

        result = self.run_ssh(
            address,
            private_key,
            ["sh", "-c", script],
            username=username,
            strip_output=False,
        )
        if result["timed_out"]:
            return {
                "router_uuid": router["router_uuid"],
                "address": address,
                "ok": False,
                "message": "Connection timed out",
            }

        if not result["ok"]:
            error_text = (result["stderr"] or result["stdout"] or "").strip()
            return {
                "router_uuid": router["router_uuid"],
                "address": address,
                "ok": False,
                "message": classify_ssh_error(error_text) if error_text else "Failed to apply roaming baseline.",
            }

        return {
            "router_uuid": router["router_uuid"],
            "address": address,
            "ok": True,
            "message": "ok",
        }

    def apply_system_update(self, router, settings):
        address = router["address"]
        username = router.get("ssh_username") or "root"
        private_key = self.resolve_private_key(router["ssh_key_ref"], settings)

        if not address:
            return {
                "router_uuid": router["router_uuid"],
                "address": "",
                "ok": False,
                "message": "Missing router address.",
            }

        if not private_key:
            return {
                "router_uuid": router["router_uuid"],
                "address": address,
                "ok": False,
                "message": "No usable SSH private key available.",
            }

        result = self.run_ssh(
            address,
            private_key,
            ["sh", "-c", "apk update && apk upgrade"],
            username=username,
            strip_output=False,
            timeout_seconds=600,
        )
        if result["timed_out"]:
            return {
                "router_uuid": router["router_uuid"],
                "address": address,
                "ok": False,
                "message": "System update timed out",
            }

        if not result["ok"]:
            error_text = (result["stderr"] or result["stdout"] or "").strip()
            return {
                "router_uuid": router["router_uuid"],
                "address": address,
                "ok": False,
                "message": error_text if error_text else "System update failed.",
            }

        return {
            "router_uuid": router["router_uuid"],
            "address": address,
            "ok": True,
            "message": "ok",
        }

    def perform_router_action(self, router, settings, action):
        address = router["address"]
        username = router.get("ssh_username") or "root"
        private_key = self.resolve_private_key(router["ssh_key_ref"], settings)
        if action == "apply_roaming_baseline":
            return self.apply_roaming_baseline(router, settings)
        if action == "sys_update":
            return self.apply_system_update(router, settings)
        command = self.router_action_command(action)

        if not address:
            return {
                "router_uuid": router["router_uuid"],
                "address": "",
                "ok": False,
                "message": "Missing router address.",
            }

        if not private_key:
            return {
                "router_uuid": router["router_uuid"],
                "address": address,
                "ok": False,
                "message": "No usable SSH private key available.",
            }

        if command is None:
            return {
                "router_uuid": router["router_uuid"],
                "address": address,
                "ok": False,
                "message": "Unsupported action.",
            }

        result = self.run_ssh(address, private_key, command, username=username)
        if result["timed_out"]:
            return {
                "router_uuid": router["router_uuid"],
                "address": address,
                "ok": False,
                "message": "Connection timed out",
            }

        if not result["ok"]:
            error_text = result["stderr"] or result["stdout"] or f"ssh exited with code {result['returncode']}"
            return {
                "router_uuid": router["router_uuid"],
                "address": address,
                "ok": False,
                "message": classify_ssh_error(error_text),
            }

        return {
            "router_uuid": router["router_uuid"],
            "address": address,
            "ok": True,
            "message": "ok",
        }

    def router_map(self):
        config = self.load_config()
        return config["settings"], {router["router_uuid"]: router for router in config["routers"]}

    def hash_content(self, content):
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def config_field_name(self, config_type):
        return f"sync_{config_type}_config_from"

    def config_spec(self, config_type):
        specs = {
            "wifi": {
                "path": WIRELESS_CONFIG_PATH,
                "apply_commands": [["wifi", "reload"]],
            },
            "system": {
                "path": SYSTEM_CONFIG_PATH,
                "apply_commands": [["/sbin/reload_config"]],
            },
            "firewall": {
                "path": FIREWALL_CONFIG_PATH,
                "apply_commands": [["/etc/init.d/firewall", "reload"]],
            },
            "dhcp": {
                "path": DHCP_CONFIG_PATH,
                "apply_commands": [["/etc/init.d/dnsmasq", "restart"]],
            },
            "rpcd": {
                "path": RPCD_CONFIG_PATH,
                "apply_commands": [["/etc/init.d/rpcd", "restart"]],
            },
        }
        return specs.get(config_type)

    def merge_system_hostname(self, source_content, target_content):
        source_lines = source_content.splitlines()
        target_lines = target_content.splitlines()

        target_hostname_line = None
        for line in target_lines:
            if line.strip().startswith("option hostname "):
                target_hostname_line = line
                break

        if target_hostname_line is None:
            return source_content

        replaced = False
        merged_lines = []
        inserted = False
        in_system_block = False
        for index, line in enumerate(source_lines):
            stripped = line.strip()
            if stripped.startswith("config "):
                if in_system_block and not inserted:
                    merged_lines.append(target_hostname_line)
                    inserted = True
                in_system_block = stripped == "config system"
            if in_system_block and stripped.startswith("option hostname "):
                merged_lines.append(target_hostname_line)
                replaced = True
                inserted = True
                continue
            merged_lines.append(line)
        if in_system_block and not inserted:
            merged_lines.append(target_hostname_line)
            inserted = True
        if not replaced and not inserted:
            return source_content
        trailing_newline = "\n" if source_content.endswith("\n") else ""
        return "\n".join(merged_lines) + trailing_newline

    def store_config_snapshot(self, router_uuid, config_type, content, fetched_at):
        content_hash = self.hash_content(content)
        with self._db_context() as conn:
            conn.execute(
                """
                INSERT INTO router_config_state (router_uuid, config_type, content_hash, content, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(router_uuid, config_type) DO UPDATE SET
                    content_hash=excluded.content_hash,
                    content=excluded.content,
                    fetched_at=excluded.fetched_at
                """,
                (router_uuid, config_type, content_hash, content, fetched_at),
            )
            conn.execute(
                """
                INSERT INTO router_config_backup (router_uuid, config_type, content_hash, content, created_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(router_uuid, config_type, content_hash) DO UPDATE SET
                    last_seen_at=excluded.last_seen_at
                """,
                (router_uuid, config_type, content_hash, content, fetched_at, fetched_at),
            )
            stale_rows = conn.execute(
                """
                SELECT content_hash FROM router_config_backup
                WHERE router_uuid=? AND config_type=?
                ORDER BY last_seen_at DESC, created_at DESC
                LIMIT -1 OFFSET ?
                """,
                (router_uuid, config_type, self._config_backup_limit),
            ).fetchall()
            for row in stale_rows:
                conn.execute(
                    "DELETE FROM router_config_backup WHERE router_uuid=? AND config_type=? AND content_hash=?",
                    (router_uuid, config_type, row["content_hash"]),
                )
        return content_hash

    def config_backups(self, router_uuid, config_type):
        with self._db_context() as conn:
            rows = conn.execute(
                """
                SELECT content_hash, created_at, last_seen_at, length(content) AS size_bytes
                FROM router_config_backup
                WHERE router_uuid=? AND config_type=?
                ORDER BY last_seen_at DESC, created_at DESC
                """,
                (router_uuid, config_type),
            ).fetchall()
        return [dict(row) for row in rows]

    def config_backup_content(self, router_uuid, config_type, content_hash):
        with self._db_context() as conn:
            row = conn.execute(
                """
                SELECT content FROM router_config_backup
                WHERE router_uuid=? AND config_type=? AND content_hash=?
                """,
                (router_uuid, config_type, content_hash),
            ).fetchone()
        return None if row is None else row["content"]

    def status_row(self, router_uuid):
        with self._db_context() as conn:
            row = conn.execute(
                """
                SELECT router_uuid, address, configured_hostname, hardware_model
                FROM router_status
                WHERE router_uuid=?
                """,
                (router_uuid,),
            ).fetchone()
        return None if row is None else dict(row)

    def fetch_router_config(self, router, settings, config_type):
        address = router["address"]
        username = router.get("ssh_username") or "root"
        private_key = self.resolve_private_key(router["ssh_key_ref"], settings)
        spec = self.config_spec(config_type)
        if not address:
            return {"ok": False, "message": "Missing router address."}
        if not private_key:
            return {"ok": False, "message": "No usable SSH private key available."}
        if spec is None:
            return {"ok": False, "message": "Unsupported config type."}

        result = self.run_ssh(address, private_key, ["cat", spec["path"]], strip_output=False, username=username)
        if result["timed_out"]:
            return {"ok": False, "message": "Connection timed out"}
        if not result["ok"]:
            error_text = result["stderr"] or result["stdout"] or f"ssh exited with code {result['returncode']}"
            return {"ok": False, "message": classify_ssh_error(error_text)}

        content = result["stdout"]
        fetched_at = now_iso()
        content_hash = self.store_config_snapshot(router["router_uuid"], config_type, content, fetched_at)
        return {
            "ok": True,
            "content": content,
            "content_hash": content_hash,
            "fetched_at": fetched_at,
        }

    def verify_router_config(self, router, settings, config_type, expected_content=None):
        if config_type == "wifi":
            return self.verify_wireless_status(router, settings)
        if config_type == "system":
            return self.verify_system_config(router, settings, expected_content or "")
        return {"ok": False, "message": "Unsupported config type."}

    def verify_wireless_status(self, router, settings):
        address = router["address"]
        username = router.get("ssh_username") or "root"
        private_key = self.resolve_private_key(router["ssh_key_ref"], settings)
        if not address or not private_key:
            return {"ok": False, "message": "Router not reachable for verification."}

        time.sleep(2)
        result = self.run_ssh(address, private_key, ["ubus", "call", "network.wireless", "status"], username=username)
        if result["timed_out"]:
            return {"ok": False, "message": "Timed out waiting for Wi-Fi status."}
        if not result["ok"]:
            error_text = result["stderr"] or result["stdout"] or f"ssh exited with code {result['returncode']}"
            return {"ok": False, "message": classify_ssh_error(error_text)}

        try:
            payload = json.loads(result["stdout"])
        except json.JSONDecodeError:
            return {"ok": False, "message": "Unable to parse Wi-Fi status."}

        radio_states = []
        for name, radio in payload.items():
            if not isinstance(radio, dict):
                continue
            up = bool(radio.get("up"))
            disabled = bool(radio.get("disabled"))
            retry_failed = bool(radio.get("retry_setup_failed"))
            pending = bool(radio.get("pending"))
            if up and not disabled and not retry_failed and not pending:
                radio_states.append(True)
            else:
                radio_states.append(False)
        if radio_states and all(radio_states):
            return {"ok": True, "message": "ok"}
        return {"ok": False, "message": "Wi-Fi did not come back up normally."}

    def verify_system_config(self, router, settings, expected_content):
        address = router["address"]
        username = router.get("ssh_username") or "root"
        private_key = self.resolve_private_key(router["ssh_key_ref"], settings)
        if not address:
            return {"ok": False, "message": "Missing router address."}
        if not private_key:
            return {"ok": False, "message": "No usable SSH private key available."}

        result = self.run_ssh(address, private_key, ["cat", SYSTEM_CONFIG_PATH], strip_output=False, username=username)
        if result["timed_out"]:
            return {"ok": False, "message": "Timed out reading system config."}
        if not result["ok"]:
            error_text = result["stderr"] or result["stdout"] or f"ssh exited with code {result['returncode']}"
            return {"ok": False, "message": classify_ssh_error(error_text)}
        if result["stdout"] != expected_content:
            return {"ok": False, "message": "System config did not match the applied content."}
        return {"ok": True, "message": "ok"}

    def apply_router_config(self, router, settings, config_type, content, current_target_content=None, preserve_target_hostname=False):
        address = router["address"]
        username = router.get("ssh_username") or "root"
        private_key = self.resolve_private_key(router["ssh_key_ref"], settings)
        spec = self.config_spec(config_type)
        if not address:
            return {"ok": False, "message": "Missing router address."}
        if not private_key:
            return {"ok": False, "message": "No usable SSH private key available."}
        if spec is None:
            return {"ok": False, "message": "Unsupported config type."}

        if config_type == "system" and preserve_target_hostname and current_target_content is not None:
            content = self.merge_system_hostname(content, current_target_content)

        write_result = self.run_ssh(
            address,
            private_key,
            ["sh", "-c", f"cat > {spec['path']}"],
            input_text=content,
            username=username,
        )
        if write_result["timed_out"]:
            return {"ok": False, "message": "Connection timed out"}
        if not write_result["ok"]:
            error_text = write_result["stderr"] or write_result["stdout"] or f"ssh exited with code {write_result['returncode']}"
            return {"ok": False, "message": classify_ssh_error(error_text)}

        for command in spec["apply_commands"]:
            reload_result = self.run_ssh(address, private_key, command, username=username)
            if reload_result["timed_out"]:
                return {"ok": False, "message": f"Timed out during {config_type} reload."}
            if not reload_result["ok"]:
                error_text = reload_result["stderr"] or reload_result["stdout"] or f"ssh exited with code {reload_result['returncode']}"
                return {"ok": False, "message": classify_ssh_error(error_text)}

        verify = self.verify_router_config(router, settings, config_type, content)
        if not verify["ok"]:
            return verify

        self.store_config_snapshot(router["router_uuid"], config_type, content, now_iso())
        return {"ok": True, "message": "ok"}

    def run_router_action(self, action, router_uuids):
        config = self.load_config()
        settings = config["settings"]
        routers = {router["router_uuid"]: router for router in config["routers"]}
        selected = [routers[router_uuid] for router_uuid in router_uuids if router_uuid in routers]

        if not selected:
            return {
                "status": "error",
                "message": "No matching routers selected.",
                "results": [],
            }

        futures = [self.executor.submit(self.perform_router_action, router, settings, action) for router in selected]
        results = [future.result() for future in as_completed(futures)]
        return {
            "status": "ok",
            "action": action,
            "requested": len(router_uuids),
            "matched": len(selected),
            "successful": sum(1 for item in results if item["ok"]),
            "failed": sum(1 for item in results if not item["ok"]),
            "results": sorted(results, key=lambda item: item.get("address", "")),
        }

    def fetch_all_configs(self, config_type):
        settings, routers = self.router_map()
        futures = {
            self.executor.submit(self.fetch_router_config, router, settings, config_type): router
            for router in routers.values()
        }
        results = {}
        for future in as_completed(futures):
            router = futures[future]
            results[router["router_uuid"]] = future.result()
        return settings, routers, results

    def sync_configs_by_type(self, router_uuids, config_type):
        settings, routers, fetched = self.fetch_all_configs(config_type)
        selected = [routers[router_uuid] for router_uuid in router_uuids if router_uuid in routers]
        if not selected:
            return {"status": "error", "message": "No matching routers selected.", "results": []}

        results = []
        for router in selected:
            source_uuid = (router.get(self.config_field_name(config_type)) or "").strip()
            address = router.get("address") or ""
            if source_uuid == "":
                results.append({"router_uuid": router["router_uuid"], "address": address, "config_type": config_type, "ok": True, "changed": False, "message": f"No {config_type} sync source configured."})
                continue
            if source_uuid == router["router_uuid"]:
                results.append({"router_uuid": router["router_uuid"], "address": address, "config_type": config_type, "ok": False, "changed": False, "message": "Router cannot sync from itself."})
                continue
            if source_uuid not in routers:
                results.append({"router_uuid": router["router_uuid"], "address": address, "config_type": config_type, "ok": False, "changed": False, "message": "Sync source router not found."})
                continue

            source_router = routers[source_uuid]
            target_fetch = fetched.get(router["router_uuid"], {"ok": False, "message": "Config unavailable."})
            source_fetch = fetched.get(source_uuid, {"ok": False, "message": "Config unavailable."})
            if not target_fetch.get("ok"):
                results.append({"router_uuid": router["router_uuid"], "address": address, "config_type": config_type, "ok": False, "changed": False, "message": "Could not fetch target config: " + target_fetch.get("message", "error")})
                continue
            if not source_fetch.get("ok"):
                results.append({"router_uuid": router["router_uuid"], "address": address, "config_type": config_type, "ok": False, "changed": False, "message": "Could not fetch source config: " + source_fetch.get("message", "error")})
                continue

            target_status = self.status_row(router["router_uuid"]) or {}
            source_status = self.status_row(source_uuid) or {}
            target_model = (target_status.get("hardware_model") or "").strip()
            source_model = (source_status.get("hardware_model") or "").strip()
            if target_model and source_model and target_model != source_model:
                results.append({"router_uuid": router["router_uuid"], "address": address, "config_type": config_type, "ok": False, "changed": False, "message": "Sync source model does not match target."})
                continue

            if target_fetch["content_hash"] == source_fetch["content_hash"]:
                results.append({"router_uuid": router["router_uuid"], "address": address, "config_type": config_type, "ok": True, "changed": False, "message": "Already in sync."})
                continue

            apply_result = self.apply_router_config(
                router,
                settings,
                config_type,
                source_fetch["content"],
                current_target_content=target_fetch["content"],
                preserve_target_hostname=(config_type == "system"),
            )
            if apply_result["ok"]:
                results.append({"router_uuid": router["router_uuid"], "address": address, "config_type": config_type, "ok": True, "changed": True, "message": "Synced from " + (source_router.get("hostname") or source_router.get("address") or "source router") + "."})
                continue

            rollback_result = self.apply_router_config(router, settings, config_type, target_fetch["content"])
            if rollback_result["ok"]:
                results.append({"router_uuid": router["router_uuid"], "address": address, "config_type": config_type, "ok": False, "changed": False, "message": "Sync failed and previous config was restored: " + apply_result["message"]})
            else:
                results.append({"router_uuid": router["router_uuid"], "address": address, "config_type": config_type, "ok": False, "changed": False, "message": "Sync failed and rollback also failed: " + apply_result["message"] + " / " + rollback_result["message"]})

        return {
            "status": "ok",
            "action": f"sync_{config_type}",
            "requested": len(router_uuids),
            "matched": len(selected),
            "successful": sum(1 for item in results if item["ok"]),
            "failed": sum(1 for item in results if not item["ok"]),
            "changed": sum(1 for item in results if item.get("changed")),
            "results": sorted(results, key=lambda item: item.get("address", "")),
        }

    def restore_config_backup(self, router_uuid, config_type, content_hash):
        settings, routers = self.router_map()
        router = routers.get(router_uuid)
        if router is None:
            return {"status": "error", "message": "Router not found."}

        backup_content = self.config_backup_content(router_uuid, config_type, content_hash)
        if backup_content is None:
            return {"status": "error", "message": "Backup not found."}

        current_fetch = self.fetch_router_config(router, settings, config_type)
        if not current_fetch.get("ok"):
            return {"status": "error", "message": "Could not fetch current config: " + current_fetch.get("message", "error")}

        if current_fetch["content_hash"] == content_hash:
            return {"status": "ok", "message": "Router already has this config.", "restored": False}

        apply_result = self.apply_router_config(router, settings, config_type, backup_content)
        if apply_result["ok"]:
            return {"status": "ok", "message": "Backup restored.", "restored": True}

        rollback_result = self.apply_router_config(router, settings, config_type, current_fetch["content"])
        if rollback_result["ok"]:
            return {"status": "error", "message": "Restore failed and previous config was restored: " + apply_result["message"]}

        return {"status": "error", "message": "Restore failed and rollback also failed: " + apply_result["message"] + " / " + rollback_result["message"]}

    def sync_all_configs(self, router_uuids):
        all_results = []
        changed = 0
        successful = 0
        failed = 0
        for config_type in CONFIG_TYPES:
            result = self.sync_configs_by_type(router_uuids, config_type)
            if result.get("status") != "ok":
                return result
            all_results.extend(result["results"])
            changed += result.get("changed", 0)
            successful += result.get("successful", 0)
            failed += result.get("failed", 0)
        return {
            "status": "ok",
            "action": "sync_configs",
            "requested": len(router_uuids),
            "matched": len(router_uuids),
            "successful": successful,
            "failed": failed,
            "changed": changed,
            "results": sorted(all_results, key=lambda item: (item.get("address", ""), item.get("config_type", ""))),
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
        while not self.shutdown_event.wait(self._poll_interval):
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
        with self._db_context() as conn:
            rows = conn.execute(
                """
                SELECT router_status.router_uuid, router_status.address, router_status.configured_hostname, router_status.description, router_status.ssh_key_ref,
                       router_status.reachable, router_status.status_text, router_status.version, router_status.hardware_model, router_status.detected_hostname, router_status.load_1m,
                       router_status.uptime_seconds, router_status.memory_used_pct, router_status.wifi_clients, router_status.wifi_clients_by_radio, router_status.wifi_clients_by_network, router_status.best_signal_dbm,
                       router_status.worst_signal_dbm, router_status.signal_histogram, router_status.rx_bps, router_status.tx_bps, router_status.latency_ms,
                       router_status.last_seen, router_status.last_error, router_status.updated_at,
                       wifi_state.content_hash AS wifi_content_hash,
                       wifi_state.fetched_at AS wifi_fetched_at,
                       system_state.content_hash AS system_content_hash,
                       system_state.fetched_at AS system_fetched_at,
                       firewall_state.content_hash AS firewall_content_hash,
                       firewall_state.fetched_at AS firewall_fetched_at,
                       dhcp_state.content_hash AS dhcp_content_hash,
                       dhcp_state.fetched_at AS dhcp_fetched_at,
                       rpcd_state.content_hash AS rpcd_content_hash,
                       rpcd_state.fetched_at AS rpcd_fetched_at
                FROM router_status
                LEFT JOIN router_config_state AS wifi_state
                  ON wifi_state.router_uuid = router_status.router_uuid AND wifi_state.config_type = 'wifi'
                LEFT JOIN router_config_state AS system_state
                  ON system_state.router_uuid = router_status.router_uuid AND system_state.config_type = 'system'
                LEFT JOIN router_config_state AS firewall_state
                  ON firewall_state.router_uuid = router_status.router_uuid AND firewall_state.config_type = 'firewall'
                LEFT JOIN router_config_state AS dhcp_state
                  ON dhcp_state.router_uuid = router_status.router_uuid AND dhcp_state.config_type = 'dhcp'
                LEFT JOIN router_config_state AS rpcd_state
                  ON rpcd_state.router_uuid = router_status.router_uuid AND rpcd_state.config_type = 'rpcd'
                ORDER BY router_status.address COLLATE NOCASE
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def client_rows(self):
        with self._db_context() as conn:
            rows = conn.execute(
                """
                SELECT router_client_status.router_uuid, router_client_status.client_mac, router_client_status.ip_address,
                       router_client_status.network_name, router_client_status.radio_name, router_client_status.signal_dbm,
                       router_client_status.rx_bytes, router_client_status.tx_bytes, router_client_status.rx_bps, router_client_status.tx_bps, router_client_status.connected_seconds,
                       router_client_status.updated_at,
                       router_status.address AS router_address, router_status.configured_hostname, router_status.detected_hostname
                FROM router_client_status
                JOIN router_status ON router_status.router_uuid = router_client_status.router_uuid
                ORDER BY router_client_status.client_mac COLLATE NOCASE,
                         router_status.address COLLATE NOCASE,
                         router_client_status.network_name COLLATE NOCASE
                """
            ).fetchall()
        return [dict(row) for row in rows]


STATE = None


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

    def _read_json_body(self):
        """Read and parse the JSON request body. Sends a 400 and returns None on error."""
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            return json.loads(raw_body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(400, {"status": "error", "message": "Invalid JSON payload"})
            return None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/v1/status":
            self._send(200, STATE.status_payload())
        elif parsed.path == "/v1/routers":
            self._send(200, {"status": "ok", "routers": STATE.router_rows()})
        elif parsed.path == "/v1/clients":
            self._send(200, {"status": "ok", "clients": STATE.client_rows()})
        elif parsed.path == "/v1/config-backups":
            router_uuid = (query.get("router_uuid") or [""])[0]
            config_type = (query.get("config_type") or [""])[0]
            if config_type not in CONFIG_TYPES:
                self._send(400, {"status": "error", "message": "Unsupported config type", "backups": []})
                return
            self._send(
                200,
                {
                    "status": "ok",
                    "router_uuid": router_uuid,
                    "config_type": config_type,
                    "backups": STATE.config_backups(router_uuid, config_type),
                },
            )
        else:
            self._send(404, {"status": "error", "message": "Not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/v1/poll-now":
            accepted = STATE.trigger_poll()
            self._send(200, {"status": "ok", "accepted": accepted})
            return

        payload = self._read_json_body()
        if payload is None:
            return

        if parsed.path == "/v1/router-actions":
            action = str(payload.get("action") or "").strip()
            routers = payload.get("routers") or []
            if not isinstance(routers, list):
                self._send(400, {"status": "error", "message": "Routers must be a list"})
                return
            result = STATE.run_router_action(action, [str(item) for item in routers if str(item).strip()])
            self._send(200 if result.get("status") == "ok" else 400, result)
        elif parsed.path == "/v1/config-sync":
            routers = payload.get("routers") or []
            if not isinstance(routers, list):
                self._send(400, {"status": "error", "message": "Routers must be a list"})
                return
            result = STATE.sync_all_configs([str(item) for item in routers if str(item).strip()])
            self._send(200 if result.get("status") == "ok" else 400, result)
        elif parsed.path == "/v1/config-restore":
            router_uuid = str(payload.get("router_uuid") or "").strip()
            config_type = str(payload.get("config_type") or "").strip()
            content_hash = str(payload.get("content_hash") or "").strip()
            if config_type not in CONFIG_TYPES:
                self._send(400, {"status": "error", "message": "Unsupported config type"})
                return
            result = STATE.restore_config_backup(router_uuid, config_type, content_hash)
            self._send(200 if result.get("status") == "ok" else 400, result)
        else:
            self._send(404, {"status": "error", "message": "Not found"})


def main():
    global STATE
    STATE = BrokerState()
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
