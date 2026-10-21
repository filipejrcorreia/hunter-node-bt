"""The Hunter NODE-BT integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import HunterConfigEntry, HunterCoordinator

PLATFORMS: list[Platform] = [
    Platform.VALVE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: HunterConfigEntry) -> bool:
    """Set up Hunter NODE-BT from a config entry."""
    coordinator = HunterCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HunterConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown_client()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: HunterConfigEntry) -> None:
    """Reload when options (e.g. default run time) change."""
    await hass.config_entries.async_reload(entry.entry_id)
