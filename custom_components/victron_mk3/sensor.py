from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfFrequency,
    UnitOfElectricPotential,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    CoordinatorEntity,
)
from homeassistant.helpers.typing import StateType
from typing import Callable
from victron_mk3 import DeviceState, LEDState, SwitchRegister, SwitchState

from . import Data, Mode, enum_options, enum_native_value
from .const import (
    DOMAIN,
    KEY_DATA_UPDATE_COORDINATOR,
    KEY_DEVICE_ID,
    KEY_DEVICE_INFO,
)


def front_panel_mode(reg: SwitchRegister) -> Mode:
    if reg & SwitchRegister.FRONT_SWITCH_UP != 0:
        return Mode.ON
    if reg & SwitchRegister.FRONT_SWITCH_DOWN != 0:
        return Mode.CHARGER_ONLY
    return Mode.OFF


def remote_panel_mode(reg: SwitchRegister) -> Mode:
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


def actual_mode(reg: SwitchRegister) -> Mode:
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


@dataclass(kw_only=True)
class VictronMK3SensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[Data], StateType]


def make_ac_phase_sensors(phase: int) -> tuple[VictronMK3SensorEntityDescription, ...]:
    index = phase - 1
    enable_default = phase == 1
    key_suffix = "" if phase == 1 else f"_l{phase}"
    name_suffix = "" if phase == 1 else f" L{phase}"
    return (
        VictronMK3SensorEntityDescription(
            key=f"ac_input_voltage{key_suffix}",
            name=f"AC Input Voltage{name_suffix}",
            device_class=SensorDeviceClass.VOLTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            entity_registry_enabled_default=enable_default,
            value_fn=lambda data: None
            if data.ac[index] is None
            else data.ac[index].ac_mains_voltage,
        ),
        VictronMK3SensorEntityDescription(
            key=f"ac_input_current{key_suffix}",
            name=f"AC Input Current{name_suffix}",
            device_class=SensorDeviceClass.CURRENT,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            entity_registry_enabled_default=enable_default,
            value_fn=lambda data: None
            if data.ac[index] is None
            else data.ac[index].ac_mains_current,
        ),
        VictronMK3SensorEntityDescription(
            key=f"ac_output_voltage{key_suffix}",
            name=f"AC Output Voltage{name_suffix}",
            device_class=SensorDeviceClass.VOLTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            entity_registry_enabled_default=enable_default,
            value_fn=lambda data: None
            if data.ac[index] is None
            else data.ac[index].ac_inverter_voltage,
        ),
        VictronMK3SensorEntityDescription(
            key=f"ac_output_current{key_suffix}",
            name=f"AC Output Current{name_suffix}",
            device_class=SensorDeviceClass.CURRENT,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            entity_registry_enabled_default=enable_default,
            value_fn=lambda data: None
            if data.ac[index] is None
            else data.ac[index].ac_inverter_current,
        ),
    )


