from __future__ import annotations

from dataclasses import dataclass
from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, NumberMode, UnitOfElectricCurrent
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from typing import Awaitable, Callable

from . import Context, Data
from .const import (
    DOMAIN,
    KEY_CONTEXT,
)


async def set_remote_panel_current_limit(context: Context, value: float) -> None:
    data = context.coordinator.data
    if data is None or data.config is None:
        raise HomeAssistantError("Device is not available")

    mode = data.remote_panel_mode()
    await context.controller.set_remote_panel_state(mode, value)
    await context.coordinator.async_request_refresh()


@dataclass(kw_only=True)
class VictronMK3NumberEntityDescription(NumberEntityDescription):
    range_fn: Callable[[Data], tuple[float, float, float, float]]
    set_fn: Callable[[Context, float], Awaitable[None]]


ENTITY_DESCRIPTIONS: tuple[VictronMK3NumberEntityDescription, ...] = (
    VictronMK3NumberEntityDescription(
        key="remote_panel_current_limit",
        name="Remote Panel Current Limit",
        device_class=NumberDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        range_fn=lambda data: None
        if data.config is None
        else (
            data.config.minimum_current_limit,
            data.config.maximum_current_limit,
            0.1,
            data.config.actual_current_limit,
        ),
        set_fn=set_remote_panel_current_limit,
    ),
)


class VictronMK3NumberEntity(CoordinatorEntity, NumberEntity):
    _attr_has_entity_name = True

    def __init__(
        self, context: Context, entity_description: VictronMK3NumberEntityDescription
    ):
        CoordinatorEntity.__init__(self, context.coordinator, entity_description.key)
        self.context = context
        self.entity_description = entity_description
        self._attr_device_info = context.device_info
        self._attr_unique_id = f"{context.device_id}-{entity_description.key}"
        self._attr_available = False
        self._attr_native_min_value = 0
        self._attr_native_max_value = 0
        self._attr_native_step = None
        self._attr_native_value = None

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        value = None if data is None else self.entity_description.range_fn(data)
        if value is None:
            self._attr_available = False
        else:
            self._attr_available = True
            self._attr_native_min_value = value[0]
            self._attr_native_max_value = value[1]
            self._attr_native_step = value[2]
            self._attr_native_value = value[3]
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        await self.entity_description.set_fn(self.context, value)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    context = hass.data[DOMAIN][entry.entry_id][KEY_CONTEXT]
    async_add_entities(
        VictronMK3NumberEntity(context, description)
        for description in ENTITY_DESCRIPTIONS
    )
