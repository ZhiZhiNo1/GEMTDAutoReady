"""Platform-independent regression tests for the Windows lifecycle seams."""
import ast
import logging
from pathlib import Path
import threading
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def load_definitions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text())
    tree.body = [node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    exec(compile(tree, path, 'exec'), namespace)
    return namespace


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.home = self.desktop('home')
        self.user_empty = self.desktop('user-empty')
        self.created = []
        self.all = [self.home, self.user_empty]

        def create():
            desktop = self.desktop('owned-' + str(len(self.created)))
            self.created.append(desktop)
            self.all.append(desktop)
            return desktop

        virtual = types.SimpleNamespace(current=lambda: self.home, create=create)
        cleanup_ns = load_definitions('utils/delete_empty_desktops.py',
                                     {'delete_empty_desktops'}, {
                                         'VirtualDesktop': virtual,
                                         'get_virtual_desktops': lambda: self.all})
        self.cleanup = cleanup_ns['delete_empty_desktops']
        self.view = Mock()
        self.view.is_app_pinned.return_value = False
        self.view.desktop = self.home
        self.view.is_pinned.return_value = True
        self.gui = Mock()
        self.gui.GetWindowLong.return_value = 0
        self.gui.IsWindow.return_value = True
        self.gui.GetWindowPlacement.return_value = ('placement',)
        self.process = Mock()
        self.process.GetWindowThreadProcessId.return_value = (12, 34)
        self.ns = load_definitions('scripts/main_multi_desktops.py',
                                  {'DesktopCoordinator', 'WindowInfo'}, {
            'threading': threading, 'VirtualDesktop': virtual,
            'AppView': Mock(return_value=self.view), 'pythoncom': Mock(),
            'win32gui': self.gui, 'win32process': self.process,
            'win32con': types.SimpleNamespace(GWL_EXSTYLE=-20, WS_EX_TOPMOST=8,
                HWND_TOPMOST=-1, HWND_NOTOPMOST=-2, SWP_NOMOVE=2,
                SWP_NOSIZE=1, SWP_NOACTIVATE=16),
            'automation': types.SimpleNamespace(logger=logging.getLogger('test')),
            'delete_empty_desktops': self.cleanup,
        })
        self.coordinator = self.ns['DesktopCoordinator']()

    @staticmethod
    def desktop(identifier):
        desktop = Mock()
        desktop.id = identifier
        desktop.apps_by_z_order.return_value = []
        return desktop

    def assign(self, hwnd=123):
        return self.coordinator._find('dota', lambda: [dict(
            hwnd=hwnd, title='Dota', exe='dota.exe', left=0, top=0, width=10, height=10)])

    def test_restores_origin_pin_and_placement_before_deleting_owned(self):
        self.assign()
        self.coordinator.close()
        self.assertEqual(self.view.move.call_args.args, (self.home,))
        self.view.pin.assert_called_once()
        self.gui.SetWindowPlacement.assert_called_once_with(123, ('placement',))
        self.user_empty.remove.assert_not_called()
        for desktop in self.created:
            desktop.remove.assert_called_once_with(fallback=self.home)
        self.assertIsNone(self.assign())

    def test_cleanup_without_ownership_is_noop(self):
        self.cleanup()
        for desktop in self.all:
            desktop.remove.assert_not_called()

    def test_nonempty_owned_desktop_is_retained(self):
        self.created[0].apps_by_z_order.return_value = [object()]
        self.coordinator.close()
        self.created[0].remove.assert_not_called()
        self.user_empty.remove.assert_not_called()

    def test_partial_initialization_rolls_back(self):
        virtual = self.ns['VirtualDesktop']
        first = self.desktop('first')
        self.all.append(first)
        virtual.create = Mock(side_effect=[first, RuntimeError('create failed')])
        with self.assertRaisesRegex(RuntimeError, 'create failed'):
            self.ns['DesktopCoordinator']()
        first.remove.assert_called_once()
        self.user_empty.remove.assert_not_called()

    def test_failed_move_still_has_rollback_record(self):
        self.view.move.side_effect = [RuntimeError('move'), None]
        with self.assertRaises(RuntimeError):
            self.assign()
        self.coordinator.close()
        self.view.pin.assert_called_once()
        self.assertFalse(self.coordinator._original_windows)

    def test_restore_failure_retains_desktops_and_other_windows_continue(self):
        self.assign(123)
        self.assign(124)
        self.view.move.side_effect = [RuntimeError('restore'), None]
        with self.assertLogs('test', level='ERROR'):
            self.coordinator.close()
        self.assertEqual(len(self.coordinator._original_windows), 1)
        for desktop in self.created:
            desktop.remove.assert_not_called()
        self.view.move.side_effect = None
        self.coordinator.close()
        self.assertFalse(self.coordinator._original_windows)

    def test_reused_handle_is_not_moved(self):
        self.assign()
        self.view.move.reset_mock()
        self.process.GetWindowThreadProcessId.return_value = (99, 100)
        self.coordinator.close()
        self.view.move.assert_not_called()

    def test_repeated_discovery_preserves_first_origin(self):
        self.assign()
        self.view.desktop = self.created[0]
        self.assign()
        self.coordinator.close()
        self.assertEqual(self.view.move.call_args.args, (self.home,))

    def test_app_pinning_is_left_untouched(self):
        self.view.is_app_pinned.return_value = True
        with self.assertRaises(RuntimeError):
            self.assign()
        self.view.unpin.assert_not_called()
        self.view.move.assert_not_called()

    def test_stopped_coordinator_rejects_late_capture(self):
        window = self.assign()
        self.coordinator.close()
        self.ns['time'] = Mock()
        capture = Mock()
        with self.assertRaises(RuntimeError):
            self.coordinator.capture(window, capture)
        capture.assert_not_called()

    def test_main_shutdown_for_normal_error_and_keyboard_interrupt(self):
        for error in (None, RuntimeError('monitor'), KeyboardInterrupt()):
            with self.subTest(error=error):
                coordinator = Mock()
                automation = Mock()
                ns = load_definitions('scripts/main_multi_desktops.py', {'main'}, {
                    'automation': automation,
                    'DesktopCoordinator': Mock(return_value=coordinator),
                    'threading': threading,
                    'atexit': Mock(),
                    'install_virtual_desktop_layer': Mock(),
                    'watch_force_stop': lambda event: None,
                    'run_monitors': Mock(side_effect=error),
                })
                if error:
                    with self.assertRaises(type(error)):
                        ns['main']()
                else:
                    ns['main']()
                coordinator.close.assert_called_once()
                # The console-close callback and atexit share this same path.
                callback = automation.register_console_close_handler.call_args.args[0]
                callback()
                self.assertEqual(coordinator.close.call_count, 2)

    def test_ctrl_f1_sets_shared_stop_event(self):
        event = threading.Event()
        event.wait = Mock(return_value=False)
        user32 = Mock()
        user32.GetAsyncKeyState.return_value = 0x8000
        ns = load_definitions('scripts/main_multi_desktops.py', {'watch_force_stop'}, {
            'ctypes': types.SimpleNamespace(windll=types.SimpleNamespace(user32=user32)),
            'VK_CONTROL': 0x11, 'VK_F1': 0x70,
            'automation': Mock(),
        })
        ns['watch_force_stop'](event)
        self.assertTrue(event.is_set())

    def test_worker_exception_stops_peer_and_is_propagated(self):
        event = threading.Event()
        automation = Mock()
        automation.TEMPLATES = {}
        automation.monitor_dota_updates.side_effect = RuntimeError('worker')
        automation.monitor_xiaoheihei.side_effect = lambda event: event.wait(1)
        ns = load_definitions('scripts/main_multi_desktops.py', {'run_monitors'}, {
            'automation': automation, 'threading': threading, 'os': __import__('os'),
        })
        with self.assertRaisesRegex(RuntimeError, 'worker'):
            ns['run_monitors'](event)
        self.assertTrue(event.is_set())
        automation.monitor_dota_updates.assert_called_once_with(event)


if __name__ == '__main__':
    unittest.main()
