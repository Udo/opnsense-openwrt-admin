import importlib.util
import tempfile
import unittest
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
        self.module.DATA_DIR = base / "data"
        self.module.DB_PATH = self.module.DATA_DIR / "state.sqlite"
        self.module.KEY_DIR = self.module.DATA_DIR / "keys"
        self.module.CONTROL_SOCKET_DIR = self.module.DATA_DIR / "control"
        self.module.KNOWN_HOSTS_PATH = self.module.DATA_DIR / "known_hosts"
        self.module.CONFIG_XML_PATH = base / "config.xml"
        self.module.CONFIG_XML_PATH.write_text("<config/>", encoding="utf-8")
        self.state = self.module.BrokerState()

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


if __name__ == "__main__":
    unittest.main()
