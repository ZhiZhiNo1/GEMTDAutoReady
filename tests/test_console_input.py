"""Console input policy without touching a real console or game window."""
import ast
import ctypes
import unittest
from ctypes import wintypes
from pathlib import Path
from unittest.mock import Mock


class ConsoleInputTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'main.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        self.ns = dict(ctypes=ctypes, wintypes=wintypes)
        for name in ('disable_console_quick_edit', 'setup_logging'):
            node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), self.ns)
        self.api = Mock()
        self.api.GetStdHandle.return_value = 123
        self.api.SetConsoleMode.return_value = 1

    def test_quick_edit_is_disabled_and_other_flags_are_preserved(self):
        for initial in (0x0047, 0x01f7):
            with self.subTest(initial=initial):
                def read_mode(handle, pointer):
                    pointer._obj.value = initial
                    return 1
                self.api.GetConsoleMode.side_effect = read_mode
                self.assertTrue(self.ns['disable_console_quick_edit'](self.api))
                handle, updated = self.api.SetConsoleMode.call_args.args
                self.assertEqual(handle, 123)
                self.assertFalse(updated & 0x0040)
                self.assertTrue(updated & 0x0080)
                self.assertEqual(updated & ~0x00c0, initial & ~0x00c0)
                self.assertTrue(updated & 0x0001)  # ENABLE_PROCESSED_INPUT: Ctrl+C

    def test_missing_console_does_not_change_mode(self):
        for handle in (None, 0, ctypes.c_void_p(-1).value):
            self.api.GetStdHandle.return_value = handle
            self.assertFalse(self.ns['disable_console_quick_edit'](self.api))
        self.api.GetConsoleMode.assert_not_called()
        self.api.SetConsoleMode.assert_not_called()

    def test_redirected_input_does_not_change_mode(self):
        self.api.GetConsoleMode.return_value = 0
        self.assertFalse(self.ns['disable_console_quick_edit'](self.api))
        self.api.SetConsoleMode.assert_not_called()

    def test_console_api_failure_does_not_crash_startup(self):
        self.api.GetStdHandle.side_effect = OSError('console unavailable')
        self.assertFalse(self.ns['disable_console_quick_edit'](self.api))

    def test_console_mode_is_set_before_any_logging_even_on_reinitialization(self):
        disable = Mock()
        logger = Mock(handlers=[object()])
        self.ns.update(disable_console_quick_edit=disable, logger=logger)
        self.assertIs(self.ns['setup_logging'](), logger)
        disable.assert_called_once_with()
        logger.info.assert_not_called()


if __name__ == '__main__':
    unittest.main()
