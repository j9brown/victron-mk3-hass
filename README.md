[![hacs_badge](https://img.shields.io/badge/HACS-Experimental-bbaa25.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Victron VE.Bus MK3 Interface Integration

A Home Assistant integration for communicating with certain Victron charger and inverter
devices that have VE.Bus ports using the Victron Interface MK3-USB (VE.Bus to USB).

This integration lets you build a remote control panel for your charger/inverter.

- Sensors describe the status of your device and its electrical performance.
- The `Remote Panel Mode` entity sets the mode to on, off, charger_only, or inverter_only.
- The `Remote Panel Current Limit` entity sets the AC input current limit.
- The `Remote Panel Standby` entity sets whether the device will be prevented from
  sleeping while it is turned off. Refer to the standby section for more details.
- The `victron_mk3.set_remote_panel_state` service action sets both the panel mode and the
  current limit simultaneously.

Note that the remote panel mode and current limit persists even after the interface
has been disconnected or the device is turned off. To restore the device to its default
behavior, set the remote panel mode to `on` and set the current limit to its maximum.

Refer to the [victron-mk3 library](https://github.com/j9brown/victron-mk3) for the list of supported devices.

## Entities

### AC sensors

- AC Input Voltage
- AC Input Current
- AC Input Power
- AC Input Frequency
- AC Output Voltage
- AC Output Current
- AC Output Power
- AC Output Frequency

If your device has multiple AC phases, you must enable the sensors for the additional phases that
you need (such as AC Input Voltage L2) because they are disabled by default.

### Battery sensors

- Battery Voltage
- Battery Input Current
- Battery Output Current
- Battery Power

### Configuration entities

- Remote Panel Mode: off, on, charging_only, inverter_only
- Remote Panel Current Limit
- Remote Panel Standby: off, on

### Diagnostic entities

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

## Standby

When the device is turned off, it may go to sleep and shut off its internal power supply
to avoid draining the batteries. Because the MK3 interface is powered from device's VE.Bus
port, it too will lose power and it will become unresponsive. Consequently, you will not
be able to turn the device back on again using the interface.

Don't panic!

There are two ways to resolve this issue:

- When standby mode is enabled, the interface will prevent the device from going to sleep
  as long as it remains connected to the device's VE.Bus. Note that the device draws more energy
  from the batteries while in standby than it would while sleeping.
- The device will automatically wake up from sleep whenever power is supplied to its AC input.

So if the device is asleep and it is not responding to the MK3 interface, just plug it into
the AC mains to wake it up. Try sending the command again and consider enabling standby mode.

# Installation

## Manual

1. Clone the repository to your machine and copy the contents of custom_components/ to your config directory.
2. Restart Home Assistant.
3. Plug in the Victron MK3 interface.
4. Setup integration via the integration page.

## HACS

1. Add the integration through this link:
   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=j9brown&repository=victron-mk3-hass&category=integration)
2. Restart Home Assistant
3. Plug in the Victron MK3 interface.
4. Setup integration via the integration page.

## Integration setup

The device should have been auto-discovered and available to set up with one click. If not, click the button
in the UI to add the "Victron MK3" integration then specify the path of the Victron MK3 interface's
serial port device.

# Alternatives

Victron provides several options for controlling VE.Bus based charger and inverter devices.
Here's a quick overview of some of them.

[Victron Interface MK3-USB](https://www.victronenergy.com/accessories/interface-mk3-usb):

- Actively monitor and control your device with Home Assistant using this
  [victron-mk3-hass](https://github.com/j9brown/victron-mk3-hass) integration.
- Can set the operating mode and current limit and keep the device in standby.
- Configure your device over USB from a computer running [VictronConnect](https://www.victronenergy.com/victronconnectapp/victronconnect/downloads).

[Victron VE.Bus Smart Dongle](https://www.victronenergy.com/communication-centres/ve-bus-smart-dongle):

- Passively monitor your device with Home Assistant via Bluetooth Low Energy using
  the [victron-ble-hacs](https://github.com/keshavdv/victron-hacs) integration (or
  this [fork](https://github.com/j9brown/victron-hacs/tree/main)) or with an
  [ESPHome device](https://esphome.io/) and the [esphome-victron_ble](https://github.com/Fabian-Schmidt/esphome-victron_ble) component.
- Because the integrations are passive, they cannot set the operating mode or current limit.
- Configure your device over Bluetooth from a computer or smartphone running
  [VictronConnect](https://www.victronenergy.com/victronconnectapp/victronconnect/downloads).

[Victron GX Controllers](https://www.victronenergy.com/communication-centres):

- Actively monitor and control your device with Home Assistant over a network connection
  using the [hass-victron](https://github.com/sfstar/hass-victron) integration.
- Some GX devices have displays and programmable control panels.

Built-in remote on/off control:

- Simple: only requires wiring a switch to the remote on/off terminals.
- On/off only: cannot switch between operating modes such as on and charger_only.

For devices with multiple VE.Bus ports, you can combine certain products to achieve
complementary goals such as using a Smart Dongle to configure devices with the
VictronConnect app and using a USB Interface to remotely set the operating mode
and current limit from Home Assistant.
