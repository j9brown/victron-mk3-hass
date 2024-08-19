from __future__ import annotations

from homeassistant.components import usb
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_MODEL, CONF_NAME, CONF_PORT
from typing import Any
from victron_mk3 import ProbeResult, probe
import voluptuous as vol

from .const import CONF_SERIAL_NUMBER, DOMAIN

DEFAULT_ENTRY_NAME = "Victron MK3"


class MK3ConfigFlow(ConfigFlow, domain=DOMAIN):
    # The schema version of the entries that it creates
    # Home Assistant will call your migrate method if the version changes
    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: usb.UsbServiceInfo = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step when user initializes a integration."""
        errors = {}
        placeholders = {}
        if user_input is not None:
            name = user_input[CONF_NAME]
            port = user_input[CONF_PORT]
            self._async_abort_entries_match({CONF_PORT: port})
            probe_result = await probe(port)
            if probe_result == ProbeResult.OK:
                return self.async_create_entry(title=name, data={CONF_PORT: port})
            errors[CONF_PORT] = "cannot_connect"
            placeholders["error_detail"] = probe_result.name.lower()
        else:
            user_input = {}
            user_input[CONF_NAME] = DEFAULT_ENTRY_NAME
            user_input[CONF_PORT] = ""

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=user_input[CONF_NAME]): str,
                    vol.Required(CONF_PORT, default=user_input[CONF_PORT]): str,
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_usb(
        self, discovery_info: usb.UsbServiceInfo
    ) -> ConfigFlowResult:
        """Handle USB Discovery."""
        await self.async_set_unique_id(
            f"{discovery_info.vid}:{discovery_info.pid}_{discovery_info.serial_number}_{discovery_info.manufacturer}_{discovery_info.description}"
        )
        # check if this device is not already configured
        self._async_abort_entries_match({CONF_PORT: discovery_info.device})
        # check if we can make a valid connection
        probe_result = await probe(discovery_info.device)
        if probe_result != ProbeResult.OK:
            return self.async_abort(
                reason="cannot_connect",
                description_placeholders={"error_detail", probe_result.name.lower()},
            )
        # store the data for the config step
        self._discovery_info = discovery_info
        # call the config step
        self._set_confirm_only()
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle Discovery confirmation."""
        if user_input is not None:
            return self.async_create_entry(
                title=DEFAULT_ENTRY_NAME,
                data={
                    CONF_PORT: self._discovery_info.device,
                    CONF_MODEL: self._discovery_info.description,
                    CONF_SERIAL_NUMBER: self._discovery_info.serial_number,
                },
            )
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"model": self._discovery_info.description},
        )
