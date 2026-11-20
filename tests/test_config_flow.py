"""Tests for picking the controller's Bluetooth address in the config flow."""

import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

_BLEAK_MODULES = ("bleak", "bleak.backends", "bleak.backends.device", "bleak_retry_connector")


def _import_config_flow():
    """Import the config flow with the real bleak, not test_api's stubs."""
    stubs = {
        name: sys.modules.pop(name)
        for name in _BLEAK_MODULES
        if name in sys.modules and getattr(sys.modules[name], "__file__", None) is None
    }
    try:
        return importlib.import_module("custom_components.hunter_node_bt.config_flow")
    except ImportError:  # Home Assistant isn't installed
        return None
    finally:
        for name, module in stubs.items():
            sys.modules.setdefault(name, module)


config_flow = _import_config_flow()

NUS = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"


def _info(address, name, rssi, uuids=()):
    return SimpleNamespace(address=address, name=name, rssi=rssi, service_uuids=list(uuids))


@unittest.skipIf(config_flow is None, "Home Assistant is not installed")
class NormalizeAddressTest(unittest.TestCase):
    def test_formats_home_assistant_uses(self):
        expected = "AA:BB:CC:DD:EE:0F"
        for value in (
            "AA:BB:CC:DD:EE:0F",
            "aa:bb:cc:dd:ee:0f",
            "aa-bb-cc-dd-ee-0f",
            " aabbccddee0f ",
            "AA BB CC DD EE 0F",
        ):
            with self.subTest(value=value):
                self.assertEqual(config_flow.normalize_address(value), expected)

    def test_rejects_what_isnt_an_address(self):
        for value in ("", "AA:BB:CC:DD:EE", "AA:BB:CC:DD:EE:0F:11", "garden controller", "GG:BB:CC:DD:EE:0F"):
            with self.subTest(value=value):
                self.assertIsNone(config_flow.normalize_address(value))


@unittest.skipIf(config_flow is None, "Home Assistant is not installed")
class AddressOptionsTest(unittest.TestCase):
    def _options(self, infos, configured=()):
        flow = config_flow.HunterConfigFlow()
        flow.hass = object()
        with (
            patch.object(config_flow.bluetooth, "async_discovered_service_info", return_value=infos),
            patch.object(flow, "_async_current_ids", return_value=set(configured)),
        ):
            return flow._address_options()

    def test_controllers_first_then_everything_else_by_signal(self):
        options = self._options(
            [
                _info("11:11:11:11:11:11", "Kettle", -50),
                _info("22:22:22:22:22:22", "Garden", -90, [NUS.upper()]),
                _info("33:33:33:33:33:33", None, -60),
                _info("44:44:44:44:44:44", "Already added", -40, [NUS]),
            ],
            configured={"44:44:44:44:44:44"},
        )
        self.assertEqual(
            [option["value"] for option in options],
            ["22:22:22:22:22:22", "11:11:11:11:11:11", "33:33:33:33:33:33"],
        )
        self.assertEqual(options[0]["label"], "Garden (22:22:22:22:22:22, -90 dBm)")
        self.assertEqual(options[2]["label"], "Unnamed device (33:33:33:33:33:33, -60 dBm)")


@unittest.skipIf(config_flow is None, "Home Assistant is not installed")
class ActiveScanTest(unittest.IsolatedAsyncioTestCase):
    async def test_requests_an_active_scan_when_available(self):
        flow = config_flow.HunterConfigFlow()
        flow.hass = object()
        request = AsyncMock()
        with patch.object(config_flow.bluetooth, "async_request_active_scan", request, create=True):
            await flow._async_active_scan()
        request.assert_awaited_once_with(flow.hass, config_flow.ACTIVE_SCAN_SECONDS)

    async def test_a_failed_scan_request_is_not_fatal(self):
        flow = config_flow.HunterConfigFlow()
        flow.hass = object()
        request = AsyncMock(side_effect=RuntimeError("no scanners"))
        with patch.object(config_flow.bluetooth, "async_request_active_scan", request, create=True):
            await flow._async_active_scan()

    async def test_older_home_assistant_skips_it(self):
        flow = config_flow.HunterConfigFlow()
        flow.hass = object()
        with patch.object(config_flow, "bluetooth", SimpleNamespace()):
            await flow._async_active_scan()


if __name__ == "__main__":
    unittest.main()
