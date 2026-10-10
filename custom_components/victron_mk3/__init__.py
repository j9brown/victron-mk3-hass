"""The victron_mk3 integration."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from enum import Enum
from homeassistant.components.device_automation.exceptions import DeviceNotFound
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    Platform,
    CONF_DEVICE_ID,
    CONF_MODE,
    CONF_MODEL,
    CONF_PORT,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
import logging
import math
from typing import List
from victron_mk3 import (
    ACResponse,
    ConfigResponse,
    DCResponse,
    DeviceState,
    Fault,
    Handler,
    InterfaceFlags,
    LEDResponse,
    PowerResponse,
    Response,
    SettingResponse,
    SwitchRegister,
    SwitchState,
    VersionResponse,
    VictronMK3,
    logger,
)
import voluptuous as vol

from .prioritize_wind_and_solar import (
    PRIORITY_STATE_ACTIVE,
    PRIORITY_STATE_OVERRIDDEN,
    PRIORITY_STATE_AC_OR_GENERATOR,
    PRIORITY_ENABLED_BIT,
    PRIORITY_SETTING,
    InterfaceModeError,
    PriorityOverride,
    PriorityOverrideError,
    SoftwareVersion,
    firmware_supported,
)
from .const import (
    AC_PHASES_POLLED,
    CONF_CURRENT_LIMIT,
    CONF_RESET_TO_MAX_CURRENT_LIMIT,
    CONF_SERIAL_NUMBER,
    DOMAIN,
    KEY_CONTEXT,
)

PLATFORMS: list[Platform] = ["number", "select", "sensor", "switch"]
UPDATE_INTERVAL = timedelta(seconds=2)


class Mode(Enum):
    OFF = 0
    ON = 1
    CHARGER_ONLY = 2
    INVERTER_ONLY = 3


MODE_TO_SWITCH_STATE = {
    Mode.OFF: SwitchState.OFF,
    Mode.ON: SwitchState.ON,
    Mode.CHARGER_ONLY: SwitchState.CHARGER_ONLY,
    Mode.INVERTER_ONLY: SwitchState.INVERTER_ONLY,
}


def enum_options(enum_class) -> List[str]:
    return [x.lower() for x in enum_class._member_names_]


def enum_value(e: Enum | None) -> str | None:
    return None if e is None else str(e) if e.name is None else e.name.lower()


def mode_from_value(value: str) -> Mode:
    return Mode[value.upper()]


SERVICE_NAME = "set_remote_panel_state"

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Required(CONF_MODE): vol.In(enum_options(Mode)),
        vol.Exclusive(CONF_CURRENT_LIMIT, "current_limit"): vol.Coerce(float),
        vol.Exclusive(CONF_RESET_TO_MAX_CURRENT_LIMIT, "current_limit"): cv.boolean,
    }
)


# Extended status read (Winmon 0x44, parameter 0xFF). The reply is
# FF <slot> A2 FF <valid bit count> <32-bit status word, little-endian>.
EXTENDED_STATUS_REQUEST = bytes([0x44, 0xFF])
EXTENDED_STATUS_REPLY = bytes([0xA2, 0xFF])
# Status word bit 24 is set while Solar & Wind Priority is active. With it
# clear, bit 25 or 26 set means the device is charging to 100% because AC
# input 1 is connected or a generator is running. The bits are only read when
# the reply marks at least 26 bits as valid.
PRIORITY_ACTIVE_BIT = 1 << 24
PRIORITY_AC_OR_GENERATOR_BITS = (1 << 25) | (1 << 26)
MIN_VALID_BITS = 26


def priority_state(reply: bytes | None) -> int | None:
    """The PRIORITY_STATE_ value in an extended status reply, or None if the
    reply is missing, malformed or marks too few bits as valid."""
    if (
        reply is None
        or len(reply) < 9
        or reply[2:4] != EXTENDED_STATUS_REPLY
        or reply[4] < MIN_VALID_BITS
    ):
        return None
    word = int.from_bytes(reply[5:9], "little")
    if word & PRIORITY_ACTIVE_BIT:
        return PRIORITY_STATE_ACTIVE
    if word & PRIORITY_AC_OR_GENERATOR_BITS:
        return PRIORITY_STATE_AC_OR_GENERATOR
    return PRIORITY_STATE_OVERRIDDEN


# Requests used by the Solar & Wind Priority override switch, and the replies that mean
# success.
SEND_SOFTWARE_VERSION = 0x05
SOFTWARE_VERSION_OK = 0x82
# In short-frame mode, 0x05 returns the low 16 bits of the software version
# and 0x06 the high 16 bits.
SEND_SOFTWARE_VERSION_PART1 = 0x06
SOFTWARE_VERSION_PART1_OK = 0x83
READ_SETTING = 0x31
READ_SETTING_OK = 0x86
GET_SETTING_INFO = 0x35
SETTING_INFO_OK = 0x89

# Interface frames that put the interface in long-frame (Winmon mode 2) mode
# around the Solar & Wind Priority override write, and back in short-frame
# mode after it.
# Address 0.
SET_ADDRESS_DATA = [0x01, 0x00]
# 'S' data after the three bytes copied from the 'D' reply: variant 2, flags
# 0xD0, reserved 0x3E, FlagsExt0 0x06 (bit 0 clear: long frames).
LONG_FRAME_STATE_TAIL = [0x01, 0xD0, 0x3E, 0x06]
# 'S' data for short frames: switch state and limit 0, variant 2, flags 0x90
# (bit 4: do not send the panel state), reserved 0, FlagsExt0 0x01 (bit 0
# set: short frames).
SHORT_FRAME_STATE_DATA = [0x00, 0x00, 0x00, 0x01, 0x90, 0x00, 0x01]
# A 'D' reply must be longer than this to carry the state bytes.
MIN_STATE_REPLY_LENGTH = 7


# After sending the remote panel state, the actual current limit is read every
# LIMIT_READ_INTERVAL seconds, LIMIT_READS_PER_SEND times, before the state is
# sent again. The state is sent at most STATE_SEND_ATTEMPTS times in all.
LIMIT_READ_INTERVAL = 0.5
LIMIT_READS_PER_SEND = 4
STATE_SEND_ATTEMPTS = 3


def _limit_applied(current_limit: float, config: ConfigResponse) -> bool:
    """Whether a config reply shows the device applied a current limit above
    0. Compares in tenths of an amp, the unit sent to the device. The device
    raises a limit below its minimum to the minimum when PowerAssist is
    enabled, and lowers one above its maximum to the maximum."""
    sent = min(int(current_limit * 10), 0x7FFF)
    actual = round(config.actual_current_limit * 10)
    minimum = round(config.minimum_current_limit * 10)
    maximum = round(config.maximum_current_limit * 10)
    if actual == sent:
        return True
    if sent < minimum and actual == minimum:
        return True
    return sent > maximum and actual == maximum


def _reply_word(reply: bytes | None, code: int) -> int | None:
    """The 16-bit value in a reply FF <slot> <code> <lo> <hi>, or None if there
    was no reply or it has a different code."""
    if reply is None or len(reply) < 5 or reply[2] != code:
        return None
    return reply[3] | reply[4] << 8


class Data:
    def __init__(self) -> None:
        self.ac: List[ACResponse | None] = [None] * AC_PHASES_POLLED
        self.config: ConfigResponse | None = None
        self.dc: DCResponse | None = None
        self.led: LEDResponse | None = None
        self.power: PowerResponse | None = None
        self.version: VersionResponse | None = None
        # Settings 60 (Solar & Wind Priority flags) and 88 (its charge voltage
        # x100), the PRIORITY_STATE_ value, and the device's version number.
        self.solar_wind_priority: SettingResponse | None = None
        self.sustain_voltage: SettingResponse | None = None
        self.priority_state: int | None = None
        self.device_firmware: int | None = None

    def power_assist_active(self) -> bool | None:
        if self.ac[0] is None:
            return None
        return self.ac[0].device_state == DeviceState.POWER_ASSIST

    def front_panel_mode(self) -> Mode | None:
        if self.config is None:
            return None
        reg = self.config.switch_register
        if reg & SwitchRegister.FRONT_SWITCH_UP != 0:
            return Mode.ON
        if reg & SwitchRegister.FRONT_SWITCH_DOWN != 0:
            return Mode.CHARGER_ONLY
        return Mode.OFF

    def remote_panel_mode(self) -> Mode | None:
        if self.config is None:
            return None
        reg = self.config.switch_register
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

    def actual_mode(self) -> Mode | None:
        if self.config is None:
            return None
        reg = self.config.switch_register
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


class Controller(Handler):
    def __init__(self, port: str) -> None:
        self._mk3 = VictronMK3(port)
        self._fault: Fault | None = None
        self._idle = False
        self._version: VersionResponse | None = None
        # Set once at startup by read_device_info().
        self.device_firmware: int | None = None
        self.priority_override_supported = False
        self.standby: bool | None = None
        self.ac_entities = [[] for _ in range(0, AC_PHASES_POLLED)]
        # Serializes device I/O so the periodic poll and other requests never
        # overlap. Without it, concurrent requests share the
        # driver's single response slot and get cross-matched, corrupting both.
        self._io_lock = asyncio.Lock()
        # True from sending the long-frame 'S' frame until the interface has
        # replied to the short-frame one. While True, every request first sends
        # the short-frame 'S' frame.
        self._short_frames_pending = False
        # The last current limit sent with the remote panel state, or None if
        # none has been sent or the last one was the device maximum.
        self._last_sent_current_limit: float | None = None
        # The device's maximum current limit (its hardware rating) from the
        # last valid config reply, or None if none has been read.
        self._maximum_current_limit: float | None = None
        self._priority_override = PriorityOverride()
        self._priority_override_transport = _DeviceTransport(self)

    async def start(self) -> None:
        await self._mk3.start(self)

    async def stop(self) -> None:
        await self._mk3.stop()

    def on_response(self, response: Response) -> None:
        response.log(logger, logging.DEBUG)
        self._idle = False
        # We don't need to query the version because the interface delivers it every second.
        if isinstance(response, VersionResponse):
            self._version = response

    def on_idle(self) -> None:
        logger.debug("Idle")
        self._idle = True

    def on_fault(self, fault: Fault) -> None:
        if fault == Fault.EXCEPTION:
            logger.exception("Unhandled exception in handler")
        else:
            logger.error(f"Communication fault: {fault}")
        self._fault = fault

    async def update(self) -> Data:
        if self._fault is not None:
            raise UpdateFailed(f"Communication fault: {self._fault}")
        if self._idle:
            raise UpdateFailed("Device is asleep")

        async with self._io_lock:
            await self._ensure_short_frames()
            if self.standby is not None:
                flags = InterfaceFlags.PANEL_DETECT
                if self.standby:
                    flags |= InterfaceFlags.STANDBY
                await self._mk3.send_interface_request(flags)

            data = Data()
            data.version = self._version
            data.device_firmware = self.device_firmware
            data.led = await self._mk3.send_led_request()
            data.dc = await self._mk3.send_dc_request()
            for phase in range(1, AC_PHASES_POLLED + 1):
                # It might be nice to optimize the polling based on AC_Response.ac_num_phases
                # but it seems to report an incorrect number of phases on some devices so instead
                # we only poll phases that are associated with enabled entities.
                index = phase - 1
                data.ac[index] = (
                    await self._mk3.send_ac_request(phase)
                    if any(x.enabled for x in self.ac_entities[index])
                    else None
                )
            data.power = await self._mk3.send_power_request()
            data.config = await self._mk3.send_config_request()
            self._note_current_limits(data.config)
            data.solar_wind_priority = await self._mk3.send_read_setting_request(60)
            data.sustain_voltage = await self._mk3.send_read_setting_request(88)
            data.priority_state = priority_state(
                await self._w_request_raw(EXTENDED_STATUS_REQUEST)
            )
            return data

    async def _ensure_short_frames(self) -> None:
        """Sends the short-frame 'S' frame if short-frame mode has not been
        confirmed, and fails if the interface does not reply. The caller must
        hold self._io_lock."""
        if not self._short_frames_pending:
            return
        if await self._frame_request_raw("S", SHORT_FRAME_STATE_DATA) is None:
            raise UpdateFailed("Could not put the interface in short-frame mode")
        self._short_frames_pending = False

    async def read_device_info(self) -> None:
        """Reads the VE.Bus device's version number into device_firmware, and
        whether it supports the Solar & Wind Priority override into
        priority_override_supported. Sets address 0 and sends the two
        short-frame version requests (0x05 and 0x06). Then, unless the
        firmware is older than MIN_FIRMWARE, reads setting 60's info (and the
        version, if the short-frame requests got no valid reply) in a
        long-frame session. The override is supported if the firmware is
        MIN_FIRMWARE or later and setting 60's maximum has
        PRIORITY_ENABLED_BIT."""
        version = None
        async with self._io_lock:
            await self._ensure_short_frames()
            if await self._frame_request_raw("A", SET_ADDRESS_DATA) is not None:
                low = _reply_word(
                    await self._w_request_raw(bytes([SEND_SOFTWARE_VERSION, 0, 0])),
                    SOFTWARE_VERSION_OK,
                )
                high = _reply_word(
                    await self._w_request_raw(
                        bytes([SEND_SOFTWARE_VERSION_PART1, 0, 0])
                    ),
                    SOFTWARE_VERSION_PART1_OK,
                )
                if low is not None and high is not None:
                    version = low | high << 16
        maximum = None
        if version is None or firmware_supported(version):
            transport = self._priority_override_transport
            try:
                async with transport.long_frame_session():
                    if version is None:
                        reply = await transport.read_software_version()
                        if reply is not None and reply.long_form:
                            version = reply.version
                    maximum = await transport.read_setting_maximum(PRIORITY_SETTING)
            except InterfaceModeError as e:
                logger.warning(f"Could not read the device information: {e}")
        logger.info(f"VE.Bus device version: {version}")
        self.device_firmware = version
        self.priority_override_supported = (
            firmware_supported(version)
            and maximum is not None
            and bool(maximum & PRIORITY_ENABLED_BIT)
        )

    async def set_remote_panel_state(
        self, mode: Mode, current_limit: float | None
    ) -> None:
        """Sets the remote panel mode and current limit. A current limit of
        None resets it to the device maximum. Otherwise the limit must be
        between 0 and the last maximum read from the device, or nothing is
        sent."""
        if current_limit is not None and not (
            math.isfinite(current_limit) and current_limit >= 0
        ):
            raise HomeAssistantError(f"Invalid current limit: {current_limit}")

        if current_limit is not None:
            maximum = self._maximum_current_limit
            if maximum is None:
                raise HomeAssistantError("The device maximum is not known yet")
            if current_limit > maximum:
                raise HomeAssistantError(
                    f"Current limit {current_limit} A is above the device "
                    f"maximum of {maximum} A"
                )

        async with self._io_lock:
            await self._ensure_short_frames()
            await self._send_state_and_verify(mode, current_limit)

    async def set_remote_panel_mode(self, mode: Mode) -> None:
        """Sets the remote panel mode and keeps the current limit. Reads the
        actual current limit from the device just before sending and sends it,
        or the last limit sent by set_remote_panel_state if that is lower.
        Sends nothing if the limit cannot be read. Checks the limit was
        applied, as set_remote_panel_state does."""
        if self._fault is not None:
            raise HomeAssistantError(f"Communication fault: {self._fault}")
        if self._idle:
            raise HomeAssistantError("Device is asleep")

        async with self._io_lock:
            await self._ensure_short_frames()
            current_limit = (await self._read_current_limits()).actual_current_limit
            if self._last_sent_current_limit is not None:
                current_limit = min(current_limit, self._last_sent_current_limit)
            await self._send_state_and_verify(mode, current_limit)

    async def _send_state_and_verify(
        self, mode: Mode, current_limit: float | None
    ) -> None:
        """Sends the remote panel state, then reads the actual current limit
        back. The device sometimes acknowledges the state without applying the
        limit, so the same state is sent again, up to STATE_SEND_ATTEMPTS
        times in all, until the limit is applied. Fails if it never is. A
        limit of None (the device maximum) or 0 is sent once and not checked.
        The caller must hold self._io_lock."""
        switch_state = MODE_TO_SWITCH_STATE[mode]
        await self._mk3.send_state_request(switch_state, current_limit)
        self._last_sent_current_limit = current_limit
        if current_limit is None or current_limit <= 0:
            return
        actual = None
        for attempt in range(STATE_SEND_ATTEMPTS):
            if attempt > 0:
                logger.warning(
                    f"Current limit {current_limit} A not applied (device "
                    f"reports {actual} A); sending the panel state again"
                )
                await self._mk3.send_state_request(switch_state, current_limit)
            for _ in range(LIMIT_READS_PER_SEND):
                await asyncio.sleep(LIMIT_READ_INTERVAL)
                config = await self._mk3.send_config_request()
                self._note_current_limits(config)
                if config is None:
                    continue
                if config.digital_multi_control_dedicated:
                    raise HomeAssistantError(
                        "The current limit is controlled by a Digital Multi Control"
                    )
                actual = config.actual_current_limit
                if _limit_applied(current_limit, config):
                    return
        raise HomeAssistantError(
            f"The device did not apply the current limit of {current_limit} A "
            f"(it reports {actual} A)"
        )

    async def _read_current_limits(self) -> ConfigResponse:
        """Reads the device's current limits, failing if there is no reply or
        a Digital Multi Control sets them. The caller must hold
        self._io_lock."""
        config = await self._mk3.send_config_request()
        self._note_current_limits(config)
        if config is None:
            raise HomeAssistantError("Could not read the current limit")
        # A DMC-dedicated reply's current limit bytes are not valid.
        if config.digital_multi_control_dedicated:
            raise HomeAssistantError(
                "The current limit is controlled by a Digital Multi Control"
            )
        return config

    def _note_current_limits(self, config: ConfigResponse | None) -> None:
        """Remembers the maximum current limit from a config reply. A
        DMC-dedicated reply's current limit bytes are not valid."""
        if config is not None and not config.digital_multi_control_dedicated:
            self._maximum_current_limit = config.maximum_current_limit

    async def _w_request_raw(self, payload: bytes) -> bytes | None:
        """Sends one request and returns the raw reply payload, or None if there
        was no reply. The caller must hold self._io_lock."""
        driver = self._mk3._driver
        if driver is None:
            return None

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        def _completion(handler: Handler, msg: bytes) -> None:
            if not future.done():
                future.set_result(bytes(msg))

        driver._send_w_request(list(payload), _completion)
        try:
            return await asyncio.wait_for(future, timeout=1.0)
        except asyncio.TimeoutError:
            return None

    async def _frame_request_raw(self, command: str, data: list[int]) -> bytes | None:
        """Sends one interface frame and returns the raw reply frame with the
        same command letter, or None if there was no reply. The caller must
        hold self._io_lock."""
        driver = self._mk3._driver
        if driver is None:
            return None

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        letter = ord(command)
        original = driver._handle_frame

        def _capture(handler: Handler, msg: bytes) -> None:
            if (
                not future.done()
                and len(msg) >= 2
                and msg[0] == 0xFF
                and msg[1] == letter
            ):
                future.set_result(bytes(msg))
            original(handler, msg)

        driver._handle_frame = _capture
        try:
            driver._send_frame(command, data)
            return await asyncio.wait_for(future, timeout=1.0)
        except asyncio.TimeoutError:
            return None
        finally:
            del driver._handle_frame

    async def set_prioritize_wind_and_solar_override(self, active: bool) -> bool:
        """Starts (active=True) or stops the Solar & Wind Priority override.
        Returns False if it was already in that state, in which case nothing
        was written."""
        if self._fault is not None:
            raise UpdateFailed(f"Communication fault: {self._fault}")
        if self._idle:
            raise UpdateFailed("Device is asleep")
        try:
            if active:
                return await self._priority_override.start(
                    self._priority_override_transport
                )
            return await self._priority_override.stop(self._priority_override_transport)
        except PriorityOverrideError as e:
            raise HomeAssistantError(str(e)) from e
        except Exception as e:
            logger.exception(
                "Unexpected error changing the Solar & Wind Priority override"
            )
            raise HomeAssistantError(f"Charge to 100% failed: {e}") from e


