"""Fail-closed Steam executable and process-tree validation."""
from functools import lru_cache
import hashlib
import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess


def windows_system_directories(kernel32=None):
    """Resolve trusted OS paths without consulting the launch environment."""
    api = kernel32 or ctypes.WinDLL('kernel32', use_last_error=True)
    paths = []
    for name in ('GetSystemDirectoryW', 'GetWindowsDirectoryW'):
        read = getattr(api, name)
        read.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        read.restype = wintypes.UINT
        buffer = ctypes.create_unicode_buffer(32768)
        length = read(buffer, len(buffer))
        if not length or length >= len(buffer):
            raise OSError('Cannot resolve trusted Windows directory')
        paths.append(Path(buffer.value))
    return tuple(paths)


@lru_cache(maxsize=32)
def _signed_by_valve(path, digest):
    try:
        system, windows = windows_system_directories()
        powershell_home = system / 'WindowsPowerShell/v1.0'
        powershell = str(powershell_home / 'powershell.exe')
        # Do not inherit module lookup, CLR profiler/startup hooks, or PATH overrides.
        env = {
            'SystemRoot': str(windows), 'windir': str(windows),
            'PATH': str(system),
            'PSModulePath': str(powershell_home / 'Modules'),
            'GEMTD_VERIFY_EXE': path,
        }
        script = 'Import-Module Microsoft.PowerShell.Security -ErrorAction Stop; $s=Get-AuthenticodeSignature -LiteralPath $env:GEMTD_VERIFY_EXE; if ($s.Status -eq \'Valid\' -and $s.SignerCertificate.Subject -match \'(CN|O)="?Valve (Corp\\.|Corporation)"?(,|$)\') { \'OK\' }'
        result = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-Command', script],
                                env=env, capture_output=True, text=True, timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        return result.returncode == 0 and result.stdout.strip() == 'OK'
    except (AttributeError, OSError, subprocess.TimeoutExpired):
        return False



def installed_steam_root():
    import winreg
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 0,
                                winreg.KEY_READ | view) as key:
                return Path(winreg.QueryValueEx(key, 'InstallPath')[0]).resolve()
        except OSError:
            continue
    return None


class SteamIdentity:
    def __init__(self, root, signer=None):
        self.root = Path(root).resolve() if root else None
        self.signer = signer or self.signed

    @staticmethod
    def signed(path):
        with open(path, 'rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        return _signed_by_valve(str(path), digest)

    def executable(self, process, main=False):
        path = Path(process.exe()).resolve()
        if not self.root or not path.is_relative_to(self.root):
            return None
        if main:
            if path != self.root / 'steam.exe':
                return None
        elif path.name.lower() not in ('steam.exe', 'steamwebhelper.exe'):
            return None
        return path if self.signer(path) else None

    def check(self, process):
        path = self.executable(process)
        if path is None:
            return None
        if path.name.lower() == 'steamwebhelper.exe':
            ancestor = process.parent()
            for _ in range(8):
                if ancestor is None:
                    return None
                if self.executable(ancestor, main=True):
                    break
                ancestor = ancestor.parent()
            else:
                return None
        elif not self.executable(process, main=True):
            return None
        return process.pid, process.create_time(), str(path)
