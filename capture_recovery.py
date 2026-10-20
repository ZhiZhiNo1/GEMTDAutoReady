"""Shared screenshot recovery gate and best-effort Windows diagnostics."""
import os
import threading
import time
from contextlib import contextmanager


class CaptureUnavailable(RuntimeError):
    """Skip this monitoring round while screenshots are unavailable or stale."""


def desktop_session_state():
    import win32api
    import win32con
    import win32service
    import win32ts

    state = {}

    def read(name, func):
        try:
            state[name] = func()
        except Exception as exc:
            state[name] = f"unavailable: {exc}"

    def input_desktop():
        desktop = win32service.OpenInputDesktop(0, False, win32con.DESKTOP_READOBJECTS)
        try:
            return win32service.GetUserObjectInformation(desktop, win32con.UOI_NAME)
        finally:
            desktop.CloseDesktop()

    read("input_desktop", input_desktop)
    # GetThreadDesktop returns a borrowed handle: do not close it.
    read("thread_desktop", lambda: win32service.GetUserObjectInformation(
        win32service.GetThreadDesktop(win32api.GetCurrentThreadId()), win32con.UOI_NAME))
    read("window_station", lambda: win32service.GetUserObjectInformation(
        win32service.GetProcessWindowStation(), win32con.UOI_NAME))
    read("process_session", lambda: win32ts.ProcessIdToSessionId(os.getpid()))
    read("console_session", win32ts.WTSGetActiveConsoleSessionId)
    for name, info in (("connection_state", win32ts.WTSConnectState),
                       ("session_station", win32ts.WTSWinStationName),
                       ("protocol", win32ts.WTSClientProtocolType)):
        read(name, lambda info=info: win32ts.WTSQuerySessionInformation(
            win32ts.WTS_CURRENT_SERVER_HANDLE, state.get("process_session", -1), info))
    read("virtual_screen", lambda: tuple(win32api.GetSystemMetrics(n) for n in (76, 77, 78, 79)))
    state["connection_state_legend"] = "0=Active,4=Disconnected"
    state["protocol_legend"] = "0=Console,2=RDP"
    return state


class CaptureRecovery:
    def __init__(self, logger, diagnostics=desktop_session_state):
        self.logger = logger
        self.diagnostics = diagnostics
        self.lock = threading.RLock()
        self.failed = set()
        self.started = None
        self.last_log = None
        self.generation = 0
        self.local = threading.local()

    def state(self):
        try:
            return self.diagnostics()
        except Exception as exc:
            return {"diagnostics_error": str(exc)}

    def capture(self, source, operation, errors, context):
        # Serialize capture and clicks so a known failure cannot race a click.
        with self.lock:
            try:
                screen = operation()
            except errors as exc:
                now = time.monotonic()
                if self.started is None:
                    self.started = now
                self.failed.add(source)
                self.generation += 1
                if self.last_log is None or now - self.last_log >= 60:
                    self.last_log = now
                    self.logger.warning(
                        "截图失败，暂停识别和点击，自动重试；通道=%s 区域=%s 错误=%s details=%s 桌面/会话=%s",
                        source, context, exc, getattr(exc, "details", None), self.state())
                raise CaptureUnavailable(str(exc)) from exc
            self.failed.discard(source)
            if self.failed:
                raise CaptureUnavailable("等待其他截图通道恢复")
            if self.started is not None:
                self.logger.info("截图恢复，继续识别和点击；暂停 %.1f 秒；桌面/会话=%s",
                                 time.monotonic() - self.started, self.state())
                self.started = self.last_log = None
            self.local.generation = self.generation
            return screen

    @contextmanager
    def action(self):
        with self.lock:
            if self.started is not None or getattr(self.local, "generation", None) != self.generation:
                raise CaptureUnavailable("截图不可用或截图已失效，跳过操作")
            yield

    def window_missing(self, source):
        # A closed/minimized window cannot provide a recovery frame. Let the
        # remaining visible channel prove recovery on its next successful grab.
        with self.lock:
            self.failed.discard(source)
