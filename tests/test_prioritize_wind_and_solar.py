"""Tests for the guarded Solar & Wind Priority override. Run with:

    python3 -m unittest discover -s tests
"""

import asyncio
import contextlib
import importlib.util
from pathlib import Path
import sys
import unittest

_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "victron_mk3"
    / "prioritize_wind_and_solar.py"
)
_spec = importlib.util.spec_from_file_location("priority", _PATH)
priority = importlib.util.module_from_spec(_spec)
sys.modules["priority"] = priority
_spec.loader.exec_module(priority)

Error = priority.PriorityOverrideError
OVERRIDDEN = priority.PRIORITY_STATE_OVERRIDDEN
ACTIVE = priority.PRIORITY_STATE_ACTIVE
AC_OR_GENERATOR = priority.PRIORITY_STATE_AC_OR_GENERATOR

VERSION = priority.SoftwareVersion(2629506, long_form=True)
WRITE_OK = b"\xff\x58\x88"
START_528 = bytes.fromhex("37033c1000")
STOP_528 = bytes.fromhex("37033c1002")


class DeviceTransport:
    """Simulates the device: setting 60 keeps reading the same value, and an
    accepted write changes the reported state after `settle` state reads."""

    def __init__(
        self,
        enabled=True,
        overridden=False,
        state=None,
        setting_60=528,
        maximum=0x3FF,
        version=VERSION,
        reply=WRITE_OK,
        settle=0,
    ):
        self.enabled = enabled
        self.overridden = overridden
        # Overrides the state derived from `overridden` when set.
        self.state = state
        self.setting_60 = setting_60
        self.maximum = maximum
        self.version = version
        self.reply = reply
        self.settle = settle
        self.writes = []
        self.reads = []
        # "enter", "exit" and each write, in order.
        self.events = []
        self.session_error = None
        self.in_session = False
        self._pending = None

    @contextlib.asynccontextmanager
    async def long_frame_session(self):
        self.events.append("enter")
        if self.session_error is not None:
            self.events.append("exit")
            raise self.session_error
        self.in_session = True
        try:
            yield
        finally:
            self.in_session = False
            self.events.append("exit")

    async def priority_enabled(self):
        return self.enabled

    async def priority_state(self):
        if self._pending is not None:
            if self._pending[1] <= 0:
                self.overridden = self._pending[0]
                self._pending = None
            else:
                self._pending = (self._pending[0], self._pending[1] - 1)
        if self.state is not None:
            return self.state
        if self.overridden is None:
            return None
        return OVERRIDDEN if self.overridden else ACTIVE

    async def read_setting(self, setting_id):
        self.reads.append(("setting", setting_id, self.in_session))
        return self.setting_60 if setting_id == 60 else None

    async def read_setting_maximum(self, setting_id):
        self.reads.append(("maximum", setting_id))
        return self.maximum if setting_id == 60 else None

    async def read_software_version(self):
        self.reads.append(("version",))
        return self.version

    async def write(self, payload):
        self.writes.append(payload)
        self.events.append(("write", self.in_session))
        if self.reply == WRITE_OK:
            bit_9 = (payload[3] | payload[4] << 8) & 0x200
            self._pending = (not bit_9, self.settle)
        return self.reply


def make(confirm_timeout=1.0):
    return priority.PriorityOverride(confirm_timeout, confirm_poll_interval=0.001)


def run(coro):
    return asyncio.run(coro)


class WriteTest(unittest.TestCase):
    def test_start_from_528_clears_bit_9_ram_only(self):
        transport = DeviceTransport()
        self.assertTrue(run(make().start(transport)))
        self.assertEqual(transport.writes, [START_528])
        self.assertEqual(
            transport.reads, [("version",), ("maximum", 60), ("setting", 60, True)]
        )
        self.assertEqual(transport.events, ["enter", ("write", True), "exit"])

    def test_stop_from_528_sets_bit_9_ram_only(self):
        transport = DeviceTransport(overridden=True)
        self.assertTrue(run(make().stop(transport)))
        self.assertEqual(transport.writes, [STOP_528])

    def test_other_bits_are_kept(self):
        self.assertEqual(
            priority.override_write(0xFFFF, True), bytes.fromhex("37033cfffd")
        )
        self.assertEqual(
            priority.override_write(0xFDFF, False), bytes.fromhex("37033cffff")
        )

    def test_setting_60_read_before_every_write(self):
        transport = DeviceTransport()
        override = make()
        run(override.start(transport))
        run(override.stop(transport))
        self.assertEqual(transport.reads.count(("setting", 60, True)), 2)
        self.assertEqual(transport.writes, [START_528, STOP_528])

    def test_repeated_presses_write_once(self):
        transport = DeviceTransport()
        override = make()
        run(override.start(transport))
        for _ in range(3):
            self.assertFalse(run(override.start(transport)))
        self.assertEqual(transport.writes, [START_528])

    def test_rejected_or_missing_reply_is_not_retried(self):
        for reply in (None, b"\xff\x58\x80\x00\x00", b"\xff\x58\x9b", b"\xff\x58"):
            transport = DeviceTransport(reply=reply)
            with self.subTest(reply=reply):
                with self.assertRaises(Error):
                    run(make().start(transport))
                self.assertEqual(transport.writes, [START_528])

    def test_confirmed_after_settling(self):
        transport = DeviceTransport(settle=2)
        self.assertTrue(run(make().start(transport)))
        self.assertTrue(transport.overridden)

    def test_unconfirmed_write_is_not_retried(self):
        transport = DeviceTransport(settle=100)
        with self.assertRaises(Error):
            run(make(confirm_timeout=0.05).start(transport))
        self.assertEqual(transport.writes, [START_528])


