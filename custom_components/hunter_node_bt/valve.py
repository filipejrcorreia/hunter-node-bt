"""Valve platform for Hunter NODE-BT."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import station_is_active
from .const import DOMAIN, MAX_RUN_TIME_MIN, STATION_STATES
from .coordinator import HunterConfigEntry, HunterCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_START_WATERING = "start_watering"
ATTR_DURATION = "duration"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HunterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hunter NODE-BT valve entities."""
    coordinator = entry.runtime_data
    count = coordinator.station_count or 1

    entities = [
        HunterStationValve(coordinator, station_num)
        for station_num in range(1, count + 1)
    ]
    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_START_WATERING,
        {vol.Required(ATTR_DURATION): cv.positive_time_period},
        "async_start_watering",
    )


class HunterStationValve(CoordinatorEntity[HunterCoordinator], ValveEntity):
    """Representation of a Hunter NODE-BT station as a valve."""

    _attr_device_class = ValveDeviceClass.WATER
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    _attr_reports_position = False
    _attr_has_entity_name = True

    def __init__(self, coordinator: HunterCoordinator, station_number: int) -> None:
        """Initialize the station valve."""
        super().__init__(coordinator)
        self.station_number = station_number
        self._attr_unique_id = f"{coordinator.address}_station_{station_number}"

        station_cfg = coordinator.stations.get(station_number, {})
        configured_name = station_cfg.get("Name")
        if configured_name and configured_name.strip():
            self._attr_name = configured_name.strip()
        else:
            self._attr_name = f"Station {station_number}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information."""
        ctrl = self.coordinator.controller
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.address)},
            name=self.coordinator.entry.title or "Hunter NODE-BT",
            manufacturer="Hunter Industries",
            model=f"NODE-BT ({self.coordinator.station_count} Station)",
            sw_version=str(ctrl.get("Version", "")) if ctrl.get("Version") else None,
            hw_version=str(ctrl.get("BTVersion", "")) if ctrl.get("BTVersion") else None,
            serial_number=str(ctrl.get("SerialNumber")) if ctrl.get("SerialNumber") else None,
        )

    @property
    def _station_state(self) -> dict | None:
        """Return raw station state data from State section."""
        state = self.coordinator.data.get("State", {})
        st_key = f"Station_{self.station_number}"
        return state.get(st_key)

    @property
    def is_closed(self) -> bool:
        """Return true if valve is closed."""
        st_data = self._station_state
        if not st_data:
            return True
        st_state = st_data.get("State")
        return not station_is_active(st_state)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        st_data = self._station_state or {}
        st_state_int = st_data.get("State", 0)
        remaining = st_data.get("Remaining", 0)

        return {
            "station_number": self.station_number,
            "station_state": STATION_STATES.get(st_state_int, "unknown"),
            "remaining_seconds": remaining,
            "run_time_minutes": self.coordinator.station_run_time_s(self.station_number) // 60,
        }

    async def async_open_valve(self) -> None:
        """Open the valve for the station's Run Time."""
        await self.coordinator.async_start_station(self.station_number)

    async def async_close_valve(self) -> None:
        """Close the valve (stop watering)."""
        await self.coordinator.async_stop_all()

    async def async_start_watering(self, duration: timedelta) -> None:
        """Water this station for a specific duration."""
        seconds = int(duration.total_seconds())
        if not 1 <= seconds <= MAX_RUN_TIME_MIN * 60:
            raise ServiceValidationError(
                f"Duration must be between 1 second and {MAX_RUN_TIME_MIN} minutes"
            )
        await self.coordinator.async_start_station(self.station_number, seconds)
