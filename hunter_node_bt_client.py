"""
Hunter NODE-BT reference BLE client (reverse-engineered from com.hunter.nodev2 v6.0.611246).

Transport: Nordic UART Service. Commands are JSON, UTF-8, written in 20-byte chunks
to the RX characteristic; responses are JSON terminated by a NUL (0x00) byte via
notifications on the TX characteristic. A PIN challenge-response login (XOR-obfuscated
6-byte packets on a separate service) is required before commands are accepted.

This is a minimal, dependency-light reference for building a Home Assistant / HACS
integration. Requires: pip install bleak

Verified against decompiled C# (NodeV2.Services.BleDeviceCommunication). Field layouts,
the 0xAC XOR (skip-zero) quirk, and the handshake order match the app exactly.
"""

import asyncio
import json
import struct

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    BleakClient = None
    BleakScanner = None

# --- GATT UUIDs -------------------------------------------------------------
NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
MSG_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # write (app -> device)
MSG_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # notify (device -> app)

PIN_SERVICE = "0ed3e3d3-8cd8-4f29-8fec-a7d3a2c5443e"
PIN_CHAR = "4c9dbe52-3566-4dfc-a299-4ea1353970e2"  # write + notify

CHUNK = 20  # bytes per write (as the app does, regardless of negotiated MTU)

# PinMessageType
LOGIN_REQUEST = 1
LOGIN_CHALLENGE_REQUEST = 2
LOGIN_CHALLENGE_RESPONSE = 3
LOGIN_CHALLENGE_RESULT = 4


def _xor_ac(buf: bytes) -> bytes:
    # MessageEncryptDecrypt: XOR 0xAC, but leave bytes that are 0x00 unchanged.
    return bytes((b ^ 0xAC) if b != 0 else 0 for b in buf)


def _pin_info(packet_type: int, result: int = 0, random_number: int = 0, pin: int = 0) -> bytes:
    # DevicePinInfo, 6 bytes little-endian: packetType, result, u16 randomNumber, u16 pin
    return struct.pack("<BBHH", packet_type, result, random_number & 0xFFFF, pin & 0xFFFF)


def _parse_pin_info(buf: bytes):
    packet_type, result, random_number, pin = struct.unpack("<BBHH", buf[:6])
    return packet_type, result, random_number, pin


def sanitize_hunter_json(text: str) -> str:
    """Fix common firmware JSON corruption quirks identified in decompiled app."""
    if '"Cycl"Soak":0' in text:
        text = text.replace('"Cycl"Soak":0', '"Cycle":0,"Soak":0')
    if '"SeasonAdjustByMonthEnabl"' in text:
        text = text.replace('"SeasonAdjustByMonthEnabl"', '"SeasonAdjustByMonthEnable"')
    if '"St"Remaining":0' in text:
        text = text.replace('"St"Remaining":0', '"State":0,"Remaining":0')
    return text


class HunterNodeBT:
    def __init__(self, address: str, pin: int = 0):
        self.address = address
        self.pin = int(pin)
        self.client: BleakClient | None = None
        self._pin_q: asyncio.Queue = asyncio.Queue()
        self._msg_buf = bytearray()
        self._msg_future: asyncio.Future | None = None

    # -- notifications -------------------------------------------------------
    def _on_pin(self, _char, data: bytearray):
        self._pin_q.put_nowait(_parse_pin_info(_xor_ac(bytes(data))))

    def _on_msg(self, _char, data: bytearray):
        self._msg_buf.extend(data)
        if 0x00 in self._msg_buf:
            text = bytes(self._msg_buf).split(b"\x00", 1)[0].decode("utf-8", "replace")
            self._msg_buf.clear()
            if self._msg_future and not self._msg_future.done():
                self._msg_future.set_result(text)

    async def _next_pin(self, timeout=15):
        return await asyncio.wait_for(self._pin_q.get(), timeout)

    # -- connection + login --------------------------------------------------
    async def connect(self):
        self.client = BleakClient(self.address)
        await self.client.connect()
        await self.client.start_notify(PIN_CHAR, self._on_pin)
        await self.client.start_notify(MSG_TX, self._on_msg)
        await self._login()

    async def _login(self):
        # 1) send LoginRequest (PIN characteristic requires write-without-response)
        await self.client.write_gatt_char(PIN_CHAR, _xor_ac(_pin_info(LOGIN_REQUEST)), response=False)
        # 2) receive challenge (random number)
        ptype, result, rnd, _ = await self._next_pin()
        if ptype != LOGIN_CHALLENGE_REQUEST or result != 0:
            raise RuntimeError(f"login challenge failed: type={ptype} result={result}")
        # 3) respond with pin XOR random
        resp = _pin_info(LOGIN_CHALLENGE_RESPONSE, random_number=rnd, pin=self.pin ^ rnd)
        await self.client.write_gatt_char(PIN_CHAR, _xor_ac(resp), response=False)
        # 4) result
        ptype, result, _, _ = await self._next_pin()
        if ptype != LOGIN_CHALLENGE_RESULT or result != 0:
            raise RuntimeError(f"PIN rejected (result={result})")

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()
            self.client = None

    # -- commands ------------------------------------------------------------
    async def send_command(self, cmd: dict, expect_reply: bool = True) -> str | None:
        payload = json.dumps(cmd, separators=(",", ":")).encode("utf-8")
        if expect_reply:
            loop = asyncio.get_running_loop()
            self._msg_future = loop.create_future()
            self._msg_buf.clear()
        for i in range(0, len(payload), CHUNK):
            # Nordic UART RX characteristic requires write with response
            await self.client.write_gatt_char(MSG_RX, payload[i : i + CHUNK], response=True)
        if expect_reply:
            raw = await asyncio.wait_for(self._msg_future, 20)
            return sanitize_hunter_json(raw)
        return None

    async def read_all(self) -> dict:
        reply = await self.send_command({"Read": "All"})
        return json.loads(reply) if reply else {}

    async def read_state(self) -> dict:
        reply = await self.send_command({"Read": "Section_State"})
        return json.loads(reply) if reply else {}

    async def start_station(self, station: int, seconds: int) -> str | None:
        return await self.send_command({"Manual": {"StationNumber": station, "RunTime": seconds}})

    async def stop_all(self) -> str | None:
        return await self.send_command({"Manual": {"StopAll": True}})

    async def run_program(self, program: str) -> str | None:
        return await self.send_command({"Manual": {"ProgramLetter": program.upper()}})


