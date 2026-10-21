"""Unit test for Hunter NODE-BT protocol math and parsing."""

import json
from hunter_node_bt_client import _xor_ac, _pin_info, sanitize_hunter_json

def test_xor_ac():
    # Plaintext 0 stays 0
    assert _xor_ac(bytes([0x00])) == bytes([0x00])
    # Plaintext byte XORed with 0xAC
    assert _xor_ac(bytes([0x01])) == bytes([0xAD])
    assert _xor_ac(bytes([0xAD])) == bytes([0x01])

def test_pin_info():
    packet = _pin_info(1, 0, 0, 0)
    assert len(packet) == 6
    # Obfuscated packetType=1
    obf = _xor_ac(packet)
    assert obf == bytes([0xAD, 0x00, 0x00, 0x00, 0x00, 0x00])

def test_sanitize_json():
    corrupted = '{"Station_1":{"Name":"Front","Cycl"Soak":0},"State":{"St"Remaining":0},"Controller":{"SeasonAdjustByMonthEnabl":true}}'
    clean = sanitize_hunter_json(corrupted)
    data = json.loads(clean)
    assert data["Station_1"]["Cycle"] == 0
    assert data["Station_1"]["Soak"] == 0
    assert data["State"]["State"] == 0
    assert data["State"]["Remaining"] == 0
    assert data["Controller"]["SeasonAdjustByMonthEnable"] is True

if __name__ == "__main__":
    test_xor_ac()
    test_pin_info()
    test_sanitize_json()
    print("All Hunter NODE-BT protocol tests passed successfully!")
