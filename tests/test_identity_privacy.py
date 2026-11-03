import ast
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import cv2
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dota_identity import DotaIdentity, bound_client_click


class IdentityPrivacyTests(unittest.TestCase):
    def test_public_fixtures_mask_identifying_regions(self):
        regions = {
            'steam_join_error': [(130,15,570,55),(328,172,503,213)],
            'steam_join_info': [(130,15,570,55),(328,172,503,213)],
            'steam_join_info_other_map': [(130,15,570,55),(328,172,503,213)],
            'xhb_invite_expired': [(12,56,221,81),(12,80,65,106)],
        }
        for name, boxes in regions.items():
            image = cv2.imread(str(ROOT / 'tests/fixtures' / (name+'.png')))
            for x,y,r,b in boxes:
                self.assertEqual(image[y:b,x:r].max(), 0)

    def test_dota_requires_manifest_path_and_valid_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'steamapps').mkdir()
            (root / 'steamapps/appmanifest_570.acf').write_text('"installdir" "dota 2 beta"')
            exe = root / 'steamapps/common/dota 2 beta/game/bin/win64/dota2.exe'
            process = SimpleNamespace(exe=lambda:str(exe),pid=1,create_time=lambda:2)
            self.assertIsNotNone(DotaIdentity([root],lambda p:True).check(process))
            self.assertIsNone(DotaIdentity([root],lambda p:False).check(process))
            process.exe=lambda:str(root/'fake/dota2.exe')
            self.assertIsNone(DotaIdentity([root],lambda p:True).check(process))

    def test_map_click_only_addresses_verified_hwnd(self):
        gui = Mock()
        gui.GetClientRect.return_value=(0,0,640,480)
        win = SimpleNamespace(hwnd=7)
        self.assertTrue(bound_client_click(gui, win, 30, 40, lambda w: True))
        self.assertEqual([c.args[0] for c in gui.SendMessageTimeout.call_args_list],[7,7,7])
        gui.reset_mock()
        with self.assertRaises(RuntimeError):
            bound_client_click(gui,win,30,40,lambda w:False)
        gui.SendMessageTimeout.assert_not_called()

    def test_shared_window_input_never_moves_or_clicks_global_mouse(self):
        import window_input
        self.assertNotIn('pydirectinput', vars(window_input))
        gui = Mock(); gui.GetClientRect.return_value=(0,0,640,480)
        stop = threading.Event(); stop.set()
        self.assertFalse(window_input.bound_client_click(gui,SimpleNamespace(hwnd=9),10,20,lambda w:True,stop))
        gui.SendMessageTimeout.assert_not_called()

    def test_identity_change_after_move_never_sends_mouse_down(self):
        gui=Mock();gui.GetClientRect.return_value=(0,0,640,480)
        verify=Mock(side_effect=[True,False])
        self.assertFalse(bound_client_click(gui,SimpleNamespace(hwnd=7),30,40,verify))
        self.assertEqual([c.args[1] for c in gui.SendMessageTimeout.call_args_list],[0x200])

    def test_desktop_coordinator_uses_steam_lock(self):
        tree=ast.parse((ROOT/'scripts/main_multi_desktops.py').read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='DesktopCoordinator')
        init=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
        shared=threading.RLock()
        ns=dict(automation=SimpleNamespace(WINDOW_OPERATION_LOCK=shared),VirtualDesktop=SimpleNamespace(current=Mock()))
        exec(compile(ast.Module(body=[init],type_ignores=[]),'coordinator','exec'),ns)
        coordinator=SimpleNamespace(_create_desktop=Mock())
        ns['__init__'](coordinator)
        self.assertIs(coordinator._lock,shared)
        with shared:
            acquired=[]
            worker=threading.Thread(target=lambda:acquired.append(coordinator._lock.acquire(blocking=False)))
            worker.start();worker.join()
            self.assertEqual(acquired,[False])


if __name__=='__main__': unittest.main()