class DeviceCheckTest(unittest.TestCase):
    def assertRefused(self, transport, message=None):
        if message is None:
            with self.assertRaises(Error):
                run(make().start(transport))
        else:
            with self.assertRaisesRegex(Error, message):
                run(make().start(transport))
        self.assertEqual(transport.writes, [])
        self.assertEqual(transport.events, ["enter", "exit"])

    def test_version_unreadable(self):
        self.assertRefused(DeviceTransport(version=None))

    def test_short_version_reply(self):
        self.assertRefused(
            DeviceTransport(version=priority.SoftwareVersion(0x1234, long_form=False))
        )

    def test_firmware_below_506(self):
        for version in (2629505, 2629412, 2629099, 2600000):
            with self.subTest(version=version):
                self.assertRefused(
                    DeviceTransport(
                        version=priority.SoftwareVersion(version, long_form=True)
                    ),
                    "older than 506",
                )

    def test_firmware_506_and_later(self):
        for version in (2629506, 2629507, 2629999):
            transport = DeviceTransport(
                version=priority.SoftwareVersion(version, long_form=True)
            )
            with self.subTest(version=version):
                self.assertTrue(run(make().start(transport)))

    def test_setting_maximum_unreadable(self):
        self.assertRefused(DeviceTransport(maximum=None))

    def test_setting_maximum_without_bit_9(self):
        self.assertRefused(
            DeviceTransport(maximum=0x1FF),
            "Solar & Wind Priority is not supported by this device",
        )

    def test_setting_60_unreadable(self):
        self.assertRefused(DeviceTransport(setting_60=None))

    def test_bit_9_clear(self):
        self.assertRefused(DeviceTransport(setting_60=16))

    def test_session_failure_writes_nothing(self):
        transport = DeviceTransport()
        transport.session_error = priority.InterfaceModeError("no reply")
        with self.assertRaises(priority.InterfaceModeError):
            run(make().start(transport))
        self.assertEqual(transport.writes, [])
        self.assertEqual(transport.reads, [])


class PreconditionTest(unittest.TestCase):
    def assertNothingSent(self, transport):
        self.assertEqual(transport.writes, [])
        self.assertEqual(transport.reads, [])
        self.assertEqual(transport.events, [])

    def test_start_while_feature_disabled_refuses(self):
        transport = DeviceTransport(enabled=False)
        with self.assertRaisesRegex(Error, "Solar & Wind Priority is not enabled"):
            run(make().start(transport))
        self.assertNothingSent(transport)

    def test_stop_while_feature_disabled_writes_nothing(self):
        transport = DeviceTransport(enabled=False)
        self.assertFalse(run(make().stop(transport)))
        self.assertNothingSent(transport)

    def test_feature_unreadable(self):
        transport = DeviceTransport(enabled=None)
        with self.assertRaises(Error):
            run(make().start(transport))
        self.assertNothingSent(transport)

    def test_state_unreadable_or_unknown(self):
        for transport in (DeviceTransport(overridden=None), DeviceTransport(state=3)):
            with self.subTest():
                with self.assertRaises(Error):
                    run(make().start(transport))
                self.assertNothingSent(transport)

    def test_start_when_already_running_writes_nothing(self):
        transport = DeviceTransport(overridden=True)
        self.assertFalse(run(make().start(transport)))
        self.assertNothingSent(transport)

    def test_stop_when_not_running_writes_nothing(self):
        transport = DeviceTransport()
        self.assertFalse(run(make().stop(transport)))
        self.assertNothingSent(transport)

    def test_start_while_ac_or_generator_charging_refuses(self):
        transport = DeviceTransport(state=AC_OR_GENERATOR)
        with self.assertRaisesRegex(Error, "AC input 1"):
            run(make().start(transport))
        self.assertNothingSent(transport)

    def test_stop_while_ac_or_generator_charging_writes_nothing(self):
        transport = DeviceTransport(state=AC_OR_GENERATOR)
        self.assertFalse(run(make().stop(transport)))
        self.assertNothingSent(transport)

    def test_stop_confirmed_when_state_becomes_ac_or_generator(self):
        transport = DeviceTransport(overridden=True)
        states = iter([OVERRIDDEN, AC_OR_GENERATOR])

        async def state():
            return next(states)

        transport.priority_state = state
        self.assertTrue(run(make().stop(transport)))
        self.assertEqual(transport.writes, [STOP_528])


class SessionTest(unittest.TestCase):
    def test_confirm_runs_after_session(self):
        transport = DeviceTransport()
        in_session = []
        original = transport.priority_state

        async def spy():
            in_session.append(transport.in_session)
            return await original()

        transport.priority_state = spy
        run(make().start(transport))
        self.assertEqual(in_session, [False, False])

    def test_concurrent_press_is_refused(self):
        transport = DeviceTransport(settle=3)
        # The real clock, so the first press yields while it confirms.
        override = priority.PriorityOverride(confirm_poll_interval=0.01)

        async def both():
            return await asyncio.gather(
                override.start(transport),
                override.start(transport),
                return_exceptions=True,
            )

        results = run(both())
        self.assertEqual(results.count(True), 1)
        self.assertEqual(sum(isinstance(r, Error) for r in results), 1)
        self.assertEqual(transport.writes, [START_528])


if __name__ == "__main__":
    unittest.main()
