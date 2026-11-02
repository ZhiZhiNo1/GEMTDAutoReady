"""Verified Dota installation identity and HWND-bound client mouse messages."""
from pathlib import Path
import re
from steam_identity import SteamIdentity, installed_steam_root


class DotaIdentity:
    def __init__(self, roots=None, signer=None):
        if roots is None:
            steam = installed_steam_root()
            roots = [steam] if steam else []
            if steam:
                try:
                    text = (steam / 'steamapps/libraryfolders.vdf').read_text(encoding='utf-8')
                    roots += [Path(p.replace('\\\\', '\\')) for p in re.findall(r'"path"\s*"([^"]+)"', text)]
                except OSError:
                    pass
        self.paths = set()
        for root in roots:
            root = Path(root).resolve()
            try:
                manifest = (root / 'steamapps/appmanifest_570.acf').read_text(encoding='utf-8')
                match = re.search(r'"installdir"\s*"([^"]+)"', manifest)
                if match:
                    base = (root / 'steamapps/common').resolve()
                    exe = (base / match.group(1) / 'game/bin/win64/dota2.exe').resolve()
                    if exe.is_relative_to(base):
                        self.paths.add(exe)
            except OSError:
                pass
        self.signer = signer or SteamIdentity.signed

    def check(self, process):
        path = Path(process.exe()).resolve()
        if path not in self.paths or not self.signer(path):
            return None
        return process.pid, process.create_time(), str(path)


def bound_client_click(gui, window, x, y, verify, stopped=None):
    """Deliver to the verified HWND only; never send elevated global mouse input."""
    if stopped is not None and stopped.is_set():
        return False
    if not verify(window):
        raise RuntimeError('Dota identity changed before map click')
    width, height = gui.GetClientRect(window.hwnd)[2:]
    x, y = int(x), int(y)
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError('Map click outside Dota client')
    point = (y << 16) | x
    # WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP. HWND routing prevents a
    # disappearing or click-through overlay from redirecting input elsewhere.
    gui.SendMessageTimeout(window.hwnd, 0x0200, 0, point, 0x0002, 1000)
    if not verify(window) or (stopped is not None and stopped.is_set()):
        return False
    try:
        gui.SendMessageTimeout(window.hwnd, 0x0201, 1, point, 0x0002, 1000)
    finally:
        gui.SendMessageTimeout(window.hwnd, 0x0202, 0, point, 0x0002, 1000)
    return True