class _DeviceTransport:
    """Device access for PriorityOverride. Takes the controller's I/O lock for
    each request so the periodic poll cannot interleave with it. Offers reads
    and a single write method, so the only path to a write is the one that
    PriorityOverride guards."""

    def __init__(self, controller: Controller) -> None:
        self._controller = controller
        # True while a long-frame session holds the controller's I/O lock.
        self._in_session = False

    async def priority_enabled(self) -> bool | None:
        response = await self.read_setting(PRIORITY_SETTING)
        if response is None:
            return None
        return bool(response & PRIORITY_ENABLED_BIT)

    async def priority_state(self) -> int | None:
        return priority_state(await self._request(EXTENDED_STATUS_REQUEST))

    async def _request(self, payload: bytes) -> bytes | None:
        if self._in_session:
            return await self._controller._w_request_raw(payload)
        async with self._controller._io_lock:
            await self._controller._ensure_short_frames()
            return await self._controller._w_request_raw(payload)

    @contextlib.asynccontextmanager
    async def long_frame_session(self):
        """Sets address 0, reads the interface state with 'D', and sends 'S'
        with that state and FlagsExt0 0x06 (long frames). On exit, sends 'S'
        with FlagsExt0 0x01 (short frames), even if the body failed, retrying
        once. If that gets no reply, the next request of any kind sends it
        again before anything else. Holds the I/O lock throughout, so other
        device I/O waits."""
        controller = self._controller
        async with controller._io_lock:
            self._in_session = True
            long_sent = False
            try:
                reply = await controller._frame_request_raw("A", SET_ADDRESS_DATA)
                if reply is None:
                    raise InterfaceModeError("No reply to the set-address frame")
                state = await controller._frame_request_raw("D", [])
                if state is None or len(state) < MIN_STATE_REPLY_LENGTH:
                    raise InterfaceModeError("Could not read the interface state")
                long_sent = True
                controller._short_frames_pending = True
                reply = await controller._frame_request_raw(
                    "S", list(state[2:5]) + LONG_FRAME_STATE_TAIL
                )
                if reply is None:
                    raise InterfaceModeError("No reply to the long-frame mode frame")
                yield
            finally:
                try:
                    if long_sent:
                        for _ in range(2):
                            reply = await controller._frame_request_raw(
                                "S", SHORT_FRAME_STATE_DATA
                            )
                            if reply is not None:
                                controller._short_frames_pending = False
                                break
                        else:
                            raise InterfaceModeError(
                                "No reply to the short-frame mode frame"
                            )
                finally:
                    self._in_session = False

    async def read_setting(self, setting_id: int) -> int | None:
        reply = await self._request(bytes([READ_SETTING, setting_id, 0x00]))
        return _reply_word(reply, READ_SETTING_OK)

    async def read_setting_maximum(self, setting_id: int) -> int | None:
        """GetSettingInfo (0x35), long-form reply only: 0x89 followed by
        scale, offset, default, minimum and maximum (16-bit each) and the
        access level."""
        reply = await self._request(bytes([GET_SETTING_INFO, setting_id, 0x00]))
        if reply is None or len(reply) < 14 or reply[2] != SETTING_INFO_OK:
            return None
        return reply[11] | reply[12] << 8

    async def read_software_version(self) -> SoftwareVersion | None:
        """Software version request (0x05): reply 0x82 <lo> <hi> in the short
        form, or 0x82 followed by at least four bytes in the long form, of
        which the first three are the version."""
        reply = await self._request(bytes([SEND_SOFTWARE_VERSION]))
        if reply is None or len(reply) < 5 or reply[2] != SOFTWARE_VERSION_OK:
            return None
        if len(reply) > 6:
            return SoftwareVersion(
                int.from_bytes(reply[3:6], "little"), long_form=True
            )
        return SoftwareVersion(reply[3] | reply[4] << 8, long_form=False)

    async def write(self, payload: bytes) -> bytes | None:
        return await self._request(payload)


