"""Run the automation with Dota 2 and Heybox on isolated virtual desktops.

This module reuses the image recognition and state machines from ``main.py``,
but replaces its window coordination layer with Windows virtual desktops.
"""

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
        self._desktops = {
            "dota": self._create_desktop("Dota 2"),
            "xhb": self._create_desktop("Heybox"),
        }
        self._assigned_hwnds = {}

    @staticmethod
    def _create_desktop(name):
        desktop = VirtualDesktop.create()
        try:
            desktop.rename(name)
        except (NotImplementedError, OSError):
            automation.logger.debug("当前 Windows 版本不支持虚拟桌面命名：%s", name)
        return desktop

    def _find(self, app_name, finder):
        matches = finder()
        if not matches:
            return None

        window = WindowInfo(matches[0])
        with self._lock:
            pythoncom.CoInitialize()
            try:
                if self._assigned_hwnds.get(app_name) != window.hwnd:
                    view = AppView(hwnd=window.hwnd)
                    if view.is_pinned():
                        view.unpin()
                    view.move(self._desktops[app_name])
                    self._assigned_hwnds[app_name] = window.hwnd
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

    def _app_for_hwnd(self, hwnd):
        for app_name, assigned_hwnd in self._assigned_hwnds.items():
            if assigned_hwnd == hwnd:
                return app_name
        raise RuntimeError("窗口尚未分配到受管虚拟桌面")

    def _activate(self, window):
        app_name = self._app_for_hwnd(window.hwnd)
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

    def restore_home(self):
        with self._lock:
            try:
                self._return_home()
            except Exception:
                automation.logger.exception("恢复启动时的虚拟桌面失败。")


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

    dota_thread = threading.Thread(
        target=automation.monitor_dota_updates,
        args=(stop_event,),
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
        automation.cleanup()


def main():
    automation.setup_logging()
    automation.register_console_close_handler()
    automation.logger.info("虚拟桌面模式启动：Dota 2 与小黑盒将分别独占一个桌面。")
    automation.logger.info("每次操作后自动返回启动桌面；按 Ctrl+F1 可强制结束。")

    coordinator = DesktopCoordinator()
    install_virtual_desktop_layer(coordinator)
    stop_event = threading.Event()
    hotkey_thread = threading.Thread(
        target=watch_force_stop,
        args=(stop_event,),
        name="ForceStopHotkey",
        daemon=True,
    )
    hotkey_thread.start()
    try:
        run_monitors(stop_event)
    finally:
        stop_event.set()
        coordinator.restore_home()
        try:
            delete_empty_desktops()
        except Exception:
            automation.logger.exception("清理空虚拟桌面失败。")


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
