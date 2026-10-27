"""Check polling policy without moving real windows or starting monitors."""
import ast
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


class WindowFocusTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        self.gui = Mock()
        self.gui.GetWindowLong.return_value = 8
        self.gui.GetForegroundWindow.return_value = 100
        self.con = SimpleNamespace(
            GWL_EXSTYLE=-20, WS_EX_TOPMOST=8, HWND_TOPMOST=-1,
            SWP_NOMOVE=2, SWP_NOSIZE=1, SWP_NOACTIVATE=16,
            SWP_NOOWNERZORDER=512, SW_SHOWNOACTIVATE=4,
        )
        self.ns = dict(
            win32gui=self.gui, win32con=self.con, time=Mock(), logger=Mock(),
            WINDOW_LAYER_ACCESS_WARNING_LOGGED=False,
            WindowLayerAccessDenied=PermissionError,
            WINDOW_OPERATION_CONDITION=threading.Condition(),
            windows_overlap=lambda *_: False,
        )
        for name in ("bring_window_to_front", "capture_window_on_turn"):
            node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), self.ns)
        self.win = SimpleNamespace(hwnd=42, isMinimized=Mock(return_value=False))

    def test_repeated_separate_window_capture_does_not_change_z_order(self):
        grab = Mock(return_value="frame")
        for _ in range(3):
            result = self.ns["capture_window_on_turn"](
                "dota", self.win, None, grab, threading.Event(), 1)
            self.assertEqual(result, ("frame", False))
        self.assertEqual(grab.call_count, 3)
        self.gui.SetWindowPos.assert_not_called()
        self.gui.ShowWindow.assert_not_called()

    def test_lost_topmost_is_reapplied_without_activation(self):
        self.gui.GetWindowLong.return_value = 0
        self.ns["bring_window_to_front"](self.win, force_raise=False)
        flags = self.gui.SetWindowPos.call_args.args[-1]
        self.assertTrue(flags & self.con.SWP_NOACTIVATE)
        self.assertTrue(flags & self.con.SWP_NOOWNERZORDER)

    def test_overlap_or_click_still_raises_target(self):
        self.ns["bring_window_to_front"](self.win)
        self.gui.SetWindowPos.assert_called_once()

    def test_minimized_window_restores_without_activation(self):
        self.win.isMinimized.return_value = True
        self.ns["bring_window_to_front"](self.win, force_raise=False)
        self.gui.ShowWindow.assert_called_once_with(42, self.con.SW_SHOWNOACTIVATE)
        self.gui.SetWindowPos.assert_called_once()

    def test_foreground_change_is_logged_without_forcing_focus_back(self):
        self.gui.GetForegroundWindow.side_effect = [100, 42]
        self.ns["bring_window_to_front"](self.win)
        self.ns["logger"].warning.assert_called_once()
        self.gui.SetForegroundWindow.assert_not_called()

    def test_access_denied_still_pauses_window_operation(self):
        self.gui.SetWindowPos.side_effect = OSError(5, "Access denied")
        with self.assertRaises(PermissionError):
            self.ns["bring_window_to_front"](self.win)


if __name__ == "__main__":
    unittest.main()
