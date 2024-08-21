[![hacs_badge](https://img.shields.io/badge/HACS-Experimental-bbaa25.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Victron VE.Bus MK3 Interface Integration

A Home Assistant integration for communicating with certain Victron charger and inverter
devices that have VE.Bus ports using the Victron Interface MK3-USB (VE.Bus to USB).

This integration lets you build a remote control panel for your charger/inverter.

- Sensors describe the status of your device and its electrical performance.
- The `Remote Panel Mode` entity sets the mode to on, off, charger_only, or inverter_only.
- The `Remote Panel Current Limit` entity sets the AC input current limit.
- The `victron_mk3.set_remote_panel_state` service action sets both the panel mode and the
  current limit simultaneously.

Note that the remote panel mode and current limit persists even after the interface
has been disconnected or the device is turned off. To restore the device to its default
behavior, set the remote panel mode to `on` and set the current limit to its maximum.

Refer to the [victron-mk3 library](https://github.com/j9brown/victron-mk3) for the list of supported devices.

## Entities

### AC Sensors

- AC Input Voltage
- AC Input Current
- AC Input Frequency
- AC Output Voltage
- AC Output Current
- AC Output Frequency

If your device has multiple AC phases, you must enable the sensors for the additional phases that
you need (such as AC Input Voltage L2) because they are disabled by default.

### Battery Sensors

- Battery Voltage
- Battery Input Current
- Battery Output Current

### Configuration

- Remote Panel Mode: off, on, charging_only, inverter_only
- Remote Panel Current Limit

### Diagnostics

- AC Input Current Limit
- AC Input Current Limit Maximum
- AC Input Current Limit Minimum
- Device State: down, startup, off, slave, invert_full, invert_half, invert_aes, power_assist, bypass, state_charge
- Front Panel Mode: off, on, charging_only
- Actual Mode: off, on, charging_only, inverter_only
- Lit Indicators: mains, absorption, bulk, float, inverter, overload, low_battery, temperature
- Blinking Indicators: mains, absorption, bulk, float, inverter, overload, low_battery, temperature
- Firmware Version

## Services

The `victron_mk3.set_remote_panel_state` service action sets the remote panel mode and
current limit simultaneously. The mode is required whereas the current limit is optional
and defaults to its maximum value.

The device id is a unique identifier assigned to the device by Home Assistant. To find this
value, visit the Developer Tools -> Actions page in the Home Assistant UI, select the
`victron_mk3.set_remote_panel_state` action, pick the device from the list of targets,
then view the result in YAML mode.

Here are some examples.

Set the remote panel mode to `on` and the current limit to its maximum.

```yaml
action: victron_mk3.set_remote_panel_state
data:
  device_id: 54b361121006d7658fa486a9ebaf02bc
  mode: "on"
```

Set the remote panel mode to `charger_only` and the current limit to 12.5 amps.

```yaml
action: victron_mk3.set_remote_panel_state
data:
  device_id: 54b361121006d7658fa486a9ebaf02bc
  mode: "charger_only"
  current_limit: 12.5
```

# Installation

## Manual

1. Clone the repository to your machine and copy the contents of custom_components/ to your config directory.
2. Restart Home Assistant.
3. Plug in the Victron MK3 interface.
4. Setup integration via the integration page.

## HACS

1. Add the integration through this link:
   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=j9brown&repository=victron-mk3-hacs&category=integration)
2. Restart Home Assistant
3. Plug in the Victron MK3 interface.
4. Setup integration via the integration page.

## Integration setup

The device should have been auto-discovered and available to set up with one click. If not, click the button
in the UI to add the "Victron MK3" integration then specify the path of the Victron MK3 interface's
serial port device.

# Alternatives

Victron offers several products for controlling VE.Bus based charger and inverter devices.
Here's a quick overview of some of them.

[Victron Interface MK3-USB](https://www.victronenergy.com/accessories/interface-mk3-usb):

- Actively monitor and control your device with Home Assistant using this
  [victron-mk3-hacs](https://github.com/j9brown/victron-mk3-hacs) integration.
- Configure your device when plugged into a computer running [VictronConnect](https://www.victronenergy.com/victronconnectapp/victronconnect/downloads).

[Victron VE.Bus Smart Dongle](https://www.victronenergy.com/communication-centres/ve-bus-smart-dongle):

- Passively monitor your device with Home Assistant via Bluetooth Low Energy using
  the [victron-ble-hacs](https://github.com/keshavdv/victron-hacs) integration (or
  this [fork](https://github.com/j9brown/victron-hacs/tree/main).
- Configure your device wirelessly from a computer or smartphone running [VictronConnect](https://www.victronenergy.com/victronconnectapp/victronconnect/downloads).
- Cannot set the operating mode or current limit.
- Does not report AC input and output voltages and frequency over Bluetooth LE
  (Home Assistant cannot determine whether the device is plugged into mains when the charger
  and inverter are not operating) unlike Victron Interface MK3-USB.

[Victron GX Controllers](https://www.victronenergy.com/communication-centres):

- Actively monitor and control your device with Home Assistant via a TCP connection
  using the [hass-victron]https://github.com/sfstar/hass-victron).
- Some variants offer programmable control panels and displays.

On devices with multiple VE.Bus ports, it is possible to combine products to achieve
complementary goals. This author uses the USB interface to let Home Assistant control
the operating mode and a Bluetooth smart dongle for the VictronConnect app.
