"""Run the automation with Dota 2 and Heybox on isolated virtual desktops.

This module reuses the image recognition and state machines from ``main.py``,
but replaces its window coordination layer with Windows virtual desktops.
"""

import atexit
import threading
import time
import ctypes
import os
import sys
from pathlib import Path

# Allow direct execution from either the project root or the scripts directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import pythoncom
import win32con
import win32gui
import win32process
from pyvda import AppView, VirtualDesktop

import main as automation
from utils import delete_empty_desktops, get_dota_hwnd, get_heybox_hwnd


DESKTOP_SWITCH_DELAY = 0.20
VK_CONTROL = 0x11
VK_F1 = 0x70


class WindowInfo:
    """Small adapter matching the window object expected by ``main.py``."""

    def __init__(self, data):
        self.hwnd = data["hwnd"]
        self.title = data["title"]
        self.exe = data["exe"]
        self.left = data["left"]
        self.top = data["top"]
        self.width = data["width"]
        self.height = data["height"]

    def isMinimized(self):
        return bool(win32gui.IsIconic(self.hwnd))

    def restore(self):
        win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)


class DesktopCoordinator:
    """Own the two app desktops and serialize desktop-sensitive operations."""

    def __init__(self):
        self._lock = threading.RLock()
        self._home = VirtualDesktop.current()
        self._desktops = {}
        self._assigned_hwnds = {}
        self._original_windows = {}
        self._closed = False
        try:
            for app, name in (("dota", "Dota 2"), ("xhb", "Heybox")):
                desktop = VirtualDesktop.create()
                # Record ownership before rename or any other fallible operation.
                self._desktops[app] = desktop
                try:
                    desktop.rename(name)
                except (NotImplementedError, OSError):
                    automation.logger.debug("不支持虚拟桌面命名：%s", name)
        except BaseException:
            self.close()
            raise

    def _find(self, app_name, finder):
        if self._closed:
            return None
        matches = finder()
        if not matches:
            return None

        window = WindowInfo(matches[0])
        with self._lock:
            if self._closed:
                return None
            pythoncom.CoInitialize()
            try:
                identity = win32process.GetWindowThreadProcessId(window.hwnd)
                key = (window.hwnd, identity)
                window.identity = identity
                if self._assigned_hwnds.get(app_name) != key:
                    view = AppView(hwnd=window.hwnd)
                    if view.is_app_pinned():
                        raise RuntimeError("请先取消该应用的‘在所有桌面显示窗口’设置")
                    if key not in self._original_windows:
                        self._original_windows[key] = (
                            view.desktop, view.is_pinned(),
                            win32gui.GetWindowPlacement(window.hwnd),
                            bool(win32gui.GetWindowLong(window.hwnd, win32con.GWL_EXSTYLE)
                                 & win32con.WS_EX_TOPMOST),
                        )
                    if view.is_pinned():
                        view.unpin()
                    view.move(self._desktops[app_name])
                    self._assigned_hwnds[app_name] = key
                    automation.logger.info(
                        "已将 %s 窗口移动到虚拟桌面 %s。",
                        "Dota 2" if app_name == "dota" else "小黑盒",
                        self._desktops[app_name].number,
                    )
            finally:
                pythoncom.CoUninitialize()
        return window

    def find_dota(self):
        return self._find("dota", get_dota_hwnd)

    def find_heybox(self):
        return self._find("xhb", get_heybox_hwnd)

    def _app_for_window(self, window):
        identity = win32process.GetWindowThreadProcessId(window.hwnd)
        if identity != window.identity:
            raise RuntimeError("窗口身份已变化，需要重新查找窗口")
        key = (window.hwnd, identity)
        for app_name, assigned_key in self._assigned_hwnds.items():
            if assigned_key == key:
                return app_name
        raise RuntimeError("窗口尚未分配到受管虚拟桌面")

    def _activate(self, window):
        if self._closed:
            raise RuntimeError("虚拟桌面协调器已停止")
        app_name = self._app_for_window(window)
        desktop = self._desktops[app_name]
        if VirtualDesktop.current().id != desktop.id:
            desktop.go()
            time.sleep(DESKTOP_SWITCH_DELAY)
        if window.isMinimized():
            window.restore()
        automation.bring_window_to_front_original(window)

    def capture(self, window, grab_func):
        with self._lock:
            pythoncom.CoInitialize()
            try:
                self._activate(window)
                time.sleep(0.10)
                return grab_func(window)
            finally:
                try:
                    self._return_home()
                finally:
                    pythoncom.CoUninitialize()

    def click(self, window, click_func):
        with self._lock:
            pythoncom.CoInitialize()
            try:
                self._activate(window)
                click_func()
            finally:
                try:
                    self._return_home()
                finally:
                    pythoncom.CoUninitialize()

    def _return_home(self):
        if VirtualDesktop.current().id != self._home.id:
            self._home.go()
            time.sleep(DESKTOP_SWITCH_DELAY)

    def close(self):
        """Stop accepting work, restore surviving windows, then remove owned empties.

        Failed restorations retain their desktop and can be retried by atexit.
        HWND + thread/process IDs avoid moving an unrelated reused handle.
        """
        with self._lock:
            self._closed = True
            pythoncom.CoInitialize()
            try:
                for key, (desktop, pinned, placement, topmost) in list(self._original_windows.items()):
                    hwnd, identity = key
                    try:
                        if (win32gui.IsWindow(hwnd) and
                                win32process.GetWindowThreadProcessId(hwnd) == identity):
                            view = AppView(hwnd=hwnd)
                            view.move(desktop)
                            if pinned:
                                view.pin()
                            win32gui.SetWindowPlacement(hwnd, placement)
                            win32gui.SetWindowPos(
                                hwnd, win32con.HWND_TOPMOST if topmost else win32con.HWND_NOTOPMOST,
                                0, 0, 0, 0,
                                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
                            )
                        del self._original_windows[key]
                    except Exception:
                        automation.logger.exception("恢复窗口 %s 失败，保留其桌面。", hwnd)
                try:
                    self._return_home()
                except Exception:
                    automation.logger.exception("恢复启动时的虚拟桌面失败。")
                # If any restoration failed, leave all owned desktops available.
                if not self._original_windows:
                    try:
                        delete_empty_desktops(self._desktops.values(), fallback=self._home)
                    except Exception:
                        automation.logger.exception("清理本次创建的空虚拟桌面失败。")
            finally:
                pythoncom.CoUninitialize()


