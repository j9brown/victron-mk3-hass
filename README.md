[![hacs_badge](https://img.shields.io/badge/HACS-Experimental-bbaa25.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Victron VE.Bus MK3 Interface Integration

A Home Assistant integration for communicating with certain Victron charger and inverter
devices that have VE.Bus ports using the Victron Interface MK3-USB (VE.Bus to USB).

This integration acts as a remote control panel to monitor the status and performance
of the device and to set remote switch states and current limits.

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