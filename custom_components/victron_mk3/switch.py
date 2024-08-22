from __future__ import annotations

from dataclasses import dataclass
from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import Context
from .const import (
    DOMAIN,
    KEY_CONTEXT,
)


class VictronMK3StandbySwitchEntity(RestoreEntity, SwitchEntity):
    _attr_has_entity_name = True

    entity_description = SwitchEntityDescription(
        key="remote_panel_standby",
        name="Remote Panel Standby",
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG,
    )

    def __init__(self, context: Context):
        self.context = context
        self._attr_device_info = context.device_info
        self._attr_unique_id = f"{context.device_id}-{VictronMK3StandbySwitchEntity.entity_description.key}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        self._attr_is_on = state.state == STATE_ON if state is not None else True
        await self._notify_controller()

    async def async_turn_on(self) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()
        await self._notify_controller()

    async def async_turn_off(self) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()
        await self._notify_controller()

    async def _notify_controller(self) -> None:
        self.context.controller.standby = self._attr_is_on
        await self.context.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    context = hass.data[DOMAIN][entry.entry_id][KEY_CONTEXT]
    async_add_entities([VictronMK3StandbySwitchEntity(context)])
