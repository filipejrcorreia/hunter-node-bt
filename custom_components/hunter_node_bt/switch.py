"""Switch platform for Hunter NODE-BT."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HunterConfigEntry, HunterCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HunterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hunter NODE-BT switch entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            HunterControllerSwitch(coordinator),
            HunterMonthlySeasonAdjustSwitch(coordinator),
        ]
    )


class HunterBaseSwitch(CoordinatorEntity[HunterCoordinator], SwitchEntity):
    """Base switch entity for Hunter NODE-BT."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HunterCoordinator) -> None:
        super().__init__(coordinator)

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


class HunterControllerSwitch(HunterBaseSwitch):
    """Controller on/off: off stops all scheduled watering (e.g. for winter)."""

    _attr_icon = "mdi:sprinkler-variant"

    def __init__(self, coordinator: HunterCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_controller_on"
        self._attr_name = "Controller"

    @property
    def is_on(self) -> bool | None:
        """Return true when the controller is on."""
        off = self.coordinator.controller.get("ControllerOff")
        return None if off is None else not off

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the controller on."""
        await self.coordinator.async_set_controller_off(False)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the controller off."""
        await self.coordinator.async_set_controller_off(True)


class HunterMonthlySeasonAdjustSwitch(HunterBaseSwitch):
    """Use the controller's month-by-month seasonal adjustment table."""

    _attr_icon = "mdi:calendar-month"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: HunterCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_season_adjust_by_month"
        self._attr_name = "Monthly Season Adjust"

    @property
    def is_on(self) -> bool | None:
        """Return true when the monthly table is in use."""
        return self.coordinator.controller.get("SeasonAdjustByMonthEnable")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the monthly table (January first)."""
        return {"by_month": self.coordinator.controller.get("SeasonAdjustByMonth")}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Use the monthly table."""
        await self.coordinator.async_set_season_adjust_by_month(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Use the global seasonal adjustment instead."""
        await self.coordinator.async_set_season_adjust_by_month(False)
