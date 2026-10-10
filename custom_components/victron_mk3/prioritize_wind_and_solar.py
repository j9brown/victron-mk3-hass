"""Guarded start and stop of the Solar & Wind Priority override.

With Solar & Wind Priority enabled, the MultiPlus holds the battery below
full so solar and wind can top it up. The override makes it charge to 100%
once.

The override is started by clearing, and stopped by setting, bit 9 of
setting 60 with a WriteViaID command that changes only the live (RAM) value:

    37 03 3C <lo> <hi>

The new value is the value of setting 60 read just before the write with only
bit 9 changed. The reply 0x88 means the device accepted it.

Each start or stop:

* Reads whether Solar & Wind Priority is enabled and the override state.
  Nothing is written if the device already reports the requested state. A
  stop needs nothing written while the feature is not enabled or while the
  device charges to 100% because AC input 1 is connected or a generator is
  running; a start is refused in those two cases.
* Runs the checks and the write inside a long-frame session (see
  Transport.long_frame_session). The checks refuse the write unless the
  software version reply is the long form with firmware 506 or later, the
  setting info for setting 60 lists bit 9 in its maximum, and setting 60 has
  bit 9 set. Setting 60 is a flag word, so the new value is not compared with
  the setting's minimum and maximum.
* Waits up to CONFIRM_TIMEOUT seconds for the device to report the new state.

A failed or unconfirmed write is never retried.

This module does not import Home Assistant, so it can be tested on its own.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from typing import AsyncContextManager, Protocol

_LOGGER = logging.getLogger(__name__)

# WriteViaID command, its flags for a setting written in RAM only, and the
# reply that means the setting was written.
WRITE_VIA_ID = 0x37
WRITE_SETTING_RAM_ONLY = 0x03
WRITE_SETTING_OK = 0x88

# Setting 60 bit 9 is set while Solar & Wind Priority is enabled. Clearing it
# in RAM only starts the override; setting it again stops the override.
PRIORITY_SETTING = 60
PRIORITY_ENABLED_BIT = 0x200

# Lowest firmware that supports the override. VE.Bus version numbers are
# AA BB CCC (product type, model, firmware), so this is compared with CCC.
MIN_FIRMWARE = 506

# Solar & Wind Priority states reported by the device: overridden (charging
# to 100% once), active (holding the battery below full), or charging to 100%
# because AC input 1 is connected or a generator is running.
PRIORITY_STATE_OVERRIDDEN = 0
PRIORITY_STATE_ACTIVE = 1
PRIORITY_STATE_AC_OR_GENERATOR = 2

CONFIRM_TIMEOUT = 10.0
CONFIRM_POLL_INTERVAL = 1.0


class PriorityOverrideError(Exception):
    """Why a start or stop did not happen. The message is shown to the user."""


class InterfaceModeError(PriorityOverrideError):
    """The interface could not be put into, or back out of, long-frame mode."""


@dataclass(frozen=True)
class SoftwareVersion:
    """The device's reply to the software version request."""

    version: int
    # Whether the reply was the long form, which the interface only sends in
    # long-frame mode.
    long_form: bool


def firmware_supported(version: int | None) -> bool:
    return version is not None and version % 1000 >= MIN_FIRMWARE


def override_write(value: int, active: bool) -> bytes:
    """The WriteViaID payload that starts (active=True) or stops the override,
    given the current value of setting 60: bit 9 changed, other bits kept."""
    new = value & ~PRIORITY_ENABLED_BIT if active else value | PRIORITY_ENABLED_BIT
    return bytes(
        [WRITE_VIA_ID, WRITE_SETTING_RAM_ONLY, PRIORITY_SETTING, new & 0xFF, new >> 8]
    )


class Transport(Protocol):
    """Device access. The caller serialises device I/O."""

    async def priority_enabled(self) -> bool | None:
        """Whether Solar & Wind Priority is enabled, or None on no reply."""

    async def priority_state(self) -> int | None:
        """A PRIORITY_STATE_ value, or None if the device did not answer."""

    async def read_setting(self, setting_id: int) -> int | None:
        """Reads a setting, or None if the device did not answer."""

    async def read_setting_maximum(self, setting_id: int) -> int | None:
        """A setting's maximum from the long-form setting info reply, or None
        if the device did not answer with the long form."""

    async def read_software_version(self) -> SoftwareVersion | None:
        """The device's software version, or None if it did not answer."""

    def long_frame_session(self) -> AsyncContextManager[None]:
        """Puts the interface in long-frame mode on entry and back in
        short-frame mode on exit, and holds off other device I/O in between.
        Raises InterfaceModeError if either change fails."""

    async def write(self, payload: bytes) -> bytes | None:
        """Sends one write and returns the raw reply, or None on no reply."""


