from __future__ import annotations

from dataclasses import dataclass
from homeassistant.components.select import (
    SelectEntity,
    SelectEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from typing import Awaitable, Callable

from . import Context, Data, Mode, enum_options, enum_value, mode_from_value
from .const import (
    DOMAIN,
    KEY_CONTEXT,
)


async def select_remote_panel_mode(context: Context, option: str) -> None:
    data = context.coordinator.data
    if data is None or data.config is None:
        raise HomeAssistantError("Device is not available")

    mode = mode_from_value(option)
    current_limit = data.config.actual_current_limit
    await context.controller.set_remote_panel_state(mode, current_limit)
    await context.coordinator.async_request_refresh()


@dataclass(kw_only=True)
class VictronMK3SelectEntityDescription(SelectEntityDescription):
    value_fn: Callable[[Data], str]
    select_fn: Callable[[Context, str], Awaitable[None]]


ENTITY_DESCRIPTIONS: tuple[VictronMK3SelectEntityDescription, ...] = (
    VictronMK3SelectEntityDescription(
        key="remote_panel_mode",
        name="Remote Panel Mode",
        options=enum_options(Mode),
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: enum_value(data.remote_panel_mode()),
        select_fn=select_remote_panel_mode,
    ),
)


class VictronMK3SelectEntity(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True

    def __init__(
        self, context: Context, entity_description: VictronMK3SelectEntityDescription
    ):
        CoordinatorEntity.__init__(self, context.coordinator, entity_description.key)
        self.context = context
        self.entity_description = entity_description
        self._attr_device_info = context.device_info
        self._attr_unique_id = f"{context.device_id}-{entity_description.key}"
        self._attr_available = False
        self._attr_current_option = None

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        value = None if data is None else self.entity_description.value_fn(data)
        if value is None:
            self._attr_available = False
        else:
            self._attr_available = True
            self._attr_current_option = value
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        await self.entity_description.select_fn(self.context, option)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    context = hass.data[DOMAIN][entry.entry_id][KEY_CONTEXT]
    async_add_entities(
        VictronMK3SelectEntity(context, description)
        for description in ENTITY_DESCRIPTIONS
    )
