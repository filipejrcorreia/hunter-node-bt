"""Config flow for Hunter NODE-BT integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .api import HunterAuthError, HunterConnectionError, HunterNodeBTClient
from .const import (
    CONF_DEFAULT_RUN_TIME,
    CONF_PIN,
    DEFAULT_PIN,
    DEFAULT_RUN_TIME_MIN,
    DOMAIN,
    NUS_SERVICE,
)

_LOGGER = logging.getLogger(__name__)


class HunterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hunter NODE-BT."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_device: Any | None = None
        self._discovered_devices: dict[str, str] = {}
        self._address: str | None = None
        self._name: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._address = discovery_info.address
        self._name = discovery_info.name or f"Hunter NODE-BT ({discovery_info.address})"
        self._discovered_device = discovery_info.device

        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm pairing for a discovered device."""
        errors: dict[str, str] = {}

        if user_input is not None:
            pin = user_input.get(CONF_PIN, DEFAULT_PIN)
            default_run_time = user_input.get(CONF_DEFAULT_RUN_TIME, DEFAULT_RUN_TIME_MIN)

            device = self._discovered_device or bluetooth.async_ble_device_from_address(
                self.hass, self._address, connectable=True
            )
            if device is None:
                errors["base"] = "cannot_connect"
            else:
                client = HunterNodeBTClient(device, pin, self._name)
                try:
                    await client.ensure_connected()
                    await client.read_state()
                except HunterAuthError:
                    errors["base"] = "invalid_auth"
                except Exception:
                    errors["base"] = "cannot_connect"
                finally:
                    await client.disconnect()

            if not errors:
                return self.async_create_entry(
                    title=self._name or self._address,
                    data={
                        "address": self._address,
                        CONF_PIN: pin,
                    },
                    options={
                        CONF_DEFAULT_RUN_TIME: default_run_time,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_PIN, default=DEFAULT_PIN): vol.Coerce(int),
                vol.Required(CONF_DEFAULT_RUN_TIME, default=DEFAULT_RUN_TIME_MIN): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=240)
                ),
            }
        )

        return self.async_show_form(
            step_id="confirm",
            data_schema=schema,
            description_placeholders={"name": self._name or self._address},
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual user initiation."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input["address"]
            pin = user_input.get(CONF_PIN, DEFAULT_PIN)
            default_run_time = user_input.get(CONF_DEFAULT_RUN_TIME, DEFAULT_RUN_TIME_MIN)

            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()

            device = bluetooth.async_ble_device_from_address(
                self.hass, address, connectable=True
            )
            if device is None:
                errors["base"] = "cannot_connect"
            else:
                name = device.name or f"Hunter NODE-BT ({address})"
                client = HunterNodeBTClient(device, pin, name)
                try:
                    await client.ensure_connected()
                    await client.read_state()
                except HunterAuthError:
                    errors["base"] = "invalid_auth"
                except Exception:
                    errors["base"] = "cannot_connect"
                finally:
                    await client.disconnect()

                if not errors:
                    return self.async_create_entry(
                        title=name,
                        data={
                            "address": address,
                            CONF_PIN: pin,
                        },
                        options={
                            CONF_DEFAULT_RUN_TIME: default_run_time,
                        },
                    )

        current_addresses = self._async_current_ids()
        discovered_devices: dict[str, str] = {}
        for service_info in bluetooth.async_discovered_service_info(self.hass, connectable=True):
            if (
                NUS_SERVICE in service_info.advertisement.service_uuids
                and service_info.address not in current_addresses
            ):
                label = service_info.name or service_info.address
                discovered_devices[service_info.address] = f"{label} ({service_info.address})"

        if discovered_devices:
            schema = vol.Schema(
                {
                    vol.Required("address"): vol.In(discovered_devices),
                    vol.Required(CONF_PIN, default=DEFAULT_PIN): vol.Coerce(int),
                    vol.Required(CONF_DEFAULT_RUN_TIME, default=DEFAULT_RUN_TIME_MIN): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=240)
                    ),
                }
            )
        else:
            schema = vol.Schema(
                {
                    vol.Required("address"): str,
                    vol.Required(CONF_PIN, default=DEFAULT_PIN): vol.Coerce(int),
                    vol.Required(CONF_DEFAULT_RUN_TIME, default=DEFAULT_RUN_TIME_MIN): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=240)
                    ),
                }
            )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow handler."""
        return HunterOptionsFlowHandler(config_entry)


class HunterOptionsFlowHandler(OptionsFlow):
    """Handle options flow for Hunter NODE-BT."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        default_run_time = self.config_entry.options.get(
            CONF_DEFAULT_RUN_TIME, DEFAULT_RUN_TIME_MIN
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_DEFAULT_RUN_TIME, default=default_run_time): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=240)
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
