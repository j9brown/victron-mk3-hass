# Victron VE.Bus MK3 Interface Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)

A Home Assistant integration for communicating with certain Victron charger and inverter
devices that have VE.Bus ports using the Victron Interface MK3-USB (VE.Bus to USB).

This integration lets you build a remote control panel for your charger/inverter.

- Sensors describe the status of your device and its electrical performance.
- The `Remote Panel Mode` entity sets the mode to on, off, charger_only, or inverter_only.
- The `Remote Panel Current Limit` entity sets the AC input current limit.
- The `Remote Panel Standby` entity sets whether the device will be prevented from
  sleeping while it is turned off. Refer to the [standby mode](#standby-mode) section for more details.
- The `victron_mk3.set_remote_panel_state` service action sets both the panel mode and the
  current limit simultaneously.

Here's what each remote panel switch state means:

- `on`: Enable the charger and enable the inverter.
- `charger_only`: Enable the charger and disable the inverter.
- `inverter_only`: Enable the inverter and disable the charger.
- `off`: Disable the charger and disable the inverter.

The front panel switch and other inputs on the device may override the remote panel switch state.

- When the device is turned off by the front panel switch or by the remote on/off connection, neither the charger nor the inverter will operate.
- When the device is forced to charge only mode using the front panel switch, the inverter will not operate regardless of the remote panel switch state set by this interface.
- Other conditions determined by the device may also apply such as constraints on the mains voltage and battery state of charge.

The device retains the remote panel switch state and current limit set by the MK3 interface even after it has been disconnected from VE.Bus until the device goes to sleep (assuming it is not on standby). To restore the device to its default behavior, set the remote panel mode to `on` and set the current limit to its maximum.

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
- AC Input Current Limit Minimum: the lowest limit the device applies while
  PowerAssist is enabled; it has been seen to read 0 in charger-only mode
- PowerAssist Active: off, on; the device is assisting now (Device State
  power_assist)
- Device State: down, startup, off, slave, invert_full, invert_half, invert_aes, power_assist, bypass, state_charge
- Front Panel Mode: off, on, charging_only
- Actual Mode: off, on, charging_only, inverter_only
- Lit Indicators: mains, absorption, bulk, float, inverter, overload, low_battery, temperature
- Blinking Indicators: mains, absorption, bulk, float, inverter, overload, low_battery, temperature
- Firmware Version
- Device Firmware Version: the VE.Bus device's firmware version (e.g. 509),
  read at startup

Solar & Wind Priority entities are listed under
[Prioritize Solar & Wind](#prioritize-solar--wind).

## Prioritize Solar & Wind

[Solar & Wind Priority](https://www.victronenergy.com/upload/documents/Solar_&_Wind_Priority/156386-Solar___Wind_Priority-pdf-en.pdf)
is a Victron feature that keeps the battery below full so solar and wind can
top it up. This integration does not set the feature up: configure and enable
it the usual way, for example with VictronConnect. With the feature enabled,
the integration gives you a switch to override it and charge to 100% once.

The override needs VE.Bus firmware 506 or later (see Device Firmware Version
diagnostic entity) and a device that confirms an override may be triggered.
The integration checks both at startup. If either check fails, or cannot be read, the switch is
disabled and unavailable; reload the integration after updating the firmware.

Entities:

- Solar & Wind Priority Charge to 100% (switch): on while an override is
  running. Turning it on starts one and turning it off stops it. It is off
  while the feature is not enabled and while the device charges to 100%
  because AC input 1 is connected or a generator is running, and turning it on
  is refused then. It is unavailable while the state cannot be read.
- Solar & Wind Priority Enabled (diagnostic): off, on.
- Solar & Wind Priority Charge Voltage (diagnostic): the voltage the feature
  holds the battery at.
- Solar & Wind Priority Charge to 100% Reason (diagnostic): off, one_shot
  (an override is running), ac_input_or_generator.


### Technical Description

How the switch works: it puts the interface in long-frame mode
(`04 FF 41 01 00`, `02 FF 44`, then `09 FF 53 <s> <l> <h> 01 D0 3E 06` with
the three state bytes from the `02 FF 44` reply) and holds off polling. It
then checks the software version reply (0x05) is the long form with firmware
506 or later, that the setting info for setting 60 (0x35) lists bit 9, and
that setting 60 (`31 3C 00`) has bit 9 set. It writes setting 60 back to RAM
only with bit 9 cleared to start or set to stop (`37 03 3C <lo> <hi>`; from
528, start writes `37 03 3C 10 00` and stop `37 03 3C 10 02`), and returns
the interface to short-frame mode with `09 FF 53 00 00 00 01 90 00 01`, even
if a step failed. The device must reply 0x88 and report the new state within
10 seconds. A failed change is not retried.

The startup read sends `04 FF 41 01 00`, then `05 00 00` and `06 00 00` (the
low and high halves of the version). Unless the firmware is older than 506, it
then enters long-frame mode as above, reads the version with 0x05 if either
short read got no valid reply, reads the setting info for setting 60
(`35 3C 00`), and returns to short-frame mode. It writes nothing.

The integration only changes the RAM copy of setting 60, never the stored
(EEPROM) copy, so the unit's configuration is not changed. If the unit is left
in an unintended state, a power cycle should clear it.

## Services

The `victron_mk3.set_remote_panel_state` service action sets the remote panel mode and
current limit simultaneously. The mode is required whereas the current limit is optional.
A current limit below 0 or above the device's maximum (the AC Input Current Limit Maximum
entity) is rejected and nothing is sent.

Note: this behaviour changed from the 0.8.0 release.  Formerly the current limit was set to
the max supported by the unit unless explicitly re-specified - with potentially dangerous
consequences for equipment.

If the current limit is not given, the device's actual current limit is kept: it is read from
the device just before the mode is sent, and the last current limit this integration sent is
used instead if that is lower. If the limit cannot be read (for example while the device is
asleep, or when a Digital Multi Control sets it), nothing is sent and the action fails. The
Remote Panel Mode entity keeps the current limit the same way. To reset the
current limit to the device's maximum instead, set `reset_to_max_current_limit: true`.

After sending a current limit above 0, the integration reads the device's actual current
limit back. The device sometimes acknowledges the panel state without applying the limit,
so the same panel state is sent again, up to three times in all. If the limit is still not
applied, the action fails. The Remote Panel Current Limit and Remote Panel Mode entities
check the limit the same way. A reset to the maximum, or a limit of 0, is not checked.

> [!WARNING]
> Be careful when choosing a current limit.  Do not tell the Victron unit to draw more than
> your shore supply / generator / etc. can provide.  At best this will trip a breaker; at
> worst it could damage equipment or start a fire.  Always ascertain the safe maximum current
> for your supply before setting this. 

Here are some examples.

Set the remote panel mode to `on` and keep the present current limit.

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

Set the remote panel mode to `on` and the current limit to maximum permitted by the unit.

```yaml
action: victron_mk3.set_remote_panel_state
data:
  device_id: 54b361121006d7658fa486a9ebaf02bc
  mode: "on"
  reset_to_max_current_limit: true
```

## Standby mode

When the charger/inverter device is turned off and standby mode is not enabled, it may go to sleep and shut off its internal power supply to avoid draining the batteries. Because the MK3 interface is powered from the device's VE.Bus port, then the interface will lose power when the device is turned off and it will be unable to send a command to wake the device up again.

The solution is to enable standby mode. When standby mode is enabled, the MK3 interface will prevent the device from going to sleep as long as it remains connected to the device's VE.Bus. Note that the device draws more energy from the batteries while in standby than it would while sleeping.

We recommend always enabling standby mode to maintain control of the device at all times.

## Troubleshooting

### What to do if your charger/inverter turned itself off and won't turn on anymore (and the front panel switch doesn't work)

Don't panic!

Your device probably thinks it's supposed to be sleeping and it needs little nudge to wake up or forget that it's supposed to be sleeping. The device firmware determines the operating mode based on several factors, including the state of the front panel switch, remote panel state (set via the MK3 interface), and remote on/off connection. You might feel concerned that toggling the front panel switch doesn't fix the problem right away and it's probably going to be fine.

Here are some possible recovery methods:

- Check the front panel status indicators on the device. If some of indicators are lit, they may tell you what the problem is.
- If you have connected a switch to the remote on/off switch input of your device, make sure it's in the ON position and that the wires are intact.
- Plug the device into AC mains. The device should wake up within a few seconds and begin responding to the MK3 interface again. Use the MK3 interface to set the remote panel mode to ON.
- Unplug the MK3 interface from the VE.Bus port or disconnect the ethernet jack from the interface. Toggle the front panel switch to OFF. Wait at least 30 seconds for the device to fully go to sleep. Toggle the front panel switch to ON and wait a few seconds for the device to turn on. If that didn't work, try toggling the front panel switch to CHARGE ONLY then OFF, wait at least 30 seconds again, then ON again. Plug the MK3 interface back in as before.
- Ensure the device is connected to the batteries and receiving power.

Once you have resolved the issue, consider enabling [standby mode](#standby-mode) to prevent the device from falling asleep unintentionally.

### What to do if the MK3 interface has difficulties communicating with your charger/inverter device

Here are some things to try if the MK3 interface appears to be having difficulties communicating with your charger/inverter device or is outputting incomplete data:

- Check the logs for relevant messages.
- Ensure that the MK3 interface is plugged into USB and the path of the serial port is correct.
- The MK3 interface receives power from VE.Bus and will not operate if the device is asleep. Ensure it is plugged into VE.Bus and awake as explained in [this topic](#what-to-do-if-your-chargerinverter-turned-itself-off-and-wont-turn-on-anymore-and-the-front-panel-switch-doesnt-work).
- Unplug the MK3 interface from your computer's USB port, unplug the MK3 interface from the device's VE.Bus (or disconnect the ethernet jack from the interface), plug the MK3 back in as before, and try again.
- If you have connected additional peripherals to your device's VE.Bus ports, try unplugging them to rule out possible conflicts with the MK3 interface.
- If you just operated your MK3 interface using a different program such as the Victron Connect app, the interface may have been left in a state that this library doesn't know how to handle. Quit the other program, unplug the MK3 from VE.Bus to reset it, plug it back in, and try again.
- Try using the MK3 interface with Victron Connect, just to make sure it works, and to apply firmware updates to the device.

# Installation

## Manual

1. Clone the repository to your machine and copy the contents of custom_components/ to your config directory.
2. Restart Home Assistant.
3. Plug in the Victron MK3 interface.
4. Setup integration via the integration page.

## HACS

1. Add the integration through this link:
   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=j9brown&repository=victron-mk3-hass&category=integration)
2. Restart Home Assistant.
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
