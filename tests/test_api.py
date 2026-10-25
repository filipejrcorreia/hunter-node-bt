"""Unit tests for BLE authentication, command transport, and response handling."""

import asyncio
import importlib
import json
import sys
import types
import unittest
from pathlib import Path


COMPONENT_PATH = (
    Path(__file__).parent.parent
    / "custom_components"
    / "hunter_node_bt"
)


def _install_bleak_stubs() -> None:
    bleak = types.ModuleType("bleak")
    bleak.BleakClient = type("BleakClient", (), {})
    bleak_backends = types.ModuleType("bleak.backends")
    bleak_backends.__path__ = []
    bleak_device = types.ModuleType("bleak.backends.device")
    bleak_device.BLEDevice = type("BLEDevice", (), {})
    bleak_retry = types.ModuleType("bleak_retry_connector")
    bleak_retry.establish_connection = None
    sys.modules.update(
        {
            "bleak": bleak,
            "bleak.backends": bleak_backends,
            "bleak.backends.device": bleak_device,
            "bleak_retry_connector": bleak_retry,
        }
    )


def _load_api_module():
    _install_bleak_stubs()
    package_name = "_hunter_node_bt_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(COMPONENT_PATH)]
    sys.modules[package_name] = package
    return importlib.import_module(f"{package_name}.api")


api = _load_api_module()
protocol = importlib.import_module("_hunter_node_bt_test.protocol")


class FakeDevice:
    address = "00:11:22:33:44:55"


