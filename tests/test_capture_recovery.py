import logging
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capture_recovery import CaptureRecovery, CaptureUnavailable


class CaptureRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.logger = Mock(spec=logging.Logger)
        self.gate = CaptureRecovery(self.logger, lambda: {"input_desktop": "Default"})

    def good(self, source):
        return self.gate.capture(source, lambda: "frame", (OSError,), {})

    def bad(self, source):
        def fail():
            raise OSError("BitBlt denied")
        with self.assertRaises(CaptureUnavailable):
            self.gate.capture(source, fail, (OSError,), {})

    def test_both_channels_must_recover(self):
        self.good("dota")
        self.bad("dota")
        self.bad("xhb")
        with self.assertRaises(CaptureUnavailable):
            self.good("dota")
        with self.assertRaises(CaptureUnavailable):
            with self.gate.action():
                self.fail("must not click")
        self.good("xhb")
        with self.gate.action():
            pass
        self.logger.info.assert_called_once()

    def test_old_frame_in_other_thread_cannot_click_after_recovery(self):
        self.good("dota")
        def other_monitor():
            self.bad("xhb")
            self.good("xhb")
        worker = threading.Thread(target=other_monitor)
        worker.start()
        worker.join()
        with self.assertRaises(CaptureUnavailable):
            with self.gate.action():
                self.fail("stale frame")
        self.good("dota")
        with self.gate.action():
            pass

    def test_log_throttling_and_diagnostics_failure(self):
        self.gate.diagnostics = Mock(side_effect=OSError("access denied"))
        with patch("capture_recovery.time.monotonic", return_value=100):
            self.bad("dota")
            self.bad("dota")
        self.logger.warning.assert_called_once()
        with patch("capture_recovery.time.monotonic", return_value=161):
            self.bad("dota")
        self.assertEqual(self.logger.warning.call_count, 2)
        self.good("dota")
        self.logger.info.assert_called_once()

    def test_closed_failed_window_does_not_block_other_monitor(self):
        self.bad("xhb")
        self.gate.window_missing("xhb")
        with self.assertRaises(CaptureUnavailable):
            with self.gate.action():
                self.fail("need a fresh recovery frame")
        self.good("dota")
        with self.gate.action():
            pass


if __name__ == "__main__":
    unittest.main()
