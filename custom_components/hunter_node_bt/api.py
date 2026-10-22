"""BLE client for the Hunter NODE-BT controller.

Protocol recovered from the official app (com.hunter.nodev2). See PROTOCOL.md.
Transport is the Nordic UART Service; commands are JSON written in 20-byte chunks
and responses are NUL-terminated JSON via notifications. A PIN challenge-response
login (XOR-obfuscated 6-byte packets) is required first.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection

from .const import (
    ACTIVE_STATES,
    MSG_RX,
    MSG_TX,
    NUS_SERVICE,
    PIN_CHAR,
)

_LOGGER = logging.getLogger(__name__)

CHUNK = 20
COMMAND_TIMEOUT = 20

# PinMessageType
_LOGIN_REQUEST = 1
_LOGIN_CHALLENGE_REQUEST = 2
_LOGIN_CHALLENGE_RESPONSE = 3
_LOGIN_CHALLENGE_RESULT = 4


class HunterAuthError(Exception):
    """Raised when the PIN is rejected."""


class HunterConnectionError(Exception):
    """Raised on connection/communication failure."""


def _xor_ac(buf: bytes) -> bytes:
    # MessageEncryptDecrypt: XOR 0xAC, but leave 0x00 bytes unchanged (app quirk).
    return bytes((b ^ 0xAC) if b != 0 else 0 for b in buf)


def _pin_info(packet_type: int, result: int = 0, random_number: int = 0, pin: int = 0) -> bytes:
    # DevicePinInfo: <B B H H> = packetType, result, randomNumber, pin
    return struct.pack("<BBHH", packet_type, result, random_number & 0xFFFF, pin & 0xFFFF)


def sanitize_hunter_json(text: str) -> str:
    """Fix common firmware JSON corruption quirks identified in decompiled app."""
    # Fix corrupted Cycle/Soak fields
    if '"Cycl"Soak":0' in text:
        text = text.replace('"Cycl"Soak":0', '"Cycle":0,"Soak":0')
    # Fix truncated SeasonAdjustByMonthEnabl
    if '"SeasonAdjustByMonthEnabl"' in text:
        text = text.replace('"SeasonAdjustByMonthEnabl"', '"SeasonAdjustByMonthEnable"')
    # Fix corrupted Station State / Remaining
    if '"St"Remaining":0' in text:
        text = text.replace('"St"Remaining":0', '"State":0,"Remaining":0')
    return text


class HunterNodeBTClient:
    """Manages a connection to one controller."""

    def __init__(self, device: BLEDevice, pin: int, name: str | None = None) -> None:
        self._device = device
        self._pin = int(pin)
        self._name = name or device.address
        self._client: BleakClient | None = None
        self._lock = asyncio.Lock()
        self._pin_q: asyncio.Queue[tuple[int, int, int, int]] = asyncio.Queue()
        self._msg_buf = bytearray()
        self._msg_future: asyncio.Future[str] | None = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    # -- notification handlers ----------------------------------------------
    def _on_pin(self, _char, data: bytearray) -> None:
        raw = _xor_ac(bytes(data))
        if len(raw) >= 6:
            self._pin_q.put_nowait(struct.unpack("<BBHH", raw[:6]))

    def _on_msg(self, _char, data: bytearray) -> None:
        self._msg_buf.extend(data)
        if 0x00 in self._msg_buf:
            text = bytes(self._msg_buf).split(b"\x00", 1)[0].decode("utf-8", "replace")
            self._msg_buf.clear()
            if self._msg_future and not self._msg_future.done():
                self._msg_future.set_result(text)

    # -- lifecycle -----------------------------------------------------------
    async def ensure_connected(self) -> None:
        if self.is_connected:
            return
        try:
            self._client = await establish_connection(
                BleakClient, self._device, self._name
            )
            await self._client.start_notify(PIN_CHAR, self._on_pin)
            await self._client.start_notify(MSG_TX, self._on_msg)
            await self._login()
        except HunterAuthError:
            await self.disconnect()
            raise
        except Exception as err:  # noqa: BLE001
            await self.disconnect()
            raise HunterConnectionError(str(err)) from err

    async def _login(self) -> None:
        while not self._pin_q.empty():
            self._pin_q.get_nowait()
        await self._client.write_gatt_char(PIN_CHAR, _xor_ac(_pin_info(_LOGIN_REQUEST)), response=False)
        ptype, result, rnd, _ = await asyncio.wait_for(self._pin_q.get(), COMMAND_TIMEOUT)
        if ptype != _LOGIN_CHALLENGE_REQUEST or result != 0:
            raise HunterConnectionError(f"Login challenge failed (type={ptype} result={result})")
        resp = _pin_info(_LOGIN_CHALLENGE_RESPONSE, random_number=rnd, pin=self._pin ^ rnd)
        await self._client.write_gatt_char(PIN_CHAR, _xor_ac(resp), response=False)
        ptype, result, _, _ = await asyncio.wait_for(self._pin_q.get(), COMMAND_TIMEOUT)
        if ptype != _LOGIN_CHALLENGE_RESULT or result != 0:
            raise HunterAuthError(f"PIN rejected (result={result})")

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass

    # -- commands ------------------------------------------------------------
    async def _send(self, command: dict, expect_reply: bool = True) -> str | None:
        async with self._lock:
            await self.ensure_connected()
            payload = json.dumps(command, separators=(",", ":")).encode("utf-8")
            loop = asyncio.get_running_loop()
            if expect_reply:
                self._msg_future = loop.create_future()
                self._msg_buf.clear()
            for i in range(0, len(payload), CHUNK):
                await self._client.write_gatt_char(MSG_RX, payload[i : i + CHUNK], response=True)
            if expect_reply:
                raw_reply = await asyncio.wait_for(self._msg_future, COMMAND_TIMEOUT)
                return sanitize_hunter_json(raw_reply)
            return None

    async def read_all(self) -> dict:
        reply = await self._send({"Read": "All"})
        if not reply:
            raise HunterConnectionError("Empty reply from Read All")
        return json.loads(reply)

    async def read_state(self) -> dict:
        reply = await self._send({"Read": "Section_State"})
        if not reply:
            raise HunterConnectionError("Empty reply from Read Section_State")
        return json.loads(reply)

    async def read_last_run(self) -> dict:
        reply = await self._send({"Read": "LastRun"})
        if not reply:
            raise HunterConnectionError("Empty reply from Read LastRun")
        return json.loads(reply)

    async def start_station(self, station: int, seconds: int) -> None:
        reply = await self._send({"Manual": {"StationNumber": station, "RunTime": seconds}})
        if reply:
            data = json.loads(reply)
            if data.get("Status", 0) != 0:
                raise HunterConnectionError(f"Failed to start station {station}: status={data.get('Status')}")

    async def run_program(self, letter: str, seconds: int | None = None) -> None:
        cmd: dict = {"Manual": {"ProgramLetter": letter}}
        if seconds is not None:
            cmd["Manual"]["RunTime"] = seconds
        reply = await self._send(cmd)
        if reply:
            data = json.loads(reply)
            if data.get("Status", 0) != 0:
                raise HunterConnectionError(f"Failed to run program {letter}: status={data.get('Status')}")

    async def stop_all(self) -> None:
        reply = await self._send({"Manual": {"StopAll": True}})
        if reply:
            data = json.loads(reply)
            if data.get("Status", 0) != 0:
                raise HunterConnectionError(f"Failed to stop all: status={data.get('Status')}")


def station_is_active(state_value: int | None) -> bool:
    """True if a StationState.State means water is flowing."""
    return state_value in ACTIVE_STATES
