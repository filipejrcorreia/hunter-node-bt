"""Valve platform for Hunter NODE-BT."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import station_is_active
from .const import DOMAIN, STATION_STATES
from .coordinator import HunterConfigEntry, HunterCoordinator

_LOGGER = logging.getLogger(__name__)


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
        }

    async def async_open_valve(self) -> None:
        """Open the valve (start station for configured default runtime)."""
        await self.coordinator.async_start_station(self.station_number)

    async def async_close_valve(self) -> None:
        """Close the valve (stop watering)."""
        await self.coordinator.async_stop_all()
