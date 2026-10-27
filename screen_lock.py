"""Windows lock-screen detection and a shared pause gate for UI automation."""

import ctypes
import threading
from ctypes import wintypes


WTS_SESSION_INFO_EX = 25
WTS_SESSIONSTATE_LOCK = 0
WTS_SESSIONSTATE_UNLOCK = 1
USERNAME_LENGTH = 20
DOMAIN_LENGTH = 17
WINSTATIONNAME_LENGTH = 32


class WTSInfoExLevel1(ctypes.Structure):
    _fields_ = [
        ("SessionId", wintypes.DWORD),
        ("SessionState", ctypes.c_int),
        ("SessionFlags", wintypes.LONG),
        ("WinStationName", wintypes.WCHAR * (WINSTATIONNAME_LENGTH + 1)),
        ("UserName", wintypes.WCHAR * (USERNAME_LENGTH + 1)),
        ("DomainName", wintypes.WCHAR * (DOMAIN_LENGTH + 1)),
        ("LogonTime", ctypes.c_longlong),
        ("ConnectTime", ctypes.c_longlong),
        ("DisconnectTime", ctypes.c_longlong),
        ("LastInputTime", ctypes.c_longlong),
        ("CurrentTime", ctypes.c_longlong),
        ("IncomingBytes", wintypes.DWORD),
        ("OutgoingBytes", wintypes.DWORD),
        ("IncomingFrames", wintypes.DWORD),
        ("OutgoingFrames", wintypes.DWORD),
        ("IncomingCompressedBytes", wintypes.DWORD),
        ("OutgoingCompressedBytes", wintypes.DWORD),
    ]


class WTSInfoEx(ctypes.Structure):
    _fields_ = [
        ("Level", wintypes.DWORD),
        ("Data", WTSInfoExLevel1),
    ]


def is_screen_locked():
    """Return the lock state of the Windows session running this process."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
    session_id = wintypes.DWORD()
    buffer = ctypes.c_void_p()
    byte_count = wintypes.DWORD()

    kernel32.GetCurrentProcessId.restype = wintypes.DWORD
    kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
    wtsapi32.WTSQuerySessionInformationW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    wtsapi32.WTSQuerySessionInformationW.restype = wintypes.BOOL
    wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]

    process_id = kernel32.GetCurrentProcessId()
    if not kernel32.ProcessIdToSessionId(process_id, ctypes.byref(session_id)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not wtsapi32.WTSQuerySessionInformationW(
        None,
        session_id,
        WTS_SESSION_INFO_EX,
        ctypes.byref(buffer),
        ctypes.byref(byte_count),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if byte_count.value < ctypes.sizeof(WTSInfoEx):
            raise RuntimeError("WTS session information was shorter than expected")
        info = ctypes.cast(buffer, ctypes.POINTER(WTSInfoEx)).contents
        if info.Level != 1:
            raise RuntimeError(f"unsupported WTS session information level: {info.Level}")
        if info.Data.SessionFlags == WTS_SESSIONSTATE_LOCK:
            return True
        if info.Data.SessionFlags == WTS_SESSIONSTATE_UNLOCK:
            return False
        raise RuntimeError(f"unknown WTS session flags: {info.Data.SessionFlags}")
    finally:
        wtsapi32.WTSFreeMemory(buffer)


class ScreenLockGate:
    """Pause cooperating monitor loops while the Windows session is locked."""

    def __init__(self, logger, check_interval=2.0, checker=is_screen_locked):
        self.logger = logger
        self.check_interval = check_interval
        self.checker = checker
        self._state_lock = threading.Lock()
        self._locked = False

    def _check_locked(self):
        try:
            locked = bool(self.checker())
        except Exception:
            locked = True
            self.logger.exception("检测 Windows 锁屏状态失败；为避免误操作，暂时停止自动化。")

        with self._state_lock:
            previous = self._locked
            self._locked = locked

        if locked and not previous:
            self.logger.info("检测到 Windows 已锁屏，暂停截图、窗口切换和点击操作。")
        elif previous and not locked:
            self.logger.info("检测到 Windows 已解锁，恢复自动化监控。")
        return locked

    def wait_until_unlocked(self, stop_event):
        """Wait interruptibly until unlocked; report whether a pause occurred."""
        paused = False
        while not stop_event.is_set() and self._check_locked():
            paused = True
            if stop_event.wait(self.check_interval):
                break
        return paused and not stop_event.is_set()
