import ast
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
import cv2
import numpy as np
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dota_matching import arcade_content_region, match_template_multiscale, DOTA_ARCADE_TAB_SEARCH_REGION
from steam_join_recovery import SteamJoinMonitor
from steam_identity import SteamIdentity


class ReviewRegressionTests(unittest.TestCase):
    def test_arcade_template_matches_inside_4_3_black_bars(self):
        template = cv2.imread(str(ROOT / 'templates/dota_arcade_tab_unselected.png'))
        small = cv2.resize(template, (round(template.shape[1]*1024/1920), round(template.shape[0]*1024/1920)), interpolation=cv2.INTER_AREA)
        image = np.zeros((768, 1024, 3), dtype=np.uint8)
        image[105:105+small.shape[0], 550:550+small.shape[1]] = small
        center, score, _ = match_template_multiscale(image, str(ROOT / 'templates/dota_arcade_tab_unselected.png'), .84, (1,), search_region=DOTA_ARCADE_TAB_SEARCH_REGION)
        self.assertIsNotNone(center)
        self.assertGreater(center[1], 99)

    def test_non_letterboxed_layout_is_unchanged(self):
        image = np.ones((768, 1024, 3), dtype=np.uint8) * 50
        self.assertEqual(arcade_content_region(image, DOTA_ARCADE_TAB_SEARCH_REGION), DOTA_ARCADE_TAB_SEARCH_REGION)

    def test_valid_invitation_replacement_recovers_after_timeout(self):
        tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'resume_invite_monitor')
        ns = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), ns)
        resume = ns['resume_invite_monitor']
        self.assertFalse(resume((1, 2), None, 1, 3))
        self.assertTrue(resume((1, 2), None, 3, 3))
        self.assertFalse(resume((1, 2), (3, 4), 30, 3))
        self.assertTrue(resume(None, None, 0, 3))

    def test_raise_happens_before_both_captures(self):
        monitor = SteamJoinMonitor('unused', Mock())
        events = []
        prepare = lambda: events.append('raise') or True
        capture = lambda win: events.append('capture')
        click = lambda *args: events.append('click')
        with patch('steam_join_recovery.recognize', return_value=('error', (2, 3))):
            monitor.process_window(SimpleNamespace(hwnd=1), capture, click, threading.Event(), prepare)
        self.assertEqual(events, ['raise', 'capture', 'raise', 'capture', 'click'])

    def test_untrusted_window_never_captured(self):
        monitor = SteamJoinMonitor('unused', Mock())
        capture, click = Mock(), Mock()
        monitor.process_window(SimpleNamespace(hwnd=1), capture, click, threading.Event(), lambda: False)
        capture.assert_not_called()
        click.assert_not_called()

    def process(self, path, parent=None):
        return SimpleNamespace(exe=lambda: str(path), parent=lambda: parent, pid=1, create_time=lambda: 2)

    def test_unsigned_or_wrong_path_cannot_impersonate_steam(self):
        root = ROOT / 'fake-steam'
        signed = SteamIdentity(root, signer=lambda path: True)
        unsigned = SteamIdentity(root, signer=lambda path: False)
        self.assertIsNone(signed.check(self.process(ROOT / 'attacker/steam.exe')))
        self.assertIsNone(unsigned.check(self.process(root / 'steam.exe')))
        self.assertIsNotNone(signed.check(self.process(root / 'steam.exe')))

    def test_webhelper_requires_valid_steam_ancestor(self):
        root = ROOT / 'fake-steam'
        identity = SteamIdentity(root, signer=lambda path: True)
        helper = root / 'bin/cef/steamwebhelper.exe'
        self.assertIsNone(identity.check(self.process(helper)))
        steam = self.process(root / 'steam.exe')
        self.assertIsNotNone(identity.check(self.process(helper, steam)))


class TrustedVerifierTests(unittest.TestCase):
    def test_forged_environment_does_not_select_verifier_or_modules(self):
        import steam_identity
        system, windows = steam_identity.windows_system_directories()
        result = SimpleNamespace(returncode=0, stdout='OK')
        malicious = dict(SystemRoot='Z:/attacker', windir='Z:/attacker', PATH='Z:/attacker',
                         PSModulePath='Z:/attacker', COR_ENABLE_PROFILING='1',
                         COR_PROFILER_PATH='Z:/attacker/inject.dll')
        steam_identity._signed_by_valve.cache_clear()
        with patch.dict(os.environ, malicious), patch('steam_identity.subprocess.run', return_value=result) as run:
            self.assertTrue(steam_identity._signed_by_valve('unused.exe', 'test'))
        args, kwargs = run.call_args
        self.assertEqual(Path(args[0][0]), system / 'WindowsPowerShell/v1.0/powershell.exe')
        self.assertEqual(kwargs['env']['SystemRoot'], str(windows))
        self.assertEqual(kwargs['env']['PSModulePath'], str(system / 'WindowsPowerShell/v1.0/Modules'))
        self.assertNotIn('COR_PROFILER_PATH', kwargs['env'])
        self.assertNotIn('COR_ENABLE_PROFILING', kwargs['env'])

    def test_system_directory_failure_never_launches_a_process(self):
        import steam_identity
        steam_identity._signed_by_valve.cache_clear()
        with patch('steam_identity.windows_system_directories', side_effect=OSError('API unavailable')), patch('steam_identity.subprocess.run') as run:
            self.assertFalse(steam_identity._signed_by_valve('unused.exe', 'failure'))
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
