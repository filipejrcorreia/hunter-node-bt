"""Pure protocol helpers shared by the integration and standalone client."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
import math
import struct

CHUNK_SIZE = 20
MAX_RESPONSE_SIZE = 64 * 1024
PIN_MIN = 0
PIN_MAX = 0xFFFF
SECONDS_PER_DAY = 86400
MINUTES_PER_DAY = 1440


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


# The controller keeps wall-clock (local) time and stores it as if it were a
# UTC epoch: CurrentTime, ProgrammableDaysOff and LastRun.StartTime all use this
# "local epoch". Verified on hardware: CurrentTime read 13:33 "UTC" at 12:35 UTC
# (controller last synced while on WEST, UTC+1).


def to_controller_time(local: datetime) -> int:
    """Encode a local wall-clock datetime as a controller local-epoch timestamp."""
    return int(local.replace(tzinfo=timezone.utc).timestamp())


def from_controller_time(value: object, tz: tzinfo) -> datetime | None:
    """Decode a controller local-epoch timestamp into an aware datetime in tz."""
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    try:
        naive = datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        return None
    return naive.replace(tzinfo=tz)


def rain_delay_end(local_now: datetime, days: int) -> int:
    """Controller timestamp for local midnight `days` days after today.

    A one-day delay therefore skips the rest of today; watering resumes at the
    next midnight.
    """
    if days < 1:
        raise ValueError("Rain delay must be at least one day")
    midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return to_controller_time(midnight + timedelta(days=days))


def rain_delay_days_remaining(days_off: object, controller_now: int) -> int:
    """Whole days left on a ProgrammableDaysOff delay (0 when not active)."""
    if not isinstance(days_off, int) or isinstance(days_off, bool):
        return 0
    if days_off <= controller_now:
        return 0
    return math.ceil((days_off - controller_now) / SECONDS_PER_DAY)


def next_water_time(minutes: object, local_now: datetime) -> datetime | None:
    """Next occurrence of State.NextWaterTime (minutes after local midnight)."""
    if not isinstance(minutes, int) or isinstance(minutes, bool):
        return None
    if not 0 <= minutes < MINUTES_PER_DAY:
        return None
    midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    candidate = midnight + timedelta(minutes=minutes)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate
