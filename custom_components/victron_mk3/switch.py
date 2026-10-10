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
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Context
from .prioritize_wind_and_solar import PRIORITY_ENABLED_BIT, PRIORITY_STATE_OVERRIDDEN
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


class VictronMK3PriorityOverrideSwitchEntity(CoordinatorEntity, SwitchEntity):
    """Starts or stops the Solar & Wind Priority override (a one-time charge to
    100%). On only while the device reports the override; off otherwise,
    including while Solar & Wind Priority is not enabled and while charging to
    100% because AC input 1 is connected or a generator is running.
    Unavailable while that state cannot be read. Disabled and unavailable
    unless the device read at startup supports the override."""

    _attr_has_entity_name = True

    entity_description = SwitchEntityDescription(
        key="solar_wind_priority_one_shot_charge_to_100",
        name="Solar & Wind Priority Charge to 100%",
        device_class=SwitchDeviceClass.SWITCH,
    )

    def __init__(self, context: Context):
        CoordinatorEntity.__init__(
            self, context.coordinator, self.entity_description.key
        )
        self.context = context
        self._attr_device_info = context.device_info
        self._attr_unique_id = f"{context.device_id}-{self.entity_description.key}"
        self._attr_entity_registry_enabled_default = (
            context.controller.priority_override_supported
        )

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.context.controller.priority_override_supported
            and self.is_on is not None
        )

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None or data.solar_wind_priority is None:
            return None
        if not data.solar_wind_priority.value & PRIORITY_ENABLED_BIT:
            return False
        if data.priority_state is None:
            return None
        return data.priority_state == PRIORITY_STATE_OVERRIDDEN

    async def async_turn_on(self, **kwargs) -> None:
        await self.context.controller.set_prioritize_wind_and_solar_override(True)
        await self.context.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.context.controller.set_prioritize_wind_and_solar_override(False)
        await self.context.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    context = hass.data[DOMAIN][entry.entry_id][KEY_CONTEXT]
    override = VictronMK3PriorityOverrideSwitchEntity(context)
    _sync_disabled(hass, override)
    async_add_entities([VictronMK3StandbySwitchEntity(context), override])


def _sync_disabled(
    hass: HomeAssistant, entity: VictronMK3PriorityOverrideSwitchEntity
) -> None:
    """Disables an already registered override switch when the device does not
    support the override, and enables it again when it does, unless a user
    disabled it. A newly registered switch is handled by
    entity_registry_enabled_default."""
    registry = entity_registry.async_get(hass)
    entity_id = registry.async_get_entity_id("switch", DOMAIN, entity.unique_id)
    if entity_id is None:
        return
    disabled_by = registry.async_get(entity_id).disabled_by
    integration = entity_registry.RegistryEntryDisabler.INTEGRATION
    if not entity.entity_registry_enabled_default and disabled_by is None:
        registry.async_update_entity(entity_id, disabled_by=integration)
    elif entity.entity_registry_enabled_default and disabled_by == integration:
        registry.async_update_entity(entity_id, disabled_by=None)
