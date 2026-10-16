import sys
import os
import time
import ctypes
import subprocess
import logging
import tempfile
import threading
from ctypes import wintypes
from logging.handlers import RotatingFileHandler

import cv2
import mss
import numpy as np
import psutil
import pydirectinput
import pygetwindow as gw
import win32gui
import win32process
import win32con
import atexit
from dota_matching import (
    DOTA_UPDATE_FALLBACK_SCALES,
    DOTA_UPDATE_MATCH_THRESHOLD,
    match_template_multiscale,
)

# ================= 1. 先定义资源路径函数 =================
def get_resource_path(relative_path):
    """获取资源绝对路径，兼容 PyInstaller 打包环境"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# ================= 2. 再定义配置变量 =================
TEMPLATES = {
    "update_popup": get_resource_path("templates/update_popup.png"),
    "xhb_notification_badge": get_resource_path("templates/xhb_notification_badge.png"),
    "xhb_accept_invite": get_resource_path("templates/xhb_accept_invite.png"),
    "xhb_ready": get_resource_path("templates/xhb_ready.png"),
    "xhb_cancel_ready": get_resource_path("templates/xhb_cancel_ready.png"),
}

POLL_INTERVAL = 4         # 每 3~5 秒轮询一次
CLICK_DELAY = 1           # 点击后短暂等待界面刷新，再立即识别下一步
XHB_MATCH_THRESHOLD = 0.86
XHB_MATCH_FALLBACK_SCALES = (1.0, 1.25, 1.5)
XHB_FLOW_TIMEOUT = 3        # 邀请流程中的每一步最多等待 3 秒
XHB_ACTIVE_POLL_INTERVAL = 0.5
DOTA_PROCESS = "dota2.exe"
DOTA_STEAM_URL = "steam://rungameid/570"   # Dota2 AppID = 570
WINDOW_KEYWORD = "Dota 2"
# 小黑盒不同版本的进程名/窗口标题可能不同，可通过环境变量追加匹配关键词（逗号分隔）。
XHB_PROCESS_KEYWORDS = ("heybox", "xiaohei", "blackbox")
XHB_TITLE_KEYWORDS = ("小黑盒", "游戏")

# 等待游戏更新并重启的最长时间（分钟）
# 根据你平时的更新下载速度和 Steam 后台下载速度来调整，建议 30-60 分钟
UPDATE_WAIT_MINUTES = 60 

pydirectinput.PAUSE = 0.05
pydirectinput.FAILSAFE = True # 鼠标移动到左上角强制停止

# ================= 3. 日志配置 =================
LOG_FILE_NAME = "dota2auto.log"
LOG_MAX_BYTES = 2 * 1024 * 1024   # 单个日志文件上限 2MB，超出后自动切分
LOG_BACKUP_COUNT = 3              # 最多保留 3 个历史日志
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

logger = logging.getLogger("dota2auto")
WINDOW_OPERATION_LOCK = threading.RLock()

# setup_logging() 执行后填入日志文件真实路径，便于启动提示和排查问题
LOG_FILE_PATH = None


def is_frozen():
    """是否由 PyInstaller 打包运行（onefile / onedir 均为 True）"""
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


def get_app_dir():
    """
    程序所在目录。

    打包后 sys.executable 就是 exe 自身的路径；
    这里不能用 sys._MEIPASS —— onefile 模式下它是临时解压目录，进程退出即被删除，
    日志写进去等于没写。源码运行时取脚本所在目录，避免受启动时工作目录影响。
    """
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def pick_log_dir():
    """
    挑一个真正可写的日志目录：
    1) exe 同级的 logs/  （绿色版最直观）
    2) %LOCALAPPDATA%/Dota2Auto/logs/  （exe 放在 Program Files 等无写权限位置时）
    3) 系统临时目录
    """
    candidates = [os.path.join(get_app_dir(), "logs")]
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(os.path.join(local_appdata, "Dota2Auto", "logs"))
    candidates.append(os.path.join(tempfile.gettempdir(), "Dota2Auto", "logs"))

    for path in candidates:
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, ".write_test")
            with open(probe, "w", encoding="utf-8"):
                pass
            os.remove(probe)
            return path
        except OSError:
            continue
    return None


def setup_logging():
    """控制台 + 文件双通道日志（重复调用不会叠加 handler）"""
    global LOG_FILE_PATH

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)

    # ---- 控制台 ----
    # 打包成无控制台窗口（console=False）时 sys.stdout 为 None，此时跳过，避免启动即崩
    stream = sys.stdout
    if stream is not None:
        try:
            # 输出被重定向到管道/文件时默认是 GBK，日志里的 emoji 会抛 UnicodeEncodeError
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
        console_handler = logging.StreamHandler(stream)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # ---- 文件 ----
    log_dir = pick_log_dir()
    if log_dir:
        LOG_FILE_PATH = os.path.join(log_dir, LOG_FILE_NAME)
        file_handler = RotatingFileHandler(
            LOG_FILE_PATH,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.info("日志文件：%s", LOG_FILE_PATH)
    else:
        logger.warning("⚠️ 找不到可写的日志目录，本次运行只输出到控制台。")

    return logger


# ================= 4. 然后才是各个功能函数 =================
def activate_window(win):
    """只将 Dota2 窗口置顶，不强行抢夺焦点（避免报错）"""
    if not win:
        return

    try:
        # 如果窗口最小化了，先恢复
        if win.isMinimized():
            win.restore()
            time.sleep(0.2)
            
        # 只做置顶操作：将窗口设为最顶层
        win32gui.SetWindowPos(
            win.hwnd, 
            win32con.HWND_TOPMOST, 
            0, 0, 0, 0, 
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
        )
        # 注意：不要调用 SetForegroundWindow，就不会报错了！
        
    except Exception as e:
        # 即使置顶失败，也不让它崩溃，继续跑
        logger.warning("⚠️ 窗口置顶失败: %s", e)

def set_window_topmost(win, enable):
    """设置窗口置顶状态
    enable=True: 置顶
    enable=False: 取消置顶
    """
    if not win:
        return
    try:
        if win.isMinimized():
            win.restore()
            time.sleep(0.2)
        
        # 根据参数选择置顶标志
        flag = win32con.HWND_TOPMOST if enable else win32con.HWND_NOTOPMOST
        
        win32gui.SetWindowPos(
            win.hwnd, 
            flag, 
            0, 0, 0, 0, 
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
        )
    except Exception as e:
        logger.warning("⚠️ 设置窗口置顶状态失败: %s", e)        

def find_dota_window():
    """
    通过进程名 dota2.exe 找到对应的窗口句柄和坐标
    返回一个包含 left, top, width, height, hwnd, title 的对象
    """
    target_pid = None
    
    # 1. 遍历所有进程，找到 dota2.exe 的 PID
    for proc in psutil.process_iter(['name', 'pid']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == 'dota2.exe':
                target_pid = proc.info['pid']
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if target_pid is None:
        return None

    # 2. 通过 PID 找到对应的窗口句柄 (HWND)
    def enum_windows_callback(hwnd, windows):
        # 获取窗口所属的 PID
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid == target_pid:
            # 必须是可见的顶层窗口
            if win32gui.IsWindowVisible(hwnd):
                # 获取窗口标题和矩形区域
                title = win32gui.GetWindowText(hwnd)
                rect = win32gui.GetWindowRect(hwnd)
                left, top, right, bottom = rect
                width = right - left
                height = bottom - top
                
                # 排除掉一些太小的隐藏窗口（比如工具提示、托盘图标）
                if width > 200 and height > 200:
                    windows.append({
                        'hwnd': hwnd,
                        'title': title,
                        'left': left,
                        'top': top,
                        'width': width,
                        'height': height
                    })
        return True

    windows = []
    win32gui.EnumWindows(enum_windows_callback, windows)

    if not windows:
        return None

    # 3. 如果找到了多个窗口，通常选面积最大的那个（主窗口）
    best_window = max(windows, key=lambda w: w['width'] * w['height'])
    
    # 4. 为了兼容原来的代码，用一个简单的类包装一下
    class DotaWindow:
        def __init__(self, data):
            self.hwnd = data['hwnd']
            self.title = data['title']
            self.left = data['left']
            self.top = data['top']
            self.width = data['width']
            self.height = data['height']
        
        def isMinimized(self):
            return win32gui.IsIconic(self.hwnd)
        
        def restore(self):
            win32gui.ShowWindow(self.hwnd, 9) # SW_RESTORE = 9
            
        def activate(self):
            # 只置顶，不抢焦点
            win32gui.SetWindowPos(
                self.hwnd, 
                win32con.HWND_TOPMOST, 
                0, 0, 0, 0, 
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
            )

    return DotaWindow(best_window)


def find_xiaoheihei_window():
    """按进程名或窗口标题查找小黑盒客户端窗口，优先选择更明确的匹配。"""
    process_keywords = list(XHB_PROCESS_KEYWORDS)
    title_keywords = list(XHB_TITLE_KEYWORDS)
    process_keywords += [x.strip().lower() for x in os.environ.get("DOTA2AUTO_XHB_PROCESS_KEYWORDS", "").split(",") if x.strip()]
    title_keywords += [x.strip().lower() for x in os.environ.get("DOTA2AUTO_XHB_TITLE_KEYWORDS", "").split(",") if x.strip()]

    matches = []

    def enum_windows_callback(hwnd, windows):
        if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return True

        title = win32gui.GetWindowText(hwnd)
        if not title:
            return True

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            process_name = psutil.Process(pid).name().lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            process_name = ""

        if process_name == DOTA_PROCESS.lower():
            return True

        rect = win32gui.GetWindowRect(hwnd)
        left, top, right, bottom = rect
        width, height = right - left, bottom - top
        if width < 500 or height < 350:
            return True

        process_match = any(key in process_name for key in process_keywords)
        title_match = any(
            (title.strip() == key) if key == "游戏" else (key.casefold() in title.casefold())
            for key in title_keywords
        )
        if not process_match and not title_match:
            return True

        # 进程名命中最可靠，其次是“小黑盒”标题；“游戏”是截图里当前客户端的通用标题。
        rank = 3 if process_match else (2 if "小黑盒" in title else 1)
        windows.append({
            "hwnd": hwnd,
            "title": title,
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "rank": rank,
        })
        return True

    win32gui.EnumWindows(enum_windows_callback, matches)
    if not matches:
        return None

    data = max(matches, key=lambda w: (w["rank"], w["width"] * w["height"]))

    class XiaoheiheiWindow:
        def __init__(self, info):
            self.hwnd = info["hwnd"]
            self.title = info["title"]
            self.left = info["left"]
            self.top = info["top"]
            self.width = info["width"]
            self.height = info["height"]

        def isMinimized(self):
            return win32gui.IsIconic(self.hwnd)

        def restore(self):
            win32gui.ShowWindow(self.hwnd, 9)

    return XiaoheiheiWindow(data)

def grab_window(win):
    """截取指定窗口画面"""
    left, top = win.left, win.top
    width, height = win.width, win.height

    with mss.MSS() as sct:
        monitor = {"left": left, "top": top, "width": width, "height": height}
        img = np.array(sct.grab(monitor))
        screen = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return screen


def grab_client_window(win):
    """截取 Dota 客户区，排除普通窗口模式的标题栏、边框和阴影。"""
    client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(win.hwnd)
    left, top = win32gui.ClientToScreen(win.hwnd, (client_left, client_top))
    width = client_right - client_left
    height = client_bottom - client_top
    if width <= 0 or height <= 0:
        raise ValueError("Dota 客户区尺寸无效：%s x %s" % (width, height))

    with mss.MSS() as sct:
        monitor = {"left": left, "top": top, "width": width, "height": height}
        img = np.array(sct.grab(monitor))
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def get_window_size_info(win):
    """返回外框尺寸和客户区尺寸，用于观察窗口装饰与实际画面尺寸差异。"""
    outer_left, outer_top, outer_right, outer_bottom = win32gui.GetWindowRect(win.hwnd)
    client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(win.hwnd)
    return {
        "outer": (outer_right - outer_left, outer_bottom - outer_top),
        "client": (client_right - client_left, client_bottom - client_top),
    }


def get_window_dpi_scale(win):
    """读取窗口所在显示器的 DPI 比例；旧系统或 API 不可用时返回 100%。"""
    try:
        get_dpi_for_window = ctypes.WinDLL("user32", use_last_error=True).GetDpiForWindow
        get_dpi_for_window.argtypes = [wintypes.HWND]
        get_dpi_for_window.restype = wintypes.UINT
        dpi = get_dpi_for_window(win.hwnd)
        return dpi / 96.0 if dpi else 1.0
    except (AttributeError, OSError, TypeError, ValueError):
        return 1.0


def match_template_scaled(screen_bgr, template_path, threshold=XHB_MATCH_THRESHOLD, preferred_scale=1.0):
    """优先按窗口 DPI 缩放模板，失败时再尝试常见显示缩放比例。"""
    if not os.path.exists(template_path):
        return None, 0.0

    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
    if template is None:
        return None, 0.0

    best_center, best_score = None, 0.0

    def search_scales(scales):
        nonlocal best_center, best_score
        screen_h, screen_w = screen_bgr.shape[:2]
        for scale in scales:
            width = max(1, round(template.shape[1] * scale))
            height = max(1, round(template.shape[0] * scale))
            if width > screen_w or height > screen_h:
                continue
            interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
            resized = cv2.resize(template, (width, height), interpolation=interpolation)
            result = cv2.matchTemplate(screen_bgr, resized, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
            if score > best_score:
                best_score = score
                best_center = (location[0] + width // 2, location[1] + height // 2)

    preferred_scale = round(preferred_scale, 3)
    search_scales((preferred_scale,))
    if best_score >= threshold:
        return best_center, best_score

    # DPI API 不一定反映应用最终渲染尺寸；仅补查常见档位，不做大范围逐档扫描。
    search_scales(scale for scale in XHB_MATCH_FALLBACK_SCALES if scale != preferred_scale)

    return (best_center, best_score) if best_score >= threshold else (None, best_score)

def click_in_window(win, rel_x, rel_y):
    """在窗口内相对坐标点击"""
    screen_x = win.left + rel_x
    screen_y = win.top + rel_y

    # activate_window(win)
    pydirectinput.moveTo(screen_x, screen_y)
    pydirectinput.click()
    logger.info("👉 点击窗口内 (%s, %s) -> 屏幕 (%s, %s)", rel_x, rel_y, screen_x, screen_y)

def is_process_running(process_name):
    """判断进程是否在运行"""
    for p in psutil.process_iter(["name"]):
        try:
            if p.info["name"] and p.info["name"].lower() == process_name.lower():
                return True
        except Exception:
            pass
    return False

def close_dota(stop_event):
    logger.warning("强制关闭 Dota 2...")
    # /T 表示终止指定的进程和由它启用的子进程
    subprocess.run(["taskkill", "/IM", DOTA_PROCESS, "/T", "/F"], capture_output=True)
    return not stop_event.wait(5) # 等系统释放进程资源；退出时可提前中断

def restart_dota_via_steam(stop_event):
    """通过 Steam 重启 Dota2，并等待更新和窗口出现"""
    logger.info("通过 Steam 拉起 Dota2（Steam 会处理更新）...")
    os.startfile(DOTA_STEAM_URL)

    # 根据配置的分钟数，计算需要检查多少次（每 10 秒检查一次）
    # 公式：分钟数 * 60秒 / 10秒 = 分钟数 * 6
    max_checks = UPDATE_WAIT_MINUTES * 6 
    
    logger.info("等待 Dota2 进程出现（最长等待 %s 分钟）...", UPDATE_WAIT_MINUTES)
    
    for i in range(max_checks):
        if stop_event.is_set():
            return None
        if is_process_running(DOTA_PROCESS):
            logger.info("✅ Dota2 进程已出现（等待了 %s 秒）", i * 10)
            break
        if stop_event.wait(10):
            return None
        # 每隔 1 分钟打印一次日志，避免刷屏
        if i % 6 == 0:
            elapsed_min = i * 10 // 60
            logger.info("⏳ 仍在等待更新和启动... 已等待 %s 分钟 / 共 %s 分钟", elapsed_min, UPDATE_WAIT_MINUTES)
    else:
        # 如果循环正常走完（没有 break），说明超时了
        logger.warning("⚠️ 等待 Dota2 进程超时（超过 %s 分钟），请检查 Steam 是否在下载更新。", UPDATE_WAIT_MINUTES)

    # 等待窗口出现，继续轮询
    logger.info("等待 Dota2 窗口就绪...")
    for _ in range(60): # 再等 5 分钟找窗口（这个可以写死，因为进程都有了，窗口通常很快就出来）
        if stop_event.is_set():
            return None
        win = find_dota_window()
        if win:
            logger.info("✅ Dota2 窗口已成功出现！继续轮询。")
            return win
        if stop_event.wait(5):
            return None

    logger.warning("⚠️ 等待 Dota2 窗口超时。")
    return None


def monitor_dota_updates(stop_event):
    """独立监控 Dota 更新弹窗；Steam 重启等待不会阻塞小黑盒轮询。"""
    last_window_size_info = None
    last_logged_match_score = None
    while not stop_event.is_set():
        try:
            dota_win = find_dota_window()
            if dota_win:
                size_info = get_window_size_info(dota_win)
                if size_info != last_window_size_info:
                    outer_w, outer_h = size_info["outer"]
                    client_w, client_h = size_info["client"]
                    logger.info(
                        "Dota 窗口尺寸：外框 %s×%s，客户区 %s×%s",
                        outer_w,
                        outer_h,
                        client_w,
                        client_h,
                    )
                    last_window_size_info = size_info

                with WINDOW_OPERATION_LOCK:
                    set_window_topmost(dota_win, True)
                    try:
                        time.sleep(0.2)
                        dota_screen = grab_client_window(dota_win)
                    finally:
                        set_window_topmost(dota_win, False)

                # TODO: 在这里预留 Dota 游戏内更新操作的识别/处理入口；该流程尚未实现。
                # 当前只保留现有的“需要更新”弹窗检测和 Steam 重启逻辑。
                center, score, scale = match_template_multiscale(
                    dota_screen,
                    TEMPLATES["update_popup"],
                    DOTA_UPDATE_MATCH_THRESHOLD,
                    DOTA_UPDATE_FALLBACK_SCALES,
                )
                # 常规轮询每 4 秒执行一次；分数基本不变时不重复刷控制台和日志。
                # 首次记录一次，之后仅在分数变化达到 0.05 时更新诊断信息。
                if (
                    last_logged_match_score is None
                    or abs(score - last_logged_match_score) >= 0.05
                ):
                    logger.debug("Dota 更新弹窗匹配分数 %.3f，模板缩放 %.2f", score, scale)
                    last_logged_match_score = score
                if center:
                    logger.warning(
                        "🚨 识别到 Dota [需要更新]弹窗（匹配度 %.2f，模板缩放 %.2f），通过 Steam 重启游戏...",
                        score,
                        scale,
                    )
                    if not close_dota(stop_event):
                        break
                    if restart_dota_via_steam(stop_event) and stop_event.wait(15):
                        break
        except Exception:
            logger.exception("Dota 更新监控发生异常，将在下一轮重试。")

        stop_event.wait(POLL_INTERVAL)

def cleanup():
    logger.info("脚本退出，恢复 Dota 和小黑盒窗口层级...")
    with WINDOW_OPERATION_LOCK:
        for win in (find_dota_window(), find_xiaoheihei_window()):
            if win:
                set_window_topmost(win, False)


_console_close_handler = None


def register_console_close_handler():
    """点击控制台关闭按钮时尽量先恢复窗口层级；Ctrl+C 仍由 Python 正常处理。"""
    global _console_close_handler
    if os.name != "nt":
        return

    handler_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

    def handle_console_event(event):
        # CTRL_CLOSE_EVENT / CTRL_LOGOFF_EVENT / CTRL_SHUTDOWN_EVENT
        if event in (2, 5, 6):
            try:
                cleanup()
            except Exception:
                logger.exception("控制台关闭时恢复窗口层级失败")
        # 让系统继续执行默认终止流程。
        return 0

    _console_close_handler = handler_type(handle_console_event)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetConsoleCtrlHandler.argtypes = [handler_type, ctypes.c_int]
    kernel32.SetConsoleCtrlHandler.restype = ctypes.c_int
    if not kernel32.SetConsoleCtrlHandler(_console_close_handler, 1):
        logger.warning("注册控制台关闭处理器失败（错误码 %s）", ctypes.get_last_error())

def cancel_topmost(win):
    """取消窗口置顶，恢复正常层级"""
    if not win:
        return
    try:
        win32gui.SetWindowPos(
            win.hwnd,
            win32con.HWND_NOTOPMOST,  # 取消置顶
            0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
        )
    except Exception as e:
        logger.warning("⚠️ 取消窗口置顶失败: %s", e)

def monitor_xiaoheihei(stop_event):
    """独立处理小黑盒邀请和准备状态。"""
    xhb_flow_state = "monitor_invite"
    xhb_flow_started = 0
    last_xhb_dpi_scale = None

    while not stop_event.is_set():
        try:
            xhb_win = find_xiaoheihei_window()
            if not xhb_win:
                logger.debug("未找到小黑盒窗口，继续轮询。")
                stop_event.wait(POLL_INTERVAL)
                continue

            xhb_dpi_scale = get_window_dpi_scale(xhb_win)
            if xhb_dpi_scale != last_xhb_dpi_scale:
                logger.info(
                    "小黑盒窗口 DPI 缩放：%.0f%%，优先模板缩放 %.2f",
                    xhb_dpi_scale * 100,
                    xhb_dpi_scale,
                )
                last_xhb_dpi_scale = xhb_dpi_scale

            # 两个监控线程可能同时调整窗口层级；串行化短暂的窗口操作。
            with WINDOW_OPERATION_LOCK:
                set_window_topmost(xhb_win, True)
                try:
                    time.sleep(0.2)
                    xhb_screen = grab_window(xhb_win)
                finally:
                    set_window_topmost(xhb_win, False)

            action_center = None
            action_name = None
            action_score = 0.0
            next_flow_state = None

            invite_center, invite_score = (None, 0.0)
            ready_center, ready_score = (None, 0.0)
            cancel_center, cancel_score = (None, 0.0)
            bell_center, bell_score = (None, 0.0)

            if xhb_flow_state in ("monitor_invite", "waiting_invite_card"):
                invite_center, invite_score = match_template_scaled(
                    xhb_screen,
                    TEMPLATES["xhb_accept_invite"],
                    preferred_scale=xhb_dpi_scale,
                )
            if xhb_flow_state in ("monitor_invite", "waiting_team_ready"):
                ready_center, ready_score = match_template_scaled(
                    xhb_screen, TEMPLATES["xhb_ready"], preferred_scale=xhb_dpi_scale
                )
            if xhb_flow_state in ("monitor_invite", "waiting_team_ready", "waiting_ready_confirmation"):
                cancel_center, cancel_score = match_template_scaled(
                    xhb_screen,
                    TEMPLATES["xhb_cancel_ready"],
                    preferred_scale=xhb_dpi_scale,
                )
            if xhb_flow_state == "monitor_invite" and not invite_center and not ready_center and not cancel_center:
                bell_center, bell_score = match_template_scaled(
                    xhb_screen,
                    TEMPLATES["xhb_notification_badge"],
                    preferred_scale=xhb_dpi_scale,
                )

            ready_action = ready_center and (not cancel_center or ready_score > cancel_score)
            now = time.monotonic()

            if xhb_flow_state == "monitor_invite":
                if invite_center:
                    action_center, action_name, action_score = invite_center, "接受小黑盒组队邀请", invite_score
                    next_flow_state = "waiting_team_ready"
                elif ready_action:
                    # 准备独立于邀请流程；队伍保留到下一局时也能由常规轮询处理。
                    action_center, action_name, action_score = ready_center, "在小黑盒队伍中准备", ready_score
                    next_flow_state = "waiting_ready_confirmation"
                elif cancel_center:
                    logger.debug("小黑盒队伍已准备，等待队长开始（匹配度 %.2f）。", cancel_score)
                elif bell_center:
                    action_center, action_name, action_score = bell_center, "打开小黑盒邀请通知", bell_score
                    next_flow_state = "waiting_invite_card"

            elif xhb_flow_state == "waiting_invite_card":
                if invite_center:
                    action_center, action_name, action_score = invite_center, "接受小黑盒组队邀请", invite_score
                    next_flow_state = "waiting_team_ready"
                elif now - xhb_flow_started >= XHB_FLOW_TIMEOUT:
                    logger.warning("打开通知后 %s 秒内未识别到邀请，立即返回正常轮询。", XHB_FLOW_TIMEOUT)
                    xhb_flow_state = "monitor_invite"
                    continue

            elif xhb_flow_state == "waiting_team_ready":
                if cancel_center:
                    logger.debug("小黑盒队伍已准备，等待队长开始（匹配度 %.2f）。", cancel_score)
                    xhb_flow_state = "monitor_invite"
                elif ready_action:
                    action_center, action_name, action_score = ready_center, "在小黑盒队伍中准备", ready_score
                    next_flow_state = "waiting_ready_confirmation"
                elif now - xhb_flow_started >= XHB_FLOW_TIMEOUT:
                    logger.warning("接受邀请后 %s 秒内未识别到准备按钮，立即返回正常轮询。", XHB_FLOW_TIMEOUT)
                    xhb_flow_state = "monitor_invite"
                    continue

            elif xhb_flow_state == "waiting_ready_confirmation":
                if cancel_center:
                    logger.info("✅ 小黑盒已确认准备，等待队长开始（匹配度 %.2f）。", cancel_score)
                    xhb_flow_state = "monitor_invite"
                elif now - xhb_flow_started >= XHB_FLOW_TIMEOUT:
                    logger.warning("点击准备后 %s 秒内未确认已准备，立即返回正常轮询。", XHB_FLOW_TIMEOUT)
                    xhb_flow_state = "monitor_invite"
                    continue

            if action_center:
                logger.info("✅ 识别到[%s]，匹配度 %.2f", action_name, action_score)
                with WINDOW_OPERATION_LOCK:
                    set_window_topmost(xhb_win, True)
                    try:
                        click_in_window(xhb_win, action_center[0], action_center[1])
                    finally:
                        set_window_topmost(xhb_win, False)
                xhb_flow_state = next_flow_state
                xhb_flow_started = time.monotonic()
                if stop_event.wait(CLICK_DELAY):
                    break
                # 动作后跳过常规轮询等待，尽快识别并处理下一步界面。
                continue

        except Exception:
            logger.exception("小黑盒监控发生异常，将在下一轮重试。")
            if stop_event.wait(POLL_INTERVAL):
                break
            continue

        interval = XHB_ACTIVE_POLL_INTERVAL if xhb_flow_state != "monitor_invite" else POLL_INTERVAL
        stop_event.wait(interval)


def main():
    logger.info("Dota2 自动点击脚本启动...")
    logger.info("运行模式：%s | 程序目录：%s",
                "打包运行(onefile)" if is_frozen() else "源码运行", get_app_dir())
    logger.info("提示：请保持小黑盒客户端窗口打开且未最小化；Dota 2 需运行以检测更新弹窗。")
    logger.info("Dota 更新匹配阈值 %.2f | 轮询间隔 %s 秒 | 更新最长等待 %s 分钟",
                DOTA_UPDATE_MATCH_THRESHOLD, POLL_INTERVAL, UPDATE_WAIT_MINUTES)
    logger.info("小黑盒匹配阈值 %.2f | 单步状态等待上限 %s 秒", XHB_MATCH_THRESHOLD, XHB_FLOW_TIMEOUT)

    for name, path in TEMPLATES.items():
        if not os.path.exists(path):
            logger.warning("⚠️ 模板文件缺失：%s，请先制作模板图片！", path)

    stop_event = threading.Event()
    dota_thread = threading.Thread(
        target=monitor_dota_updates,
        args=(stop_event,),
        name="DotaUpdateMonitor",
        daemon=False,
    )
    dota_thread.start()

    try:
        monitor_xiaoheihei(stop_event)
    finally:
        logger.info("正在停止监控线程...")
        stop_event.set()
        dota_thread.join(timeout=10)
        if dota_thread.is_alive():
            logger.warning("Dota 更新监控线程尚未退出，程序将继续清理窗口。")
        cleanup()


atexit.register(cleanup)

if __name__ == "__main__":
    setup_logging()
    register_console_close_handler()
    try:
        main()
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C，脚本退出。")
    except Exception:
        # 打包后一闪而退的崩溃，traceback 会完整留在日志文件里
        logger.exception("❌ 脚本异常退出")