SENSORS: tuple[VictronMK3SensorEntityDescription, ...] = (
    (
        VictronMK3SensorEntityDescription(
            key="ac_input_current_limit",
            name="AC Input Current Limit",
            device_class=SensorDeviceClass.CURRENT,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda data: None
            if data.config is None
            else data.config.actual_current_limit,
        ),
        VictronMK3SensorEntityDescription(
            key="ac_input_current_limit_maximum",
            name="AC Input Current Limit Maximum",
            device_class=SensorDeviceClass.CURRENT,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda data: None
            if data.config is None
            else data.config.maximum_current_limit,
        ),
        VictronMK3SensorEntityDescription(
            key="ac_input_current_limit_minimum",
            name="AC Input Current Limit Minimum",
            device_class=SensorDeviceClass.CURRENT,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda data: None
            if data.config is None
            else data.config.minimum_current_limit,
        ),
        VictronMK3SensorEntityDescription(
            key="ac_input_frequency",
            name="AC Input Frequency",
            device_class=SensorDeviceClass.FREQUENCY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfFrequency.HERTZ,
            value_fn=lambda data: None
            if data.ac[0] is None
            else data.ac[0].ac_mains_frequency,
        ),
        VictronMK3SensorEntityDescription(
            key="ac_output_frequency",
            name="AC Output Frequency",
            device_class=SensorDeviceClass.FREQUENCY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfFrequency.HERTZ,
            value_fn=lambda data: None
            if data.dc is None
            else data.dc.ac_inverter_frequency,
        ),
        VictronMK3SensorEntityDescription(
            key="battery_voltage",
            name="Battery Voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            value_fn=lambda data: None if data.dc is None else data.dc.dc_voltage,
        ),
        VictronMK3SensorEntityDescription(
            key="battery_input_current",
            name="Battery Input Current",
            device_class=SensorDeviceClass.CURRENT,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            value_fn=lambda data: None
            if data.dc is None
            else data.dc.dc_current_from_charger,
        ),
        VictronMK3SensorEntityDescription(
            key="battery_output_current",
            name="Battery Output Current",
            device_class=SensorDeviceClass.CURRENT,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            value_fn=lambda data: None
            if data.dc is None
            else data.dc.dc_current_to_inverter,
        ),
        VictronMK3SensorEntityDescription(
            key="device_state",
            name="Device State",
            device_class=SensorDeviceClass.ENUM,
            options=enum_options(DeviceState),
            value_fn=lambda data: None
            if data.ac[0] is None
            else enum_native_value(data.ac[0].device_state),
        ),
        VictronMK3SensorEntityDescription(
            key="firmware_version",
            name="Firmware Version",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda data: None
            if data.version is None
            else data.version.version,
        ),
        VictronMK3SensorEntityDescription(
            key="lit_indicators",
            name="Lit Indicators",
            device_class=SensorDeviceClass.ENUM,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda data: None
            if data.led is None
            else enum_native_value(data.led.on),
        ),
        VictronMK3SensorEntityDescription(
            key="blinking_indicators",
            name="Blinking Indicators",
            device_class=SensorDeviceClass.ENUM,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda data: None
            if data.led is None
            else enum_native_value(data.led.blink),
        ),
        VictronMK3SensorEntityDescription(
            key="front_panel_mode",
            name="Front Panel Mode",
            device_class=SensorDeviceClass.ENUM,
            options=enum_options(Mode),
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda data: None
            if data.config is None
            else enum_native_value(front_panel_mode(data.config.switch_register)),
        ),
        VictronMK3SensorEntityDescription(
            key="remote_panel_mode",
            name="Remote Panel Mode",
            device_class=SensorDeviceClass.ENUM,
            options=enum_options(Mode),
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda data: None
            if data.config is None
            else enum_native_value(remote_panel_mode(data.config.switch_register)),
        ),
        VictronMK3SensorEntityDescription(
            key="actual_mode",
            name="Actual Mode",
            device_class=SensorDeviceClass.ENUM,
            options=enum_options(Mode),
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda data: None
            if data.config is None
            else enum_native_value(actual_mode(data.config.switch_register)),
        ),
    )
    + make_ac_phase_sensors(1)
    + make_ac_phase_sensors(2)
    # + make_ac_phase_sensors(3)
    # + make_ac_phase_sensors(4)
)


class VictronMK3SensorEntity(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[Data],
        entity_description: VictronMK3SensorEntityDescription,
        device_id: str,
        device_info: DeviceInfo,
    ):
        CoordinatorEntity.__init__(self, coordinator, entity_description.key)
        self.entity_description = entity_description
        self._attr_device_info = device_info
        self._attr_unique_id = f"{device_id}-{entity_description.key}"

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        value = None if data is None else self.entity_description.value_fn(data)
        if value is None:
            self._attr_available = False
        else:
            self._attr_available = True
            self._attr_native_value = value
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = entry_data[KEY_DATA_UPDATE_COORDINATOR]
    device_id = entry_data[KEY_DEVICE_ID]
    device_info = entry_data[KEY_DEVICE_INFO]
    async_add_entities(
        VictronMK3SensorEntity(coordinator, description, device_id, device_info)
        for description in SENSORS
    )