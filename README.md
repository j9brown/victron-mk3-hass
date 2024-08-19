[![hacs_badge](https://img.shields.io/badge/HACS-Experimental-bbaa25.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Victron VE.Bus MK3 Interface Integration

A Home Assistant integration for communicating with certain Victron charger and inverter
devices that have VE.Bus ports using the Victron Interface MK3-USB (VE.Bus to USB).

This integration lets you build a remote control panel for your charger/inverter.

- Use sensors to monitor the status of your device and its electrical performance.
- Use the `victron_mk3.set_remote_panel_mode` service action to change the operating mode
  (on, off, charger_only, or inverter_only) and optionally the AC input current limit.

Note that the remote panel mode and current limit may persist even after the interface
has been disconnected or the device is turned off. To restore the device to its default
behavior, use the `victron_mk3.set_remote_panel_mode` service action to set the operating
mode back to on and to reset the remotely configured current limit.

Refer to the [victron-mk3 library](https://github.com/j9brown/victron-mk3) for the list of supported devices.

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
