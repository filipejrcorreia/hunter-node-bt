"""Tests for the BLE protocol helpers shared by the integration and CLI."""

from datetime import datetime, timedelta, timezone
import json
import unittest

from hunter_node_bt_client import (
    _PROTOCOL,
    _pin_info,
    _xor_ac,
    chunk_payload,
    sanitize_hunter_json,
    validate_pin,
)


class ProtocolTests(unittest.TestCase):
    def test_xor_ac_preserves_zero_and_is_symmetric_for_nonzero_bytes(self):
        self.assertEqual(_xor_ac(bytes([0x00])), bytes([0x00]))
        self.assertEqual(_xor_ac(bytes([0x01])), bytes([0xAD]))
        self.assertEqual(_xor_ac(bytes([0xAD])), bytes([0x01]))

    def test_pin_info_is_six_byte_little_endian_packet(self):
        packet = _pin_info(1, 0, 0x1234, 0x5678)
        self.assertEqual(packet, bytes([1, 0, 0x34, 0x12, 0x78, 0x56]))
        self.assertEqual(_PROTOCOL.parse_pin_info(packet), (1, 0, 0x1234, 0x5678))

    def test_pin_validation_accepts_uint16_boundaries(self):
        self.assertEqual(validate_pin("0"), 0)
        self.assertEqual(validate_pin(65535), 65535)

    def test_pin_validation_rejects_values_outside_uint16(self):
        for pin in (-1, 65536, 1.5, 1.0, True, "not-a-pin"):
            with self.subTest(pin=pin), self.assertRaises(ValueError):
                validate_pin(pin)

    def test_payload_chunking_uses_twenty_byte_packets(self):
        payload = bytes(range(45))
        chunks = chunk_payload(payload)
        self.assertEqual([len(chunk) for chunk in chunks], [20, 20, 5])
        self.assertEqual(b"".join(chunks), payload)

    def test_payload_chunking_rejects_invalid_chunk_size(self):
        with self.assertRaises(ValueError):
            chunk_payload(b"payload", 0)

    def test_sanitize_json_repairs_known_firmware_quirks(self):
        corrupted = (
            '{"Station_1":{"Name":"Front","Cycl"Soak":0},'
            '"State":{"St"Remaining":0},'
            '"Controller":{"SeasonAdjustByMonthEnabl":true}}'
        )
        data = json.loads(sanitize_hunter_json(corrupted))
        self.assertEqual(data["Station_1"]["Cycle"], 0)
        self.assertEqual(data["Station_1"]["Soak"], 0)
        self.assertEqual(data["State"]["State"], 0)
        self.assertEqual(data["State"]["Remaining"], 0)
        self.assertTrue(data["Controller"]["SeasonAdjustByMonthEnable"])

    def test_nul_delimited_buffer_reassembles_fragments_and_clears(self):
        buffer = _PROTOCOL.NulDelimitedMessageBuffer()
        self.assertIsNone(buffer.append(b'{"Sta'))
        self.assertEqual(buffer.append(b'tus":0}\x00'), '{"Status":0}')
        self.assertIsNone(buffer.append(b"next"))
        buffer.clear()
        self.assertIsNone(buffer.append(b""))

    def test_nul_delimited_buffer_rejects_oversized_response(self):
        buffer = _PROTOCOL.NulDelimitedMessageBuffer(max_size=4)
        with self.assertRaises(_PROTOCOL.MessageTooLargeError):
            buffer.append(b"12345")
        with self.assertRaises(_PROTOCOL.MessageTooLargeError):
            buffer.append(b"12345\x00ignored")
        self.assertEqual(buffer.append(b"ok\x00"), "ok")


LISBON = timezone(timedelta(hours=1), "WEST")


class ControllerTimeTests(unittest.TestCase):
    def test_controller_time_is_local_wall_clock_as_epoch(self):
        local = datetime(2026, 10, 25, 13, 33, 28, tzinfo=LISBON)
        self.assertEqual(_PROTOCOL.to_controller_time(local), 1792935208)
        decoded = _PROTOCOL.from_controller_time(1792935208, LISBON)
        self.assertEqual(decoded.replace(tzinfo=None), local.replace(tzinfo=None))
        self.assertEqual(decoded.tzinfo, LISBON)

    def test_from_controller_time_rejects_unset_values(self):
        for value in (0, -1, None, True, "1792935208"):
            self.assertIsNone(_PROTOCOL.from_controller_time(value, LISBON))

    def test_rain_delay_ends_at_local_midnight_after_n_days(self):
        now = datetime(2026, 10, 25, 13, 0, tzinfo=LISBON)
        until = _PROTOCOL.rain_delay_end(now, 2)
        self.assertEqual(
            datetime.fromtimestamp(until, tz=timezone.utc).replace(tzinfo=None),
            datetime(2026, 10, 27, 0, 0),
        )
        with self.assertRaises(ValueError):
            _PROTOCOL.rain_delay_end(now, 0)

    def test_rain_delay_days_remaining_rounds_up_and_ignores_past(self):
        now = datetime(2026, 10, 25, 13, 0, tzinfo=LISBON)
        controller_now = _PROTOCOL.to_controller_time(now)
        for days in (1, 2, 7):
            until = _PROTOCOL.rain_delay_end(now, days)
            self.assertEqual(
                _PROTOCOL.rain_delay_days_remaining(until, controller_now), days
            )
        # Value read from hardware: a delay that ended on 2026-10-08.
        self.assertEqual(
            _PROTOCOL.rain_delay_days_remaining(1791417600, controller_now), 0
        )
        self.assertEqual(_PROTOCOL.rain_delay_days_remaining(0, controller_now), 0)
        self.assertEqual(_PROTOCOL.rain_delay_days_remaining(None, controller_now), 0)

    def test_next_water_time_is_next_occurrence_of_minutes_after_midnight(self):
        morning = datetime(2026, 10, 25, 5, 0, tzinfo=LISBON)
        self.assertEqual(
            _PROTOCOL.next_water_time(360, morning),
            datetime(2026, 10, 25, 6, 0, tzinfo=LISBON),
        )
        afternoon = datetime(2026, 10, 25, 13, 0, tzinfo=LISBON)
        self.assertEqual(
            _PROTOCOL.next_water_time(360, afternoon),
            datetime(2026, 10, 26, 6, 0, tzinfo=LISBON),
        )
        for value in (-1, 1440, 65535, None, False):
            self.assertIsNone(_PROTOCOL.next_water_time(value, afternoon))


if __name__ == "__main__":
    unittest.main()
