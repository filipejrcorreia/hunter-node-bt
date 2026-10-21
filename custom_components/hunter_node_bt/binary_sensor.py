"""Binary sensor platform for Hunter NODE-BT."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Set up Hunter NODE-BT binary sensors."""
    coordinator = entry.runtime_data

    entities: list[BinarySensorEntity] = [
        HunterRainSensor(coordinator),
        HunterRainDelaySensor(coordinator),
    ]

    async_add_entities(entities)


class HunterBaseBinarySensor(CoordinatorEntity[HunterCoordinator], BinarySensorEntity):
    """Base class for Hunter binary sensors."""

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


class HunterRainSensor(HunterBaseBinarySensor):
    """Binary sensor for rain / Clik sensor detection."""

    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(self, coordinator: HunterCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_rain_sensor"
        self._attr_name = "Rain Sensor Active"

    @property
    def is_on(self) -> bool:
        """Return true if rain sensor is active."""
        sensor = self.coordinator.data.get("Sensor", {})
        state = self.coordinator.data.get("State", {})
        return bool(sensor.get("ClickSensorActive") or state.get("ClickSensorState"))


class HunterRainDelaySensor(HunterBaseBinarySensor):
    """Binary sensor indicating rain or clik delay is holding watering."""

    def __init__(self, coordinator: HunterCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_rain_delay"
        self._attr_name = "Rain Delay Active"

    @property
    def is_on(self) -> bool:
        """Return true if rain delay is active."""
        state = self.coordinator.data.get("State", {})
        # ControllerState 5 = RainDelay, 4 = RainOff
        return state.get("ControllerState") in (4, 5)
