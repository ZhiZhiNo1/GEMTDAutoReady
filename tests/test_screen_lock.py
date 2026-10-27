import logging
import threading
import unittest
from unittest.mock import Mock

from screen_lock import ScreenLockGate


class ImmediateStopEvent:
    def __init__(self):
        self._set = False
        self.waits = []

    def is_set(self):
        return self._set

    def wait(self, timeout):
        self.waits.append(timeout)
        return False


class ScreenLockGateTests(unittest.TestCase):
    def test_unlocked_session_does_not_wait(self):
        checker = Mock(return_value=False)
        stop_event = ImmediateStopEvent()
        gate = ScreenLockGate(logging.getLogger("test"), checker=checker)

        self.assertFalse(gate.wait_until_unlocked(stop_event))
        self.assertEqual(stop_event.waits, [])

    def test_locked_session_polls_until_unlocked(self):
        checker = Mock(side_effect=[True, True, False])
        stop_event = ImmediateStopEvent()
        gate = ScreenLockGate(logging.getLogger("test"), check_interval=2, checker=checker)

        self.assertTrue(gate.wait_until_unlocked(stop_event))
        self.assertEqual(stop_event.waits, [2, 2])

    def test_stop_event_interrupts_locked_wait(self):
        checker = Mock(return_value=True)
        stop_event = threading.Event()
        stop_event.set()
        gate = ScreenLockGate(logging.getLogger("test"), checker=checker)

        self.assertFalse(gate.wait_until_unlocked(stop_event))
        checker.assert_not_called()

    def test_detection_error_fails_closed(self):
        checker = Mock(side_effect=[RuntimeError("query failed"), False])
        stop_event = ImmediateStopEvent()
        gate = ScreenLockGate(logging.getLogger("test"), check_interval=2, checker=checker)

        self.assertTrue(gate.wait_until_unlocked(stop_event))
        self.assertEqual(stop_event.waits, [2])


if __name__ == "__main__":
    unittest.main()
