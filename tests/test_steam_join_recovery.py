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
from steam_join_recovery import JoinRecovery, recognize, SteamJoinMonitor, is_game_info_title, renderer_target


class SteamJoinTests(unittest.TestCase):
    def test_supplied_screenshots(self):
        for name, expected in [('steam_join_error', 'error'), ('steam_join_info', 'join'), ('steam_join_info_other_map', 'join')]:
            image = cv2.imread(str(ROOT / 'tests/fixtures' / (name + '.png')))
            for scale in (1, 1.25, 1.5):
                with self.subTest(name=name, scale=scale):
                    result, center = recognize(cv2.resize(image, None, fx=scale, fy=scale), ROOT / 'templates/steam_join')
                    self.assertEqual(result, expected)
                    self.assertIsNotNone(center)
                    point = (386, 401) if expected == 'error' else (225, 658)
                    self.assertAlmostEqual(center[0], point[0] * scale, delta=3)
                    self.assertAlmostEqual(center[1], point[1] * scale, delta=3)

    def test_join_requires_dota_identity(self):
        image = cv2.imread(str(ROOT / 'tests/fixtures/steam_join_info.png'))
        for left, top, right, bottom in ((510, 65, 570, 96),):
            changed = image.copy()
            changed[top:bottom, left:right] = 0
            if top == 65:
                changed[110:150, 500:580] = 0  # The name row also says Dota 2.
            self.assertEqual(recognize(changed, ROOT / 'templates/steam_join'), (None, None))

    def test_map_name_is_not_a_join_requirement(self):
        image = cv2.imread(str(ROOT / 'tests/fixtures/steam_join_info.png'))
        image[240:275,460:570] = 0
        self.assertEqual(recognize(image, ROOT / 'templates/steam_join')[0], 'join')

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

    def test_covered_target_does_not_advance_state(self):
        self.click.return_value = False
        self.run_frame([('error', (2, 3)), ('error', (2, 3))])
        self.assertEqual(self.monitor.recovery.windows, {})

    def test_only_game_info_titles_are_candidates(self):
        self.assertTrue(is_game_info_title('游戏信息 - hidden'))
        self.assertTrue(is_game_info_title('Game Info - hidden'))
        self.assertFalse(is_game_info_title('Steam'))
        self.assertFalse(is_game_info_title('Friends List'))

    def test_resolves_input_to_renderer_not_parent(self):
        gui=Mock()
        gui.WindowFromPoint.return_value=101
        gui.GetAncestor.return_value=7
        gui.GetClassName.return_value='Chrome_RenderWidgetHostHWND'
        gui.ScreenToClient.return_value=(225,658)
        self.assertEqual(renderer_target(gui,SimpleNamespace(hwnd=7),(3026,970)),(101,(225,658)))
        gui.ScreenToClient.assert_called_once_with(101,(3026,970))

    def test_another_root_or_parent_window_is_not_input_target(self):
        gui=Mock()
        gui.WindowFromPoint.return_value=101
        gui.GetAncestor.return_value=8
        self.assertIsNone(renderer_target(gui,SimpleNamespace(hwnd=7),(100,200)))
        gui.GetAncestor.return_value=7
        gui.GetClassName.return_value='SDL_app'
        self.assertIsNone(renderer_target(gui,SimpleNamespace(hwnd=7),(100,200)))

    def test_stop_before_click_does_not_advance_state(self):
        self.stop.set()
        self.run_frame([('error', (2, 3)), ('error', (2, 3))])
        self.click.assert_not_called()
        self.assertEqual(self.monitor.recovery.windows, {})


if __name__ == '__main__':
    unittest.main()
