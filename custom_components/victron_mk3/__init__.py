"""The victron_mk3 integration."""

import asyncio
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, CONF_PORT
from homeassistant.core import HomeAssistant
import logging
from victron_mk3 import ACFrame, Fault, Frame, Handler, VictronMK3, logger

from .const import DOMAIN

PLATFORMS: list[Platform] = []
KEY_CONTROLLER = "controller"
DELAY_BETWEEN_REQUESTS = 2  # seconds


class Controller(Handler):
    def __init__(self, port: str) -> None:
        self._mk3: VictronMK3 = VictronMK3(port)
        self._monitor_task: asyncio.Task = None
        self._ac_num_phases = 1
        self._faulted: bool = False

    async def start(self) -> None:
        await self._mk3.start(self)
        self._monitor_task = asyncio.create_task(self._monitor())

    async def stop(self) -> None:
        await self._mk3.stop()
        self._monitor_task.cancel()
        try:
            await self._monitor_task
        except asyncio.CancelledError:
            pass

    def on_frame(self, frame: Frame) -> None:
        frame.log(logger, logging.INFO)
        if isinstance(frame, ACFrame) and frame.ac_num_phases != 0:
            self._ac_num_phases = frame.ac_num_phases

    def on_idle(self) -> None:
        logger.info("Idle")

    def on_fault(self, fault: Fault) -> None:
        logger.error(f"Fault: {fault}")
        self._faulted = True

    async def _monitor(self):
        # Poll until faulted or cancelled
        while not self._faulted:
            self._mk3.send_led_request()
            await asyncio.sleep(DELAY_BETWEEN_REQUESTS)
            self._mk3.send_dc_request()
            await asyncio.sleep(DELAY_BETWEEN_REQUESTS)
            for phase in range(1, self._ac_num_phases + 1):
                self._mk3.send_ac_request(phase)
                await asyncio.sleep(DELAY_BETWEEN_REQUESTS)
            self._mk3.send_config_request()
            await asyncio.sleep(DELAY_BETWEEN_REQUESTS)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    port = entry.data[CONF_PORT]
    if port is None:
        return False

    controller = Controller(port)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {}
    hass.data[DOMAIN][entry.entry_id][KEY_CONTROLLER] = controller

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await controller.start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        controller = hass.data[DOMAIN][entry.entry_id][KEY_CONTROLLER]
        await controller.stop()
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
