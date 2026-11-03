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


from window_input import bound_client_click
