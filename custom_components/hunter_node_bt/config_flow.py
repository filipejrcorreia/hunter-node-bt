"""Config flow for Hunter NODE-BT integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .api import HunterAuthError, HunterConnectionError, HunterNodeBTClient
from .const import (
    CONF_DEFAULT_RUN_TIME,
    CONF_PIN,
    CONF_SCAN_INTERVAL,
    DEFAULT_PIN,
    DEFAULT_RUN_TIME_MIN,
    DEFAULT_SCAN_INTERVAL_MIN,
    DOMAIN,
    NUS_SERVICE,
)

_LOGGER = logging.getLogger(__name__)

PIN_SCHEMA = vol.All(
    vol.Coerce(int),
    vol.Range(min=0, max=65535),
)

# How long to scan actively before listing controllers. The NODE-BT puts its
# service UUID (and usually its name) in the scan response, which adapters and
# proxies only receive while scanning actively.
ACTIVE_SCAN_SECONDS = 10

_MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")


def normalize_address(value: str) -> str | None:
    """Return the address the way Home Assistant's Bluetooth stores it, or None.

    Accepts lower case, dashes, spaces or no separators (``dd-ca-60-d4-e7-68``,
    ``ddca60d4e768``). Home Assistant keys devices by the upper-case,
    colon-separated MAC, so anything else is never found.
    """
    raw = re.sub(r"[^0-9A-Fa-f]", "", value or "").upper()
    if len(raw) != 12:
        return None
    address = ":".join(raw[i : i + 2] for i in range(0, 12, 2))
    return address if _MAC_RE.match(address) else None


def _label(service_info: BluetoothServiceInfoBleak) -> str:
    name = service_info.name
    if not name or normalize_address(name) == service_info.address:
        name = "Unnamed device"
    return f"{name} ({service_info.address}, {service_info.rssi} dBm)"


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
        await self.async_set_unique_id(discovery_info.address.upper())
        self._abort_if_unique_id_configured()

        self._address = discovery_info.address.upper()
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
                vol.Required(CONF_PIN, default=DEFAULT_PIN): PIN_SCHEMA,
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

        if user_input is None:
            await self._async_active_scan()
        else:
            address = normalize_address(user_input["address"]) or ""
            pin = user_input.get(CONF_PIN, DEFAULT_PIN)
            default_run_time = user_input.get(CONF_DEFAULT_RUN_TIME, DEFAULT_RUN_TIME_MIN)

            device = None
            if not address:
                errors["address"] = "invalid_address"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                device = bluetooth.async_ble_device_from_address(
                    self.hass, address, connectable=True
                )
                if device is None:
                    errors["base"] = "not_found"
            if not errors:
                assert device is not None
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

        options = self._address_options()
        schema = vol.Schema(
            {
                # A list to pick from, but a typed address is accepted too, since
                # a controller that only shows up in scan responses may not be
                # listed by name.
                vol.Required("address"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_PIN, default=DEFAULT_PIN): PIN_SCHEMA,
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

    async def _async_active_scan(self) -> None:
        """Scan actively for a few seconds so scan responses come in.

        Since Home Assistant 2026.x adapters and ESPHome proxies default to the
        AUTO scanning mode, which is passive almost all the time. Passive
        scanning never receives scan responses, so a NODE-BT that advertises
        its service UUID there is neither discovered nor listed.
        """
        request = getattr(bluetooth, "async_request_active_scan", None)
        if request is None:  # older Home Assistant: scanners are active already
            return
        try:
            await request(self.hass, ACTIVE_SCAN_SECONDS)
        except Exception:  # noqa: BLE001 - listing what's known still helps
            _LOGGER.debug("Active scan request failed", exc_info=True)

    def _address_options(self) -> list[selector.SelectOptionDict]:
        """Controllers first (advertising the NUS UUID), then every other device heard."""
        current = self._async_current_ids()
        hunters: list[BluetoothServiceInfoBleak] = []
        others: list[BluetoothServiceInfoBleak] = []
        for info in bluetooth.async_discovered_service_info(self.hass, connectable=True):
            if info.address in current:
                continue
            uuids = {uuid.lower() for uuid in info.service_uuids}
            (hunters if NUS_SERVICE in uuids else others).append(info)
        hunters.sort(key=lambda info: info.rssi, reverse=True)
        others.sort(key=lambda info: info.rssi, reverse=True)
        return [
            selector.SelectOptionDict(value=info.address, label=_label(info))
            for info in (*hunters, *others)
        ]

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
        scan_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MIN
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_DEFAULT_RUN_TIME, default=default_run_time): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=240)
                ),
                vol.Required(CONF_SCAN_INTERVAL, default=scan_interval): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=120)
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
