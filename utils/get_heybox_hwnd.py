import psutil
import win32gui
import win32process

HEYBOX_TITLES = ("游戏",)
HEYBOX_PROCESS = "小黑盒.exe"

def get_heybox_hwnd():
    matches = []

    def enum_windows_callback(hwnd, windows):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True

            if win32gui.IsIconic(hwnd):
                return True

            window_title = win32gui.GetWindowText(hwnd)
            if all(title not in window_title for title in HEYBOX_TITLES):
                return True

            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            process = psutil.Process(pid)
            exe_path = process.exe()
            if process.name().lower() != HEYBOX_PROCESS.lower():
                return True

            rect = win32gui.GetWindowRect(hwnd)
            left, top, right, bottom = rect
            width, height = right - left, bottom - top
            if width < 500 or height < 350:
                return True
        except (psutil.Error, OSError, win32gui.error):
            return True

        windows.append({
            "hwnd": hwnd,
            "title": window_title,
            "exe": exe_path,
            "left": left,
            "top": top,
            "width": width,
            "height": height,
        })
        return True

    win32gui.EnumWindows(enum_windows_callback, matches)
    return matches
