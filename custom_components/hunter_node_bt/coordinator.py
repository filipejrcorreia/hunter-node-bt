"""DataUpdateCoordinator for Hunter NODE-BT."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HunterAuthError, HunterConnectionError, HunterNodeBTClient
from .const import (
    CONF_DEFAULT_RUN_TIME,
    CONF_PIN,
    DEFAULT_PIN,
    DEFAULT_RUN_TIME_MIN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

type HunterConfigEntry = ConfigEntry[HunterCoordinator]


class HunterCoordinator(DataUpdateCoordinator[dict]):
    """Polls controller state over BLE and caches the static station layout."""

    def __init__(self, hass: HomeAssistant, entry: HunterConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.entry = entry
        self.address: str = entry.unique_id or entry.data["address"]
        self._pin = int(entry.data.get(CONF_PIN, DEFAULT_PIN))
        self._client: HunterNodeBTClient | None = None
        self.station_count: int = 0
        self.controller: dict = {}
        self.stations: dict[int, dict] = {}
        self.programs: dict[str, dict] = {}
        self._full_data: dict = {}

    @property
    def default_run_time_s(self) -> int:
        minutes = self.entry.options.get(CONF_DEFAULT_RUN_TIME, DEFAULT_RUN_TIME_MIN)
        return int(minutes) * 60

    def _get_client(self) -> HunterNodeBTClient:
        device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        if device is None:
            raise UpdateFailed(f"Device {self.address} not seen by any Bluetooth adapter")
        if self._client is None or self._client._device != device:
            self._client = HunterNodeBTClient(device, self._pin, self.entry.title)
        return self._client

    async def _async_update_data(self) -> dict:
        client = self._get_client()
        try:
            if not self.station_count:
                full = await client.read_all()
                self._full_data = full
                self.controller = full.get("Controller") or {}
                self.station_count = int(self.controller.get("StationCount") or 0)

                for i in range(1, 5):
                    st_key = f"Station_{i}"
                    if st_key in full:
                        self.stations[i] = full[st_key]

                for p_letter in ("A", "B", "C", "T"):
                    p_key = f"Program_{p_letter}"
                    if p_key in full:
                        self.programs[p_letter] = full[p_key]

                return full

            state = await client.read_state()
            self._full_data.update(state)
            return self._full_data

        except HunterAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except HunterConnectionError as err:
            raise UpdateFailed(str(err)) from err

    async def async_start_station(self, station: int, run_time_s: int | None = None) -> None:
        seconds = run_time_s if run_time_s is not None else self.default_run_time_s
        await self._get_client().start_station(station, seconds)
        await self.async_request_refresh()

    async def async_run_program(self, letter: str, run_time_s: int | None = None) -> None:
        await self._get_client().run_program(letter, run_time_s)
        await self.async_request_refresh()

    async def async_stop_all(self) -> None:
        await self._get_client().stop_all()
        await self.async_request_refresh()

    async def async_shutdown_client(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None
