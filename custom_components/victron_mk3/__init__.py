"""The victron_mk3 integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from enum import Enum
from homeassistant.components.device_automation.exceptions import DeviceNotFound
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    Platform,
    CONF_DEVICE_ID,
    CONF_MODE,
    CONF_MODEL,
    CONF_PORT,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
import logging
from typing import List
from victron_mk3 import (
    AC_PHASES_SUPPORTED,
    ACFrame,
    ConfigFrame,
    DCFrame,
    Fault,
    LEDFrame,
    Frame,
    Handler,
    SwitchState,
    SwitchRegister,
    VersionFrame,
    VictronMK3,
    logger,
)
import voluptuous as vol

from .const import (
    AC_PHASES_POLLED,
    CONF_CURRENT_LIMIT,
    CONF_SERIAL_NUMBER,
    DOMAIN,
    KEY_CONTEXT,
)

PLATFORMS: list[Platform] = ["number", "select", "sensor"]
UPDATE_INTERVAL = timedelta(seconds=10)
REQUEST_INTERVAL_SECONDS = 1


class Mode(Enum):
    OFF = 0
    ON = 1
    CHARGER_ONLY = 2
    INVERTER_ONLY = 3


MODE_TO_SWITCH_STATE = {
    Mode.OFF: SwitchState.OFF,
    Mode.ON: SwitchState.ON,
    Mode.CHARGER_ONLY: SwitchState.CHARGER_ONLY,
    Mode.INVERTER_ONLY: SwitchState.INVERTER_ONLY,
}


def enum_options(enum_class) -> List[str]:
    return [x.lower() for x in enum_class._member_names_]


def enum_value(e: Enum) -> str:
    return str(e) if e.name is None else e.name.lower()


def mode_from_value(value: str) -> Mode:
    return Mode[value.upper()]


SERVICE_NAME = "set_remote_panel_state"

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Required(CONF_MODE): vol.In(enum_options(Mode)),
        vol.Optional(CONF_CURRENT_LIMIT): vol.Coerce(float),
    }
)


class Data:
    def __init__(self) -> None:
        self.ac: List[ACFrame | None] = [None] * AC_PHASES_SUPPORTED
        self.config: ConfigFrame | None = None
        self.dc: DCFrame | None = None
        self.led: LEDFrame | None = None
        self.version: VersionFrame | None = None

    def front_panel_mode(self) -> Mode | None:
        if self.config is None:
            return None
        reg = self.config.switch_register
        if reg & SwitchRegister.FRONT_SWITCH_UP != 0:
            return Mode.ON
        if reg & SwitchRegister.FRONT_SWITCH_DOWN != 0:
            return Mode.CHARGER_ONLY
        return Mode.OFF

    def remote_panel_mode(self) -> Mode | None:
        if self.config is None:
            return None
        reg = self.config.switch_register
        if reg & SwitchRegister.DIRECT_REMOTE_SWITCH_CHARGE != 0:
            if reg & SwitchRegister.DIRECT_REMOTE_SWITCH_INVERT != 0:
                return Mode.ON
            else:
                return Mode.CHARGER_ONLY
        else:
            if reg & SwitchRegister.DIRECT_REMOTE_SWITCH_INVERT != 0:
                return Mode.INVERTER_ONLY
            else:
                return Mode.OFF

    def actual_mode(self) -> Mode | None:
        if self.config is None:
            return None
        reg = self.config.switch_register
        if reg & SwitchRegister.SWITCH_CHARGE != 0:
            if reg & SwitchRegister.SWITCH_INVERT != 0:
                return Mode.ON
            else:
                return Mode.CHARGER_ONLY
        else:
            if reg & SwitchRegister.SWITCH_INVERT != 0:
                return Mode.INVERTER_ONLY
            else:
                return Mode.OFF


class Controller(Handler):
    def __init__(self, port: str) -> None:
        self._mk3 = VictronMK3(port)
        self._data: Data | None = None
        self._fault: Fault | None = None

    async def start(self) -> None:
        await self._mk3.start(self)

    async def stop(self) -> None:
        await self._mk3.stop()

    def on_frame(self, frame: Frame) -> None:
        frame.log(logger, logging.DEBUG)

        if self._data is None:
            self._data = Data()

        if isinstance(frame, ACFrame):
            self._data.ac[frame.ac_phase - 1] = frame
        elif isinstance(frame, ConfigFrame):
            self._data.config = frame
        elif isinstance(frame, DCFrame):
            self._data.dc = frame
        elif isinstance(frame, LEDFrame):
            self._data.led = frame
        elif isinstance(frame, VersionFrame):
            self._data.version = frame

    def on_idle(self) -> None:
        logger.debug("Idle")
        self._data = None

    def on_fault(self, fault: Fault) -> None:
        if fault == Fault.EXCEPTION:
            logger.exception("Unhandled exception in handler")
        else:
            logger.error(f"Communication fault: {fault}")
        self._fault = fault

    async def update(self) -> Data:
        if self._fault is not None:
            raise UpdateFailed(f"Communication fault: {self._fault}")

        # Note: We don't need to ask for version frames because the interface sends them periodically
        self._mk3.send_led_request()
        await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
        self._mk3.send_dc_request()
        await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
        for phase in range(1, AC_PHASES_POLLED):
            # It might be nice to optimize the polling based on AC_Frame.ac_num_phases
            # but it seems to report an incorrect number of phases on at least some devices.
            self._mk3.send_ac_request(phase)
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
        self._mk3.send_config_request()
        await asyncio.sleep(REQUEST_INTERVAL_SECONDS)

        if self._data is None:
            raise UpdateFailed("No data available")
        return self._data

    async def set_remote_panel_state(
        self, mode: Mode, current_limit: float | None
    ) -> None:
        self._mk3.send_state_request(MODE_TO_SWITCH_STATE[mode], current_limit)
        await asyncio.sleep(REQUEST_INTERVAL_SECONDS)


class Context:
    def __init__(
        self,
        controller: Controller,
        coordinator: DataUpdateCoordinator[Data],
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        self.controller = controller
        self.coordinator = coordinator
        self.device_id = device_id
        self.device_info = device_info


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    port = entry.data[CONF_PORT]
    controller = Controller(port)

    coordinator = DataUpdateCoordinator[Data](
        hass,
        logger,
        name=DOMAIN,
        update_interval=UPDATE_INTERVAL,
        update_method=controller.update,
    )

    device = device_registry.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        name=entry.title,
        manufacturer="Victron Energy",
        model=entry.data.get(CONF_MODEL, None),
        serial_number=entry.data.get(CONF_SERIAL_NUMBER, None),
        identifiers={(DOMAIN, port)},
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        KEY_CONTEXT: Context(
            controller, coordinator, device.id, DeviceInfo(identifiers={(DOMAIN, port)})
        )
    }

    await controller.start()
    entry.async_on_unload(controller.stop)

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await _async_setup_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def _async_setup_services(hass: HomeAssistant) -> None:
    async def _handle_set_remote_panel_state(call: ServiceCall) -> None:
        device_id = call.data[CONF_DEVICE_ID]
        mode = mode_from_value(call.data[CONF_MODE])
        current_limit = call.data.get(CONF_CURRENT_LIMIT, None)
        await set_remote_panel_state(hass, device_id, mode, current_limit)

    hass.services.async_register(
        DOMAIN,
        SERVICE_NAME,
        _handle_set_remote_panel_state,
        schema=SERVICE_SCHEMA,
    )


async def set_remote_panel_state(
    hass: HomeAssistant, device_id: str, mode: Mode, current_limit: float | None
) -> None:
    device = device_registry.async_get(hass).async_get(device_id)
    if device is None:
        raise DeviceNotFound(f"Device ID {device_id} is not valid")

    for entry_id in device.config_entries:
        entry_data = hass.data[DOMAIN].get(entry_id, None)
        if entry_data is not None:
            context = entry_data[KEY_CONTEXT]
            await context.controller.set_remote_panel_state(mode, current_limit)
            await context.coordinator.async_request_refresh()
            return

    raise HomeAssistantError(f"Device ID {device_id} cannot handle this request")
