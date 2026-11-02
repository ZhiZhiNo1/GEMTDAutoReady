import sys
from pathlib import Path
import unittest
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from steam_join_recovery import JoinRecovery, recognize, SteamJoinMonitor


class SteamJoinTests(unittest.TestCase):
    def test_supplied_screenshots(self):
        for name, expected in [('steam_join_error', 'error'), ('steam_join_info', 'join')]:
            image = cv2.imread(str(ROOT / 'tests/fixtures' / (name + '.png')))
            for scale in (1, 1.25, 1.5):
                with self.subTest(name=name, scale=scale):
                    result, center = recognize(cv2.resize(image, None, fx=scale, fy=scale), ROOT / 'templates/steam_join')
                    self.assertEqual(result, expected)
                    self.assertIsNotNone(center)
                    point = (386, 401) if expected == 'error' else (225, 658)
                    self.assertAlmostEqual(center[0], point[0] * scale, delta=3)
                    self.assertAlmostEqual(center[1], point[1] * scale, delta=3)

    def test_join_requires_dota_and_map_identity(self):
        image = cv2.imread(str(ROOT / 'tests/fixtures/steam_join_info.png'))
        for left, top, right, bottom in ((510, 65, 570, 96), (460, 240, 570, 275)):
            changed = image.copy()
            changed[top:bottom, left:right] = 0
            if top == 65:
                changed[110:150, 500:580] = 0  # The name row also says Dota 2.
            self.assertEqual(recognize(changed, ROOT / 'templates/steam_join'), (None, None))

    def test_blank_and_unrelated_error_are_ignored(self):
        image = np.zeros((700, 600, 3), dtype=np.uint8)
        self.assertEqual(recognize(image, ROOT / 'templates/steam_join'), (None, None))
        close = cv2.imread(str(ROOT / 'templates/steam_join/close.png'))
        image[385:417, 314:458] = close
        self.assertEqual(recognize(image, ROOT / 'templates/steam_join'), (None, None))

    def test_join_without_prior_error_is_ignored(self):
        self.assertIsNone(JoinRecovery().step(1, 'join', (2, 3), 0))

    def test_close_then_join_requires_same_window_and_delay(self):
        r = JoinRecovery()
        self.assertEqual(r.step(1, 'error', (2, 3), 0), ('close', (2, 3)))
        self.assertIsNone(r.step(1, 'join', (2, 3), .5))
        self.assertIsNone(r.step(2, 'join', (2, 3), 2))
        self.assertIsNone(r.step(1, 'error', (2, 3), 2))
        self.assertEqual(r.step(1, 'join', (2, 3), 3), ('join', (2, 3)))
        self.assertIsNone(r.step(1, 'error', (2, 3), 4))

    def test_timeout_does_not_click_join(self):
        r = JoinRecovery()
        r.step(1, 'error', (2, 3), 0)
        self.assertIsNone(r.step(1, 'join', (2, 3), 11))

    def test_retries_are_bounded(self):
        r = JoinRecovery()
        for now in (0, 40, 80):
            self.assertIsNotNone(r.step(1, 'error', (2, 3), now))
            self.assertIsNotNone(r.step(1, 'join', (2, 3), now + 2))
        self.assertIsNone(r.step(1, 'error', (2, 3), 120))
        r.retain(set())
        self.assertIsNotNone(r.step(1, 'error', (2, 3), 160))


class SteamClickCommitTests(unittest.TestCase):
    def setUp(self):
        self.monitor = SteamJoinMonitor('unused', Mock())
        self.window = SimpleNamespace(hwnd=1)
        self.stop = threading.Event()
        self.click = Mock()

    def run_frame(self, recognition):
        with patch('steam_join_recovery.recognize', side_effect=recognition):
            self.monitor.process_window(self.window, Mock(), self.click, self.stop)

    def test_changed_dialog_does_not_advance_state(self):
        self.run_frame([('error', (2, 3)), (None, None)])
        self.click.assert_not_called()
        self.assertEqual(self.monitor.recovery.windows, {})

    def test_failed_click_does_not_advance_state(self):
        self.click.side_effect = OSError('click failed')
        with self.assertRaises(OSError):
            self.run_frame([('error', (2, 3)), ('error', (2, 3))])
        self.assertEqual(self.monitor.recovery.windows, {})

    def test_successful_click_advances_state(self):
        self.run_frame([('error', (2, 3)), ('error', (2, 3))])
        self.click.assert_called_once_with(self.window, 2, 3)
        self.assertEqual(self.monitor.recovery.windows[1]['phase'], 'waiting')

    def test_stop_before_click_does_not_advance_state(self):
        self.stop.set()
        self.run_frame([('error', (2, 3)), ('error', (2, 3))])
        self.click.assert_not_called()
        self.assertEqual(self.monitor.recovery.windows, {})


if __name__ == '__main__':
    unittest.main()
