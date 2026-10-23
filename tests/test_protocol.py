"""Tests for the BLE protocol helpers shared by the integration and CLI."""

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


if __name__ == "__main__":
    unittest.main()
