"""Pure protocol helpers shared by the integration and standalone client."""

from __future__ import annotations

import struct

CHUNK_SIZE = 20
MAX_RESPONSE_SIZE = 64 * 1024
PIN_MIN = 0
PIN_MAX = 0xFFFF


class MessageTooLargeError(ValueError):
    """Raised when a NUL-terminated response exceeds the configured limit."""


class NulDelimitedMessageBuffer:
    """Collect one NUL-delimited response from BLE notifications."""

    def __init__(self, max_size: int = MAX_RESPONSE_SIZE) -> None:
        if max_size < 1:
            raise ValueError("Maximum response size must be positive")
        self._max_size = max_size
        self._buffer = bytearray()

    def clear(self) -> None:
        """Discard any incomplete response."""
        self._buffer.clear()

    def append(self, data: bytes) -> str | None:
        """Append a notification and return a complete response when available."""
        terminator = data.find(0)
        response_size = len(self._buffer) + (
            terminator if terminator >= 0 else len(data)
        )
        if response_size > self._max_size:
            self.clear()
            raise MessageTooLargeError(
                f"Controller response exceeded {self._max_size} bytes"
            )

        self._buffer.extend(data[:terminator] if terminator >= 0 else data)
        if terminator < 0:
            return None

        message = bytes(self._buffer).decode("utf-8", "replace")
        self.clear()
        return message


def xor_ac(buf: bytes) -> bytes:
    """Apply the controller's skip-zero XOR-0xAC transform."""
    return bytes((byte ^ 0xAC) if byte != 0 else 0 for byte in buf)


def pin_info(
    packet_type: int, result: int = 0, random_number: int = 0, pin: int = 0
) -> bytes:
    """Pack a 6-byte DevicePinInfo packet."""
    return struct.pack(
        "<BBHH", packet_type, result, random_number & 0xFFFF, pin & 0xFFFF
    )


def parse_pin_info(buf: bytes) -> tuple[int, int, int, int]:
    """Unpack a 6-byte DevicePinInfo packet."""
    if len(buf) < 6:
        raise ValueError("PIN packet must contain at least 6 bytes")
    return struct.unpack("<BBHH", buf[:6])


def validate_pin(value: int | str) -> int:
    """Convert and validate a controller PIN as an unsigned 16-bit integer."""
    if isinstance(value, (bool, float)):
        raise ValueError("PIN must be an integer between 0 and 65535")
    try:
        pin = int(value)
    except (TypeError, ValueError) as err:
        raise ValueError("PIN must be an integer between 0 and 65535") from err
    if not PIN_MIN <= pin <= PIN_MAX:
        raise ValueError("PIN must be an integer between 0 and 65535")
    return pin


def chunk_payload(payload: bytes, chunk_size: int = CHUNK_SIZE) -> list[bytes]:
    """Split a payload into BLE write chunks."""
    if chunk_size < 1:
        raise ValueError("Chunk size must be positive")
    return [
        payload[offset : offset + chunk_size]
        for offset in range(0, len(payload), chunk_size)
    ]


def sanitize_hunter_json(text: str) -> str:
    """Repair known malformed JSON fragments emitted by controller firmware."""
    text = text.replace('"Cycl"Soak":0', '"Cycle":0,"Soak":0')
    text = text.replace(
        '"SeasonAdjustByMonthEnabl"', '"SeasonAdjustByMonthEnable"'
    )
    return text.replace('"St"Remaining":0', '"State":0,"Remaining":0')
