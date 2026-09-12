import sys
import os
import time
import subprocess

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

# ================= 1. 先定义资源路径函数 =================
def get_resource_path(relative_path):
    """获取资源绝对路径，兼容 PyInstaller 打包环境"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# ================= 2. 再定义配置变量 =================
TEMPLATES = {
    "accept_ready": get_resource_path("templates/accept_ready.png"),
    "start_game": get_resource_path("templates/start_game.png"),
    "accept_invite": get_resource_path("templates/accept_invite.png"),
    "update_popup": get_resource_path("templates/update_popup.png"),
}

THRESHOLD = 0.80          # 匹配阈值，根据实际环境调整（0.75~0.9）
POLL_INTERVAL = 4         # 每 3~5 秒轮询一次
CLICK_DELAY = 2           # 点击后等几秒，避免重复点击同一个弹窗
DOTA_PROCESS = "dota2.exe"
DOTA_STEAM_URL = "steam://rungameid/570"   # Dota2 AppID = 570
WINDOW_KEYWORD = "Dota 2"

# 等待游戏更新并重启的最长时间（分钟）
# 根据你平时的更新下载速度和 Steam 后台下载速度来调整，建议 30-60 分钟
UPDATE_WAIT_MINUTES = 60 

pydirectinput.PAUSE = 0.05
pydirectinput.FAILSAFE = True # 鼠标移动到左上角强制停止

# ================= 3. 然后才是各个功能函数 =================
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
        print(f"⚠️ 窗口置顶失败: {e}")

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

def grab_window(win):
    """截取 Dota2 窗口画面"""
    left, top = win.left, win.top
    width, height = win.width, win.height

    with mss.MSS() as sct:
        monitor = {"left": left, "top": top, "width": width, "height": height}
        img = np.array(sct.grab(monitor))
        screen = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return screen

def match_template(screen_bgr, template_path, threshold=THRESHOLD):
    """模板匹配，返回按钮中心相对窗口坐标"""
    if not os.path.exists(template_path):
        return None, 0.0

    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
    if template is None:
        return None, 0.0

    res = cv2.matchTemplate(screen_bgr, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)

    if max_val >= threshold:
        h, w = template.shape[:2]
        center = (max_loc[0] + w // 2, max_loc[1] + h // 2)
        return center, max_val

    return None, max_val

def click_in_window(win, rel_x, rel_y):
    """在窗口内相对坐标点击"""
    screen_x = win.left + rel_x
    screen_y = win.top + rel_y

    activate_window(win)
    pydirectinput.moveTo(screen_x, screen_y)
    pydirectinput.click()
    print(f"👉 点击窗口内 ({rel_x}, {rel_y}) -> 屏幕 ({screen_x}, {screen_y})")

def is_process_running(process_name):
    """判断进程是否在运行"""
    for p in psutil.process_iter(["name"]):
        try:
            if p.info["name"] and p.info["name"].lower() == process_name.lower():
                return True
        except Exception:
            pass
    return False

def close_dota():
    print("强制关闭 Dota 2...")
    # /T 表示终止指定的进程和由它启用的子进程
    subprocess.run(["taskkill", "/IM", DOTA_PROCESS, "/T", "/F"], capture_output=True)
    time.sleep(5) # 等系统释放进程资源

def restart_dota_via_steam():
    """通过 Steam 重启 Dota2，并等待更新和窗口出现"""
    print("通过 Steam 拉起 Dota2（Steam 会处理更新）...")
    os.startfile(DOTA_STEAM_URL)

    # 根据配置的分钟数，计算需要检查多少次（每 10 秒检查一次）
    # 公式：分钟数 * 60秒 / 10秒 = 分钟数 * 6
    max_checks = UPDATE_WAIT_MINUTES * 6 
    
    print(f"等待 Dota2 进程出现（最长等待 {UPDATE_WAIT_MINUTES} 分钟）...")
    
    for i in range(max_checks):
        if is_process_running(DOTA_PROCESS):
            print(f"✅ Dota2 进程已出现（等待了 {i*10} 秒）")
            break
        time.sleep(10)
        # 每隔 1 分钟打印一次日志，避免刷屏
        if i % 6 == 0:
            elapsed_min = i * 10 // 60
            print(f"⏳ 仍在等待更新和启动... 已等待 {elapsed_min} 分钟 / 共 {UPDATE_WAIT_MINUTES} 分钟")
    else:
        # 如果循环正常走完（没有 break），说明超时了
        print(f"⚠️ 等待 Dota2 进程超时（超过 {UPDATE_WAIT_MINUTES} 分钟），请检查 Steam 是否在下载更新。")

    # 等待窗口出现，继续轮询
    print("等待 Dota2 窗口就绪...")
    for _ in range(60): # 再等 5 分钟找窗口（这个可以写死，因为进程都有了，窗口通常很快就出来）
        win = find_dota_window()
        if win:
            print("✅ Dota2 窗口已成功出现！继续轮询。")
            return win
        time.sleep(5)

    print("⚠️ 等待 Dota2 窗口超时。")
    return None

def cleanup():
    """脚本退出时，强制恢复所有窗口的置顶状态"""
    print("脚本退出，正在恢复窗口层级...")
    win = find_dota_window()
    if win:
        cancel_topmost(win)

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
        print(f"⚠️ 取消窗口置顶失败: {e}")

def main():
    print("Dota2 自动点击脚本启动...")
    print("提示：请确保游戏为「无边框窗口」模式，Windows缩放为100%")
    
    # 强制打印一下当前配置的模板是否存在
    for name, path in TEMPLATES.items():
        if not os.path.exists(path):
            print(f"⚠️ 警告：模板文件缺失 {path}，请先制作模板图片！")

    while True:
        win = find_dota_window()
        if not win:
            print("未找到 Dota 2 窗口，等待中...")
            time.sleep(3)
            continue

        # 截图前先临时置顶
        activate_window(win)
        time.sleep(0.1)

        try:
            screen = grab_window(win)

            # ================= 优先级 1：检测到“需要更新”弹窗 =================
            center, score = match_template(screen, TEMPLATES["update_popup"])
            if center:
                print(f"🚨 识别到[需要更新]弹窗（匹配度 {score:.2f}），直接强制关闭游戏...")
                # 因为后面要等很久，提前取消置顶，防止一直霸屏
                cancel_topmost(win)
                close_dota()
                restart_dota_via_steam()
                print("等待游戏重新启动，跳过几轮轮询...")
                time.sleep(15)
                continue

            # ================= 优先级 2：检测到“开始游戏” =================
            center, score = match_template(screen, TEMPLATES["start_game"])
            if center:
                print(f"✅ 识别到[开始游戏]按钮，匹配度 {score:.2f}")
                click_in_window(win, center[0], center[1])
                time.sleep(CLICK_DELAY)
                continue

            # ================= 优先级 3：检测到“游戏就绪-接受” =================
            center, score = match_template(screen, TEMPLATES["accept_ready"])
            if center:
                print(f"✅ 识别到[游戏就绪-接受]按钮，匹配度 {score:.2f}")
                click_in_window(win, center[0], center[1])
                time.sleep(CLICK_DELAY)
                continue

            # ================= 优先级 4：检测到“组队邀请-接受” =================
            center, score = match_template(screen, TEMPLATES["accept_invite"])
            if center:
                print(f"✅ 识别到[组队邀请-接受]按钮，匹配度 {score:.2f}")
                click_in_window(win, center[0], center[1])
                time.sleep(CLICK_DELAY)
                continue

            print("未识别到目标弹窗，继续轮询...")
            time.sleep(POLL_INTERVAL)

        finally:
            # 无论走哪个分支，只要本轮结束了，就取消置顶
            cancel_topmost(win)


atexit.register(cleanup)

if __name__ == "__main__":
    main()