"""Tests for the browser-tab watchdog that powers app auto-shutdown."""

import threading
import unittest

from services.session_watchdog import SessionWatchdog


class FakeTimer:
    def __init__(self, interval: float, function) -> None:
        self.interval = interval
        self.function = function
        self.cancelled = False
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    instances: list["FakeTimer"] = []


class SessionWatchdogTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeTimer.instances = []

    def test_disconnect_schedules_shutdown_and_connect_cancels_it(self) -> None:
        expired: list[str] = []
        watchdog = SessionWatchdog(
            grace_seconds=30, timer_factory=FakeTimer, on_expire=lambda: expired.append("x")
        )
        self.assertEqual(watchdog.sessions, 0)
        self.assertFalse(watchdog.shutdown_pending)

        watchdog.disconnect()
        self.assertEqual(watchdog.sessions, 0)
        self.assertTrue(watchdog.shutdown_pending)
        self.assertEqual(FakeTimer.instances[0].interval, 30)

        watchdog.connect()
        self.assertEqual(watchdog.sessions, 1)
        self.assertFalse(watchdog.shutdown_pending)
        self.assertTrue(FakeTimer.instances[0].cancelled)

    def test_disconnect_count_never_goes_negative_and_fires_once(self) -> None:
        calls: list[int] = []
        watchdog = SessionWatchdog(
            grace_seconds=5, timer_factory=FakeTimer, on_expire=lambda: calls.append(1)
        )
        watchdog.disconnect()
        watchdog.disconnect()  # duplicate browser unload events
        self.assertEqual(watchdog.sessions, 0)
        self.assertEqual(len(FakeTimer.instances), 1)

        watchdog._expire()
        self.assertEqual(calls, [1])
        self.assertFalse(watchdog.shutdown_pending)

    def test_two_tabs_require_two_disconnects(self) -> None:
        watchdog = SessionWatchdog(grace_seconds=5, timer_factory=FakeTimer)
        watchdog.connect()
        watchdog.connect()
        watchdog.disconnect()
        self.assertFalse(watchdog.shutdown_pending)
        watchdog.disconnect()
        self.assertTrue(watchdog.shutdown_pending)

    def test_real_timer_factory_is_compatible(self) -> None:
        started = threading.Event()
        watchdog = SessionWatchdog(
            grace_seconds=5, timer_factory=threading.Timer, on_expire=started.set
        )
        watchdog.disconnect()
        watchdog._expire()
        self.assertTrue(started.wait(timeout=1))


if __name__ == "__main__":
    unittest.main()