class FakeGattClient:
    def __init__(self, reply: bytes | None = b'{"Status":0}\x00') -> None:
        self.is_connected = True
        self.reply = reply
        self.notifications = {}
        self.writes = []
        self._command = bytearray()
        self.authenticated_pin: int | None = None

    async def start_notify(self, characteristic, callback) -> None:
        self.notifications[characteristic] = callback

    def emit(self, characteristic, data: bytes) -> None:
        self.notifications[characteristic](None, bytearray(data))

    async def write_gatt_char(self, characteristic, data, response=True) -> None:
        self.writes.append((characteristic, bytes(data), response))
        if characteristic == api.PIN_CHAR:
            packet_type, _, random_number, pin = protocol.parse_pin_info(
                protocol.xor_ac(bytes(data))
            )
            if packet_type == api._LOGIN_REQUEST:
                self.emit(
                    api.PIN_CHAR,
                    protocol.xor_ac(protocol.pin_info(2, random_number=0x2345)),
                )
            elif packet_type == api._LOGIN_CHALLENGE_RESPONSE:
                self.authenticated_pin = pin ^ random_number
                self.emit(
                    api.PIN_CHAR,
                    protocol.xor_ac(protocol.pin_info(4)),
                )
            return

        self._command.extend(data)
        try:
            json.loads(self._command)
        except json.JSONDecodeError:
            return
        if self.reply is not None:
            midpoint = len(self.reply) // 2
            self.emit(api.MSG_TX, self.reply[:midpoint])
            self.emit(api.MSG_TX, self.reply[midpoint:])

    async def disconnect(self) -> None:
        self.is_connected = False


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gatt = FakeGattClient()

        async def establish_connection(_client_type, _device, _name):
            self.gatt.is_connected = True
            return self.gatt

        api.establish_connection = establish_connection

    def client(self, pin: int = 0):
        return api.HunterNodeBTClient(FakeDevice(), pin)

    def test_authenticates_and_sends_commands_in_twenty_byte_chunks(self):
        async def run():
            client = self.client(0x1234)
            await client.start_station(1, 123456)
            self.assertEqual(self.gatt.authenticated_pin, 0x1234)
            writes = [
                (data, response)
                for char, data, response in self.gatt.writes
                if char == api.MSG_RX
            ]
            payload = b"".join(data for data, _ in writes)
            self.assertEqual(
                json.loads(payload),
                {"Manual": {"StationNumber": 1, "RunTime": 123456}},
            )
            self.assertTrue(all(response for _, response in writes))
            self.assertTrue(all(len(data) <= 20 for data, _ in writes))
            self.assertGreater(len(writes), 1)
            self.assertTrue(
                all(
                    not response
                    for char, _, response in self.gatt.writes
                    if char == api.PIN_CHAR
                )
            )
            self.assertIsNone(client._msg_future)

        asyncio.run(run())

    def test_read_accepts_fragmented_response_and_discards_old_buffer(self):
        async def run():
            self.gatt.reply = b'{"State":{"ControllerState":0}}\x00'
            client = self.client()
            client._msg_buf.append(b"stale fragment")
            self.assertEqual(await client.read_state(), {"State": {"ControllerState": 0}})

        asyncio.run(run())

    def test_controller_setting_commands_write_expected_json(self):
        async def run():
            client = self.client()
            for command, expected in (
                (
                    client.set_programmable_days_off(1792972800),
                    {"Controller": {"ProgrammableDaysOff": 1792972800}},
                ),
                (
                    client.set_current_time(1792935208),
                    {"Controller": {"CurrentTime": 1792935208}},
                ),
                (
                    client.set_controller_off(True),
                    {"Controller": {"ControllerOff": True}},
                ),
                (
                    client.set_season_adjust(80),
                    {
                        "Controller": {
                            "SeasonAdjust": 80,
                            "SeasonAdjustByMonthEnable": False,
                        }
                    },
                ),
                (
                    client.set_season_adjust_by_month(True),
                    {"Controller": {"SeasonAdjustByMonthEnable": True}},
                ),
            ):
                self.gatt.writes.clear()
                self.gatt._command.clear()
                await command
                payload = b"".join(
                    data for char, data, _ in self.gatt.writes if char == api.MSG_RX
                )
                self.assertEqual(json.loads(payload), expected)

        asyncio.run(run())

    def test_section_reads_send_matching_read_command(self):
        async def run():
            self.gatt.reply = b'{"Sensor":{"Battery":80}}\x00'
            self.assertEqual(
                await self.client().read_sensor(), {"Sensor": {"Battery": 80}}
            )
            payload = b"".join(
                data for char, data, _ in self.gatt.writes if char == api.MSG_RX
            )
            self.assertEqual(json.loads(payload), {"Read": "Section_Sensor"})

        asyncio.run(run())

    def test_malformed_json_is_reported_as_connection_error(self):
        async def run():
            self.gatt.reply = b"{invalid}\x00"
            with self.assertRaisesRegex(api.HunterConnectionError, "Invalid JSON"):
                await self.client().read_state()
            self.assertFalse(self.gatt.is_connected)

        asyncio.run(run())

    def test_empty_response_is_not_treated_as_success(self):
        async def run():
            self.gatt.reply = b"\x00"
            with self.assertRaisesRegex(api.HunterConnectionError, "Empty response"):
                await self.client().stop_all()
            self.assertFalse(self.gatt.is_connected)

        asyncio.run(run())

    def test_unexpected_status_response_does_not_report_success(self):
        async def run():
            self.gatt.reply = b'{"Status":7}\x00'
            with self.assertRaisesRegex(api.HunterConnectionError, "status=7"):
                await self.client().stop_all()
            self.assertTrue(self.gatt.is_connected)

        asyncio.run(run())

    def test_timeout_disconnects_and_clears_response_state(self):
        async def run():
            self.gatt.reply = None
            client = self.client()
            original_timeout = api.COMMAND_TIMEOUT
            api.COMMAND_TIMEOUT = 0.01
            try:
                with self.assertRaisesRegex(api.HunterConnectionError, "Timed out"):
                    await client.read_state()
            finally:
                api.COMMAND_TIMEOUT = original_timeout
            self.assertFalse(self.gatt.is_connected)
            self.assertIsNone(client._client)
            self.assertIsNone(client._msg_future)

        asyncio.run(run())

    def test_oversized_response_is_rejected_and_disconnects(self):
        async def run():
            self.gatt.reply = b"x" * (protocol.MAX_RESPONSE_SIZE + 1) + b"\x00"
            with self.assertRaisesRegex(api.HunterConnectionError, "exceeded"):
                await self.client().read_state()
            self.assertFalse(self.gatt.is_connected)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
