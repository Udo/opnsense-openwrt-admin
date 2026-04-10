import importlib.util
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


BROKER_PATH = Path(__file__).resolve().parents[1] / "src/opnsense/scripts/OPNsense/OpenWrtAdmin/broker.py"


def load_broker_module():
    spec = importlib.util.spec_from_file_location("openwrtadmin_broker", BROKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BrokerStateTestCase(unittest.TestCase):
    def setUp(self):
        self.module = load_broker_module()
        self.tempdir = tempfile.TemporaryDirectory()
        base = Path(self.tempdir.name)
        config_xml = base / "config.xml"
        config_xml.write_text("<config/>", encoding="utf-8")
        self.state = self.module.BrokerState(
            data_dir=base / "data",
            config_xml_path=config_xml,
        )

    def tearDown(self):
        self.state.close()
        self.tempdir.cleanup()

    def test_merge_system_hostname_preserves_target_hostname(self):
        source = "\n".join(
            [
                "config system",
                "\toption hostname 'AP-100'",
                "\toption timezone 'UTC'",
                "",
            ]
        )
        target = "\n".join(
            [
                "config system",
                "\toption hostname 'AP-101'",
                "\toption timezone 'UTC'",
                "",
            ]
        )

        merged = self.state.merge_system_hostname(source, target)

        self.assertIn("option hostname 'AP-101'", merged)
        self.assertNotIn("option hostname 'AP-100'", merged)

    def test_store_config_snapshot_deduplicates_and_limits_backups(self):
        for idx in range(10):
            self.state.store_config_snapshot(
                "router-1",
                "system",
                f"config system\n\toption timezone 'UTC{idx}'\n",
                f"2026-04-08T23:{idx:02d}:00+00:00",
            )

        backups = self.state.config_backups("router-1", "system")
        self.assertEqual(len(backups), 8)

        self.state.store_config_snapshot(
            "router-1",
            "system",
            "config system\n\toption timezone 'UTC9'\n",
            "2026-04-09T00:00:00+00:00",
        )
        backups_after_duplicate = self.state.config_backups("router-1", "system")
        self.assertEqual(len(backups_after_duplicate), 8)
        self.assertEqual(backups_after_duplicate[0]["content_hash"], backups[0]["content_hash"])

    def test_sync_system_config_preserves_target_hostname(self):
        routers = {
            "source": {
                "router_uuid": "source",
                "address": "10.0.0.10",
                "hostname": "AP-100",
                "sync_system_config_from": "",
                "ssh_key_ref": "system:/root/.ssh/id_ed25519.pub",
            },
            "target": {
                "router_uuid": "target",
                "address": "10.0.0.11",
                "hostname": "AP-101",
                "sync_system_config_from": "source",
                "ssh_key_ref": "system:/root/.ssh/id_ed25519.pub",
            },
        }
        fetched = {
            "source": {
                "ok": True,
                "content": "config system\n\toption hostname 'AP-100'\n\toption timezone 'UTC'\n",
                "content_hash": "source-hash",
            },
            "target": {
                "ok": True,
                "content": "config system\n\toption hostname 'AP-101'\n\toption timezone 'CET-1CEST'\n",
                "content_hash": "target-hash",
            },
        }

        applied = {}

        def fake_apply(router, settings, config_type, content, current_target_content=None, preserve_target_hostname=False):
            applied["router_uuid"] = router["router_uuid"]
            applied["config_type"] = config_type
            applied["content"] = content
            applied["current_target_content"] = current_target_content
            applied["preserve_target_hostname"] = preserve_target_hostname
            merged = content
            if config_type == "system" and preserve_target_hostname:
                merged = self.state.merge_system_hostname(content, current_target_content or "")
            self.state.store_config_snapshot(router["router_uuid"], config_type, merged, "2026-04-09T00:00:00+00:00")
            return {"ok": True, "message": "ok"}

        with mock.patch.object(self.state, "fetch_all_configs", return_value=({}, routers, fetched)), \
            mock.patch.object(self.state, "status_row", side_effect=lambda router_uuid: {
                "source": {"hardware_model": "D-Link"},
                "target": {"hardware_model": "D-Link"},
            }[router_uuid]), \
            mock.patch.object(self.state, "apply_router_config", side_effect=fake_apply):
            result = self.state.sync_configs_by_type(["target"], "system")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["changed"], 1)
        self.assertTrue(applied["preserve_target_hostname"])
        self.assertEqual(applied["router_uuid"], "target")

        stored = self.state.config_backup_content("target", "system", self.state.config_backups("target", "system")[0]["content_hash"])
        self.assertIn("option hostname 'AP-101'", stored)
        self.assertNotIn("option hostname 'AP-100'", stored)

    def test_classify_ssh_error_maps_common_failures(self):
        self.assertEqual(self.module.classify_ssh_error("ssh: connect to host 10.0.0.1 port 22: No route to host"), "No route to host")
        self.assertEqual(self.module.classify_ssh_error("Permission denied (publickey)."), "SSH auth failed")
        self.assertEqual(self.module.classify_ssh_error(""), "Offline")

    def test_config_spec_covers_supported_sync_types(self):
        self.assertEqual(self.state.config_spec("wifi")["path"], "/etc/config/wireless")
        self.assertEqual(self.state.config_spec("system")["path"], "/etc/config/system")
        self.assertEqual(self.state.config_spec("firewall")["path"], "/etc/config/firewall")
        self.assertEqual(self.state.config_spec("dhcp")["path"], "/etc/config/dhcp")
        self.assertEqual(self.state.config_spec("rpcd")["path"], "/etc/config/rpcd")
        self.assertIsNone(self.state.config_spec("unknown"))

    def test_parse_client_associations_extracts_signal_and_byte_counters(self):
        associations = self.state.parse_client_associations(
            [
                {
                    "radio": "phy0-ap0",
                    "network": "TestSSID",
                    "payload": {
                        "clients": {
                            "AA-BB-CC-DD-EE-FF": {
                                "signal": -54,
                                "ipaddr": "192.0.2.23",
                                "bytes": {
                                    "rx": 12345,
                                    "tx": 67890,
                                },
                                "connected_time": 321,
                            }
                        }
                    },
                }
            ]
        )

        self.assertEqual(len(associations), 1)
        self.assertEqual(associations[0]["client_mac"], "aa:bb:cc:dd:ee:ff")
        self.assertEqual(associations[0]["network_name"], "TestSSID")
        self.assertEqual(associations[0]["radio_name"], "phy0-ap0")
        self.assertEqual(associations[0]["signal_dbm"], -54)
        self.assertEqual(associations[0]["ip_address"], "192.0.2.23")
        self.assertEqual(associations[0]["rx_bytes"], 12345)
        self.assertEqual(associations[0]["tx_bytes"], 67890)
        self.assertEqual(associations[0]["connected_seconds"], 321)

    def test_write_poll_results_computes_bandwidth_deltas(self):
        router = {
            "router_uuid": "router-1",
            "address": "192.0.2.10",
            "hostname": "AP-1",
            "description": "",
            "ssh_key_ref": "system:/root/.ssh/id_ed25519.pub",
        }
        self.state.sync_router_rows([router])

        self.state.write_poll_results(
            [router],
            [
                {
                    "router_uuid": "router-1",
                    "reachable": 1,
                    "status_text": "Healthy | 1m up",
                    "version": "OpenWrt test",
                    "hardware_model": "Test AP",
                    "detected_hostname": "AP-1",
                    "load_1m": 0.1,
                    "uptime_seconds": 60,
                    "memory_used_pct": 50,
                    "wifi_clients": 1,
                    "wifi_clients_by_radio": None,
                    "wifi_clients_by_network": None,
                    "best_signal_dbm": -50,
                    "worst_signal_dbm": -50,
                    "signal_histogram": None,
                    "latency_ms": 10,
                    "last_seen": "2026-04-09T00:00:00+00:00",
                    "last_error": "",
                    "updated_at": "2026-04-09T00:00:00+00:00",
                    "client_associations": [
                        {
                            "client_mac": "aa:bb:cc:dd:ee:ff",
                            "ip_address": "192.0.2.23",
                            "network_name": "TestSSID",
                            "radio_name": "phy0-ap0",
                            "signal_dbm": -50,
                            "rx_bytes": 1000,
                            "tx_bytes": 2000,
                            "connected_seconds": None,
                        }
                    ],
                }
            ],
        )

        self.state.write_poll_results(
            [router],
            [
                {
                    "router_uuid": "router-1",
                    "reachable": 1,
                    "status_text": "Healthy | 2m up",
                    "version": "OpenWrt test",
                    "hardware_model": "Test AP",
                    "detected_hostname": "AP-1",
                    "load_1m": 0.1,
                    "uptime_seconds": 120,
                    "memory_used_pct": 50,
                    "wifi_clients": 1,
                    "wifi_clients_by_radio": None,
                    "wifi_clients_by_network": None,
                    "best_signal_dbm": -49,
                    "worst_signal_dbm": -49,
                    "signal_histogram": None,
                    "latency_ms": 12,
                    "last_seen": "2026-04-09T00:00:10+00:00",
                    "last_error": "",
                    "updated_at": "2026-04-09T00:00:10+00:00",
                    "client_associations": [
                        {
                            "client_mac": "aa:bb:cc:dd:ee:ff",
                            "ip_address": "192.0.2.23",
                            "network_name": "TestSSID",
                            "radio_name": "phy0-ap0",
                            "signal_dbm": -49,
                            "rx_bytes": 6000,
                            "tx_bytes": 5000,
                            "connected_seconds": None,
                        }
                    ],
                }
            ],
        )

        with self.state._db_context() as conn:
            client_row = conn.execute(
                "SELECT rx_bps, tx_bps FROM router_client_status WHERE router_uuid=?",
                ("router-1",),
            ).fetchone()
            router_row = conn.execute(
                "SELECT rx_bps, tx_bps FROM router_status WHERE router_uuid=?",
                ("router-1",),
            ).fetchone()

        self.assertEqual(client_row["rx_bps"], 500)
        self.assertEqual(client_row["tx_bps"], 300)
        self.assertEqual(router_row["rx_bps"], 500)
        self.assertEqual(router_row["tx_bps"], 300)

    def test_parse_network_stats_tracks_zero_client_networks_and_signal_summary(self):
        network_stats = self.state.parse_network_stats(
            [
                {
                    "radio": "phy0-ap0",
                    "network": "TestSSID",
                    "payload": {
                        "clients": {
                            "aa:bb:cc:dd:ee:ff": {"signal": -51},
                            "11:22:33:44:55:66": {"signal": -64},
                        }
                    },
                },
                {
                    "radio": "phy1-ap0",
                    "network": "GuestSSID",
                    "payload": {
                        "clients": {}
                    },
                },
            ]
        )

        self.assertEqual(network_stats[0]["network_name"], "GuestSSID")
        self.assertEqual(network_stats[0]["client_count"], 0)
        self.assertEqual(network_stats[1]["network_name"], "TestSSID")
        self.assertEqual(network_stats[1]["client_count"], 2)
        self.assertEqual(network_stats[1]["signal_sum"], -115)
        self.assertEqual(network_stats[1]["signal_sample_count"], 2)
        self.assertEqual(network_stats[1]["best_signal_dbm"], -51)
        self.assertEqual(network_stats[1]["worst_signal_dbm"], -64)

    def test_stats_rows_aggregate_hourly_data_across_aps(self):
        routers = [
            {
                "router_uuid": "router-1",
                "address": "192.0.2.10",
                "hostname": "AP-1",
                "description": "",
                "ssh_key_ref": "system:/root/.ssh/id_ed25519.pub",
            },
            {
                "router_uuid": "router-2",
                "address": "192.0.2.11",
                "hostname": "AP-2",
                "description": "",
                "ssh_key_ref": "system:/root/.ssh/id_ed25519.pub",
            },
        ]
        self.state.sync_router_rows(routers)

        self.state.write_poll_results(
            routers,
            [
                {
                    "router_uuid": "router-1",
                    "reachable": 1,
                    "status_text": "Healthy | 1m up",
                    "version": "OpenWrt test",
                    "hardware_model": "Test AP",
                    "detected_hostname": "AP-1",
                    "load_1m": 0.1,
                    "uptime_seconds": 60,
                    "memory_used_pct": 50,
                    "wifi_clients": 2,
                    "wifi_clients_by_radio": None,
                    "wifi_clients_by_network": None,
                    "radio_channels": None,
                    "best_signal_dbm": -50,
                    "worst_signal_dbm": -60,
                    "signal_histogram": None,
                    "latency_ms": 10,
                    "last_seen": "2026-04-09T00:05:00+00:00",
                    "last_error": "",
                    "updated_at": "2026-04-09T00:05:00+00:00",
                    "client_associations": [],
                    "network_stats": [
                        {
                            "network_name": "TestSSID",
                            "client_count": 2,
                            "signal_sum": -110,
                            "signal_sample_count": 2,
                            "best_signal_dbm": -50,
                            "worst_signal_dbm": -60,
                        }
                    ],
                },
                {
                    "router_uuid": "router-2",
                    "reachable": 1,
                    "status_text": "Healthy | 1m up",
                    "version": "OpenWrt test",
                    "hardware_model": "Test AP",
                    "detected_hostname": "AP-2",
                    "load_1m": 0.1,
                    "uptime_seconds": 60,
                    "memory_used_pct": 50,
                    "wifi_clients": 1,
                    "wifi_clients_by_radio": None,
                    "wifi_clients_by_network": None,
                    "radio_channels": None,
                    "best_signal_dbm": -55,
                    "worst_signal_dbm": -55,
                    "signal_histogram": None,
                    "latency_ms": 10,
                    "last_seen": "2026-04-09T00:15:00+00:00",
                    "last_error": "",
                    "updated_at": "2026-04-09T00:15:00+00:00",
                    "client_associations": [],
                    "network_stats": [
                        {
                            "network_name": "TestSSID",
                            "client_count": 1,
                            "signal_sum": -55,
                            "signal_sample_count": 1,
                            "best_signal_dbm": -55,
                            "worst_signal_dbm": -55,
                        }
                    ],
                },
            ],
        )

        payload = self.state.stats_rows(
            "2026-04-09T00:00:00+00:00",
            "2026-04-09T01:00:00+00:00",
            [],
            [],
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(len(payload["rows"]), 1)
        row = payload["rows"][0]
        self.assertEqual(row["network_name"], "TestSSID")
        self.assertAlmostEqual(row["avg_clients"], 1.5)
        self.assertAlmostEqual(row["avg_signal_dbm"], -55.0)
        self.assertEqual(row["best_signal_dbm"], -50)
        self.assertEqual(row["worst_signal_dbm"], -60)

    def test_cleanup_old_hourly_stats_respects_retention_days(self):
        with self.state._db_context() as conn:
            conn.execute(
                """
                INSERT INTO router_network_hourly_stats (
                    router_uuid, network_name, hour_bucket, sample_count, client_count_sum,
                    signal_sum, signal_sample_count, best_signal_dbm, worst_signal_dbm, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "router-1",
                    "TestSSID",
                    "2026-04-08T00:00:00+00:00",
                    1,
                    1,
                    -55,
                    1,
                    -55,
                    -55,
                    "2026-04-08T00:00:00+00:00",
                ),
            )

        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 4, 10, 0, 0, 0, tzinfo=timezone.utc)

        self.state._stats_retention_days = 1
        with mock.patch.object(self.module, "datetime", FrozenDateTime):
            with self.state._db_context() as conn:
                self.state.cleanup_old_hourly_stats(conn)

        with self.state._db_context() as conn:
            count = conn.execute("SELECT COUNT(*) FROM router_network_hourly_stats").fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