class Context:
    def __init__(
        self,
        controller: Controller,
        coordinator: DataUpdateCoordinator[Data],
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        self.controller = controller
        self.coordinator = coordinator
        self.device_id = device_id
        self.device_info = device_info


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    port = entry.data[CONF_PORT]
    controller = Controller(port)

    coordinator = DataUpdateCoordinator[Data](
        hass,
        logger,
        name=DOMAIN,
        update_interval=UPDATE_INTERVAL,
        update_method=controller.update,
    )

    device = device_registry.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        name=entry.title,
        manufacturer="Victron Energy",
        model=entry.data.get(CONF_MODEL, None),
        serial_number=entry.data.get(CONF_SERIAL_NUMBER, None),
        identifiers={(DOMAIN, port)},
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        KEY_CONTEXT: Context(
            controller, coordinator, device.id, DeviceInfo(identifiers={(DOMAIN, port)})
        )
    }

    await controller.start()
    entry.async_on_unload(controller.stop)

    await coordinator.async_config_entry_first_refresh()
    await controller.read_device_info()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await _async_setup_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def _async_setup_services(hass: HomeAssistant) -> None:
    async def _handle_set_remote_panel_state(call: ServiceCall) -> None:
        device_id = call.data[CONF_DEVICE_ID]
        mode = mode_from_value(call.data[CONF_MODE])
        current_limit = call.data.get(CONF_CURRENT_LIMIT, None)
        reset_to_max_current_limit = call.data.get(
            CONF_RESET_TO_MAX_CURRENT_LIMIT, False
        )
        await set_remote_panel_state(
            hass, device_id, mode, current_limit, reset_to_max_current_limit
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_NAME,
        _handle_set_remote_panel_state,
        schema=SERVICE_SCHEMA,
    )


async def set_remote_panel_state(
    hass: HomeAssistant,
    device_id: str,
    mode: Mode,
    current_limit: float | None,
    reset_to_max_current_limit: bool = False,
) -> None:
    """Sets the remote panel state. Unless a current limit is given or
    reset_to_max_current_limit is set, the device's actual current limit is
    kept."""
    device = device_registry.async_get(hass).async_get(device_id)
    if device is None:
        raise DeviceNotFound(f"Device ID {device_id} is not valid")

    for entry_id in device.config_entries:
        entry_data = hass.data[DOMAIN].get(entry_id, None)
        if entry_data is not None:
            context = entry_data[KEY_CONTEXT]
            if current_limit is None and not reset_to_max_current_limit:
                await context.controller.set_remote_panel_mode(mode)
            else:
                await context.controller.set_remote_panel_state(mode, current_limit)
            await context.coordinator.async_request_refresh()
            return

    raise HomeAssistantError(f"Device ID {device_id} cannot handle this request")