class PriorityOverride:
    """Starts or stops the Solar & Wind Priority override, one change at a
    time."""

    def __init__(
        self,
        confirm_timeout: float = CONFIRM_TIMEOUT,
        confirm_poll_interval: float = CONFIRM_POLL_INTERVAL,
    ) -> None:
        self._confirm_timeout = confirm_timeout
        self._confirm_poll_interval = confirm_poll_interval
        self._busy = asyncio.Lock()

    async def start(self, transport: Transport) -> bool:
        """Starts the override. Returns False without writing if it is
        already running, True once the device reports it running."""
        return await self._set(transport, True)

    async def stop(self, transport: Transport) -> bool:
        """Stops a running override. Returns False without writing if none is
        running, True once the device reports it stopped."""
        return await self._set(transport, False)

    async def _set(self, transport: Transport, active: bool) -> bool:
        if self._busy.locked():
            raise PriorityOverrideError(
                "A charge to 100% change is already in progress"
            )
        async with self._busy:
            if not await self._needed(transport, active):
                return False
            async with transport.long_frame_session():
                value = await self._check_device(transport)
                await self._write(transport, override_write(value, active))
            await self._confirm(transport, active)
            return True

    async def _needed(self, transport: Transport, active: bool) -> bool:
        """Whether a write is needed; raises if one may not be sent."""
        enabled = await transport.priority_enabled()
        if enabled is None:
            raise PriorityOverrideError(
                "Could not read the Solar & Wind Priority setting"
            )
        if not enabled:
            if not active:
                return False
            raise PriorityOverrideError("Solar & Wind Priority is not enabled")

        state = await transport.priority_state()
        if state not in (
            PRIORITY_STATE_OVERRIDDEN,
            PRIORITY_STATE_ACTIVE,
            PRIORITY_STATE_AC_OR_GENERATOR,
        ):
            raise PriorityOverrideError("Could not read the charge to 100% state")
        if state == PRIORITY_STATE_AC_OR_GENERATOR:
            if not active:
                return False
            raise PriorityOverrideError(
                "Already charging to 100% because AC input 1 is connected or a "
                "generator is running"
            )
        if (state == PRIORITY_STATE_OVERRIDDEN) == active:
            _LOGGER.info(
                "Charge to 100%% is already %s; nothing written",
                "running" if active else "stopped",
            )
            return False
        return True

    @staticmethod
    async def _check_device(transport: Transport) -> int:
        """Checks the device supports the override and returns the value of
        setting 60 to write back. Raises if any check fails."""
        version = await transport.read_software_version()
        if version is None:
            raise PriorityOverrideError("Could not read the firmware version")
        if not version.long_form:
            raise PriorityOverrideError(
                "The interface did not switch to long frames, so nothing was written"
            )
        if not firmware_supported(version.version):
            raise PriorityOverrideError(
                f"Firmware {version.version} is older than 506, where Solar & Wind "
                "Priority does not charge to 100% only once"
            )

        maximum = await transport.read_setting_maximum(PRIORITY_SETTING)
        if maximum is None:
            raise PriorityOverrideError(
                f"Could not read setting {PRIORITY_SETTING} info"
            )
        if not maximum & PRIORITY_ENABLED_BIT:
            raise PriorityOverrideError(
                "Solar & Wind Priority is not supported by this device"
            )

        value = await transport.read_setting(PRIORITY_SETTING)
        if value is None:
            raise PriorityOverrideError(f"Could not read setting {PRIORITY_SETTING}")
        if not value & PRIORITY_ENABLED_BIT:
            raise PriorityOverrideError("Solar & Wind Priority is not enabled")
        return value

    @staticmethod
    async def _write(transport: Transport, payload: bytes) -> None:
        _LOGGER.info("Charge to 100%%: writing %s", payload.hex())
        reply = await transport.write(payload)
        if reply is None:
            raise PriorityOverrideError("No reply to the charge to 100% write")
        if len(reply) < 3 or reply[2] != WRITE_SETTING_OK:
            raise PriorityOverrideError(
                f"Device did not accept the charge to 100% write (reply {bytes(reply).hex()})"
            )

    async def _confirm(self, transport: Transport, active: bool) -> None:
        deadline = time.monotonic() + self._confirm_timeout
        while True:
            state = await transport.priority_state()
            if state is not None and (state == PRIORITY_STATE_OVERRIDDEN) == active:
                return
            if time.monotonic() >= deadline:
                raise PriorityOverrideError(
                    "Device accepted the write but does not report charge to 100% "
                    + ("running" if active else "stopped")
                )
            await asyncio.sleep(self._confirm_poll_interval)
