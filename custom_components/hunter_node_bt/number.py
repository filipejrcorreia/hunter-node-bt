"""Number platform for Hunter NODE-BT."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MAX_RAIN_DELAY_DAYS
from .coordinator import HunterConfigEntry, HunterCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HunterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hunter NODE-BT number entities."""
    coordinator = entry.runtime_data
    async_add_entities([HunterRainDelayNumber(coordinator)])


class HunterRainDelayNumber(CoordinatorEntity[HunterCoordinator], NumberEntity):
    """Rain delay in days: setting N suspends scheduled watering, 0 cancels it."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:weather-pouring"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = MAX_RAIN_DELAY_DAYS
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.DAYS

    def __init__(self, coordinator: HunterCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_rain_delay_days"
        self._attr_name = "Rain Delay"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry info."""
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
    def native_value(self) -> int:
        """Return days left on the rain delay."""
        return self.coordinator.rain_delay_days

    async def async_set_native_value(self, value: float) -> None:
        """Start (or cancel, with 0) a rain delay of the given number of days."""
        await self.coordinator.async_set_rain_delay(int(value))