# --- Quick CLI runner -------------------------------------------------------
async def main():
    import argparse
    import sys

    if BleakClient is None or BleakScanner is None:
        print("Error: 'bleak' library is not installed.")
        print("Please install bleak with: pip install bleak")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Hunter NODE-BT BLE CLI Client")
    parser.add_argument("--address", "-a", default=None, help="Bluetooth address/UUID (auto-discovered if omitted)")
    parser.add_argument("--pin", "-p", type=int, default=0, help="Security PIN (default: 0)")

    subparsers = parser.add_subparsers(dest="cmd", help="Action to perform")
    subparsers.add_parser("read-all", help="Read complete controller configuration and state (default)")
    subparsers.add_parser("read-state", help="Read current watering state and station progress")

    start_p = subparsers.add_parser("start", help="Start manual watering on a station")
    start_p.add_argument("station", type=int, help="Station number (1-4)")
    start_p.add_argument("seconds", type=int, help="Run duration in seconds")

    subparsers.add_parser("stop", help="Stop all active watering")

    prog_p = subparsers.add_parser("run-program", help="Run program cycle (A, B, C, or T)")
    prog_p.add_argument("letter", choices=["A", "B", "C", "T", "a", "b", "c", "t"], help="Program letter")

    raw_p = subparsers.add_parser("raw", help="Send arbitrary raw JSON command to the controller")
    raw_p.add_argument("json_str", help="JSON string, e.g. '{\"Manual\":{\"StopAll\":true}}'")

    args, unknown = parser.parse_known_args()

    address = args.address
    pin = args.pin
    action = args.cmd or "read-all"

    # Backward compatibility: handle positional address and pin (e.g. client.py <MAC> [PIN])
    if not address and unknown:
        candidate = unknown[0]
        if ":" in candidate or "-" in candidate:
            address = candidate
            if len(unknown) > 1 and unknown[1].isdigit():
                pin = int(unknown[1])

    if not address:
        print(f"Scanning for NODE-BT controllers (filtering on NUS {NUS_SERVICE} or name)...")
        discovered = await BleakScanner.discover(timeout=10.0, return_adv=True)
        hunter_matches = []
        other_devices = []

        for d, adv in discovered.values():
            name = d.name or adv.local_name or "Unknown"
            uuids = [str(u).lower() for u in adv.service_uuids]
            if NUS_SERVICE.lower() in uuids or "hunter" in name.lower() or "node" in name.lower():
                hunter_matches.append(d)
                print(f"  [+] Hunter candidate found: {name} ({d.address}) | RSSI: {adv.rssi} dBm")
            else:
                other_devices.append((name, d.address))

        if not hunter_matches:
            print("\nNo Hunter NODE-BT controllers identified automatically.")
            if other_devices:
                print(f"Found {len(other_devices)} other Bluetooth device(s) nearby:")
                for name, addr in other_devices[:10]:
                    print(f"   - {name} ({addr})")
            print("\nTip: Make sure the controller is powered on, nearby, and disconnected from the phone app.")
            print("You can also run directly with the MAC/UUID: python hunter_node_bt_client.py -a <ADDRESS> [-p PIN]")
            return

        address = hunter_matches[0].address
        print(f"\nProceeding to connect to: {address}")

    client = HunterNodeBT(address, pin)
    try:
        print(f"Connecting to {address}...")
        await client.connect()
        print(f"Authenticated successfully with PIN {pin}!\n")

        if action == "read-all":
            print("Reading full state (ReadAll)...")
            res = await client.read_all()
            print(json.dumps(res, indent=2))
        elif action == "read-state":
            print("Reading running state (Section_State)...")
            res = await client.read_state()
            print(json.dumps(res, indent=2))
        elif action == "start":
            print(f"Starting station {args.station} for {args.seconds} seconds...")
            reply = await client.start_station(args.station, args.seconds)
            print(f"Controller reply: {reply}")
        elif action == "stop":
            print("Stopping all active watering...")
            reply = await client.stop_all()
            print(f"Controller reply: {reply}")
        elif action == "run-program":
            letter = args.letter.upper()
            print(f"Starting program {letter}...")
            reply = await client.run_program(letter)
            print(f"Controller reply: {reply}")
        elif action == "raw":
            cmd = json.loads(args.json_str)
            print(f"Sending raw command: {cmd}")
            reply = await client.send_command(cmd)
            print(f"Controller reply: {reply}")

    except Exception as err:
        print(f"\nError communicating with controller: {err}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
