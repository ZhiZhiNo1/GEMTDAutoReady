"""Exercise state transitions without starting monitors or moving desktop windows."""
import ast
import logging
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import dota_matching


def load_function(path, name, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


class ArcadeUpdateTests(unittest.TestCase):
    def setUp(self):
        self.stop_event = threading.Event()
        self.now = 0
        self.visible = set()
        self.ns = dict(vars(dota_matching))
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        self.ns.update(threading=threading)
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id.startswith("DOTA_ARCADE_")
                    for t in node.targets):
                exec(compile(ast.Module(body=[node], type_ignores=[]), "main.py", "exec"), self.ns)
        self.click = Mock()
        self.ns.update(
            time=types.SimpleNamespace(monotonic=lambda: self.now),
            logger=Mock(spec=logging.Logger),
            TEMPLATES={key: key for key in (
                "dota_arcade_gem_page", "dota_arcade_update", "dota_arcade_uninstall",
                "dota_arcade_install", "dota_arcade_tab", "dota_arcade_library", "dota_arcade_gem_card")},
            match_template_multiscale=lambda screen, path, *a, **k:
                ((10, 10), 1, 1) if path in self.visible else (None, 0, 1),
            click_window_on_current_turn=self.click,
        )
        self.handle = load_function(ROOT / "main.py", "handle_dota_arcade_update", self.ns)
        self.state = dict(phase="wait_update_state", started_at=0,
                          absent_update_observations=0, uninstall_missing_warned=False)
        self.ns["DOTA_ARCADE_UPDATE_ACTIVE"].set()

    def step(self):
        return self.handle(None, None, False, self.state, self.stop_event)

    def test_stop_during_matching_prevents_install(self):
        self.state['phase'] = 'uninstall_requested'
        def match(*args, **kwargs):
            self.stop_event.set()
            return (10, 10), 1, 1
        self.ns['match_template_multiscale'] = match
        self.step()
        self.click.assert_not_called()

    def test_stop_during_matching_prevents_navigation_and_uninstall(self):
        for phase in ('idle', 'navigate_arcade', 'install_requested'):
            with self.subTest(phase=phase):
                self.stop_event.clear()
                self.state.update(phase=phase, started_at=0, install_attempts=1, last_install_attempt_at=0)
                def match(*args, **kwargs):
                    self.stop_event.set()
                    return (10, 10), 1, 1
                self.ns['match_template_multiscale'] = match
                self.now = 10
                self.step()
                self.click.assert_not_called()

    def test_already_stopped_does_not_match_or_click(self):
        self.stop_event.set()
        matcher = Mock()
        self.ns['match_template_multiscale'] = matcher
        self.step()
        matcher.assert_not_called()
        self.click.assert_not_called()

    def test_current_map_requires_three_consecutive_confirmations(self):
        self.visible = {"dota_arcade_gem_page", "dota_arcade_uninstall"}
        self.step()
        self.visible.clear()
        self.step()
        self.assertEqual(self.state["absent_update_observations"], 0)
        self.visible = {"dota_arcade_gem_page", "dota_arcade_uninstall"}
        self.step(); self.step()
        self.assertEqual(self.state["phase"], "wait_update_state")
        self.step()
        self.assertEqual(self.state["phase"], "idle")
        self.assertFalse(self.ns["DOTA_ARCADE_UPDATE_ACTIVE"].is_set())

    def test_refresh_timeout_releases_request_gate(self):
        self.now = 61
        self.step()
        self.assertEqual(self.state["phase"], "idle")
        self.assertFalse(self.ns["DOTA_ARCADE_UPDATE_ACTIVE"].is_set())

    def test_update_still_enters_reinstall_flow(self):
        self.visible = {"dota_arcade_gem_page", "dota_arcade_uninstall", "dota_arcade_update"}
        self.step()
        self.assertEqual(self.state["phase"], "idle")
        self.step()
        self.assertEqual(self.state["phase"], "uninstall_requested")
        self.click.assert_called_once()

    def begin_install(self):
        self.state["phase"] = "uninstall_requested"
        self.visible = {"dota_arcade_install", "dota_arcade_gem_page"}
        self.now = 50
        self.step()
        self.assertEqual(self.state["started_at"], 50)

    def test_install_after_uninstall_requires_gem_td_page(self):
        self.state['phase'] = 'uninstall_requested'
        self.state['started_at'] = 0
        self.visible = {'dota_arcade_install'}
        self.now = 10
        self.step()
        self.click.assert_not_called()
        self.assertEqual(self.state['phase'], 'uninstall_requested')

    def test_install_retries_are_delayed_bounded_and_timeout(self):
        self.begin_install()
        self.step()
        self.assertEqual(self.click.call_count, 1)
        for self.now in (58, 66, 74):
            self.step()
        self.assertEqual(self.click.call_count, 3)
        self.now = 230
        self.step()
        self.assertEqual(self.state["phase"], "manual_intervention")
        self.ns["logger"].warning.assert_called()

    def test_no_retry_on_another_page_and_successful_install(self):
        self.begin_install()
        self.visible = {"dota_arcade_install"}
        self.now = 60
        self.step()
        self.assertEqual(self.click.call_count, 1)
        self.visible = {"dota_arcade_gem_page", "dota_arcade_uninstall"}
        for _ in range(3):
            self.step()
        self.assertEqual(self.state["phase"], "idle")
        self.assertFalse(self.ns["DOTA_ARCADE_UPDATE_ACTIVE"].is_set())


class VirtualDesktopStartupTests(unittest.TestCase):
    def test_template_variants_do_not_prevent_monitors_starting(self):
        automation = Mock()
        automation.TEMPLATES = {"single": "one.png", "variants": ("two.png", "three.png")}
        exists = Mock(side_effect=lambda path: isinstance(path, str))
        worker = Mock()
        ns = dict(automation=automation, os=types.SimpleNamespace(path=types.SimpleNamespace(exists=exists)),
                  threading=types.SimpleNamespace(Thread=Mock(return_value=worker)))
        run = load_function(ROOT / "scripts/main_multi_desktops.py", "run_monitors", ns)
        run(threading.Event())
        self.assertEqual([c.args[0] for c in exists.call_args_list], ["one.png", "two.png", "three.png"])
        worker.start.assert_called_once()
        automation.monitor_xiaoheihei.assert_called_once()


if __name__ == "__main__":
    unittest.main()