def install_virtual_desktop_layer(coordinator):
    """Replace only main.py's window-discovery/coordination seams."""
    automation.find_dota_window = coordinator.find_dota
    automation.find_xiaoheihei_window = coordinator.find_heybox

    def capture_window(_name, window, _other, grab_func, stop_event, _timeout):
        if stop_event.is_set():
            return None, False
        return coordinator.capture(window, grab_func), False

    automation.capture_window_on_turn = capture_window
    automation.finish_window_turn = lambda *_args, **_kwargs: None
    automation.advance_window_turn_if_needed = lambda *_args, **_kwargs: None
    automation.click_window_and_pass_turn = (
        lambda _name, window, click_func, overlapping=False:
        coordinator.click(window, click_func)
    )
    automation.click_window_on_current_turn = (
        lambda window, click_func, overlapping=False:
        coordinator.click(window, click_func)
    )


def watch_force_stop(stop_event):
    """Watch the system-wide keyboard state and stop on Ctrl+F1."""
    user32 = ctypes.windll.user32
    chord_was_down = False
    while not stop_event.wait(0.05):
        ctrl_down = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
        f1_down = bool(user32.GetAsyncKeyState(VK_F1) & 0x8000)
        chord_down = ctrl_down and f1_down
        if chord_down and not chord_was_down:
            automation.logger.warning("收到 Ctrl+F1，正在强制结束监控并清理。")
            stop_event.set()
            return
        chord_was_down = chord_down


def run_monitors(stop_event):
    """Start main.py's two monitor routines with bar.py's shared stop event."""
    automation.logger.info("Dota2 自动点击脚本启动（虚拟桌面模式）...")
    automation.logger.info(
        "运行模式：%s | 程序目录：%s",
        "打包运行(onefile)" if automation.is_frozen() else "源码运行",
        automation.get_app_dir(),
    )
    for path in automation.TEMPLATES.values():
        if not os.path.exists(path):
            automation.logger.warning("模板文件缺失：%s", path)

    errors = []

    def monitor_dota():
        try:
            automation.monitor_dota_updates(stop_event)
        except BaseException as exc:
            errors.append(exc)
            stop_event.set()

    dota_thread = threading.Thread(
        target=monitor_dota,
        name="DotaUpdateMonitor",
        daemon=False,
    )
    dota_thread.start()
    try:
        automation.monitor_xiaoheihei(stop_event)
    finally:
        automation.logger.info("正在停止监控线程...")
        stop_event.set()
        dota_thread.join(timeout=10)
        if dota_thread.is_alive():
            automation.logger.warning("Dota 更新监控线程尚未退出，程序将继续清理窗口。")
    if errors:
        raise errors[0]


def main():
    automation.setup_logging()
    automation.logger.info("虚拟桌面模式启动：Dota 2 与小黑盒将分别独占一个桌面。")
    automation.logger.info("每次操作后自动返回启动桌面；按 Ctrl+F1 可强制结束。")

    coordinator = DesktopCoordinator()
    stop_event = threading.Event()

    def shutdown():
        stop_event.set()
        coordinator.close()

    atexit.register(shutdown)
    try:
        automation.register_console_close_handler(shutdown)
        install_virtual_desktop_layer(coordinator)
        hotkey_thread = threading.Thread(
            target=watch_force_stop,
            args=(stop_event,),
            name="ForceStopHotkey",
            daemon=True,
        )
        hotkey_thread.start()
        run_monitors(stop_event)
    finally:
        shutdown()


# Keep an unpatched reference so the coordinator can use main.py's foreground logic.
automation.bring_window_to_front_original = automation.bring_window_to_front

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        automation.logger.info("收到 Ctrl+C，脚本退出。")
    except Exception:
        automation.logger.exception("虚拟桌面模式异常退出。")
        raise
