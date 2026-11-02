"""Recover only Steam's invalid-app-id join failure, never arbitrary dialogs."""
from pathlib import Path
import time
from copy import deepcopy

from xhb_matching import match_template_scaled
from window_input import bound_client_click


def is_game_info_title(title):
    # Never promote the main Steam browser while recovering the game dialog.
    return '游戏信息' in title or 'game info' in title.casefold()


def renderer_target(gui, window, point):
    """Resolve actual CEF input HWND, bounded to the verified dialog root."""
    target = gui.WindowFromPoint(point)
    if not target or gui.GetAncestor(target, 2) != window.hwnd:
        return None
    if gui.GetClassName(target) != 'Chrome_RenderWidgetHostHWND':
        return None
    return target, gui.ScreenToClient(target, point)


def recognize(screen, templates):
    def find(name):
        threshold = .86 if name in ('close', 'join') else .92
        return match_template_scaled(screen, str(Path(templates) / (name + '.png')), threshold=threshold)[0]

    error, close = find('error'), find('close')
    if error and close:
        dx, dy = close[0] - error[0], close[1] - error[1]
        if 0 < dy < 200 and abs(dx) < 180:
            return 'error', close
    header, game, map_name, join = (find(n) for n in ('header', 'dota', 'map', 'join'))
    if all((header, game, map_name, join)):
        if header[1] < game[1] < map_name[1] < join[1] and header[0] < join[0] < game[0]:
            return 'join', join
    return None, None


class JoinRecovery:
    """Require error -> disappearance -> join in the same window; cap attempts."""
    def __init__(self):
        self.windows = {}

    def step(self, hwnd, state, center, now):
        entry = self.windows.setdefault(hwnd, dict(phase='idle', attempts=0, deadline=0, after=0))
        if now < entry['after']:
            return None
        if state == 'error' and entry['phase'] == 'idle' and entry['attempts'] < 3:
            entry.update(phase='waiting', deadline=now + 10, after=now + 1)
            return 'close', center
        if entry['phase'] == 'waiting':
            if now > entry['deadline']:
                entry.update(phase='idle', after=now + 30)
                entry['attempts'] += 1
            elif state == 'join':
                entry.update(phase='idle', after=now + 30)
                entry['attempts'] += 1
                return 'join', center
        return None

    def retain(self, handles):
        self.windows = {h: state for h, state in self.windows.items() if h in handles}


class SteamJoinMonitor:
    def __init__(self, templates, logger):
        self.templates, self.logger = templates, logger
        self.recovery = JoinRecovery()
        self.next_poll = 0
        self.identity = None

    def poll(self, capture, lock, stopped):
        # Imports stay here so recognition/sequence tests do not touch desktop APIs.
        import psutil
        import win32gui
        import win32process
        import win32service
        import win32con
        from steam_identity import SteamIdentity, installed_steam_root
        from types import SimpleNamespace

        now = time.monotonic()
        if now < self.next_poll or stopped.is_set():
            return
        self.next_poll = now + 2
        # A secure desktop is not an actionable game screen.
        try:
            desktop = win32service.OpenInputDesktop(0, False, 1)
            try:
                if win32service.GetUserObjectInformation(desktop, 2) != 'Default':
                    return
            finally:
                desktop.CloseDesktop()
        except Exception:
            return
        if self.identity is None:
            self.identity = SteamIdentity(installed_steam_root())
        windows = []
        def visit(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
                return
            try:
                if not is_game_info_title(win32gui.GetWindowText(hwnd)):
                    return
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                identity = self.identity.check(psutil.Process(pid))
                if identity is None:
                    return
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                if 350 <= right-left <= 1400 and 350 <= bottom-top <= 1200:
                    windows.append(SimpleNamespace(hwnd=hwnd, identity=identity))
            except (psutil.Error, win32gui.error, OSError):
                return
        win32gui.EnumWindows(visit, None)
        self.recovery.retain({w.hwnd for w in windows})
        for window in windows:
            with lock:
                if stopped.is_set():
                    return
                def trusted():
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(window.hwnd)
                        return (self.identity.check(psutil.Process(pid)) == window.identity
                                and win32gui.IsWindowVisible(window.hwnd)
                                and win32gui.IsWindowEnabled(window.hwnd)
                                and not win32gui.GetWindowLong(window.hwnd, win32con.GWL_EXSTYLE) & 0x20)
                    except (psutil.Error, OSError, win32gui.error):
                        return False
                if not trusted():
                    continue
                was_topmost = bool(win32gui.GetWindowLong(window.hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOPMOST)
                def prepare():
                    if not trusted() or stopped.is_set():
                        return False
                    win32gui.SetWindowPos(window.hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
                    return True
                def bound_click(win, x, y):
                    if not trusted() or stopped.is_set():
                        return False
                    point = (win.left + x, win.top + y)
                    target = renderer_target(win32gui, win, point)
                    if target is None:
                        self.logger.debug('Steam 游戏信息窗口暂被遮挡或渲染子窗口未就绪，跳过本轮。')
                        return False
                    child, (client_x, client_y) = target
                    _, child_pid = win32process.GetWindowThreadProcessId(child)
                    child_identity = self.identity.check(psutil.Process(child_pid))
                    if child_identity is None:
                        return False
                    def trusted_child(_):
                        try:
                            _, pid = win32process.GetWindowThreadProcessId(child)
                            return (trusted() and win32gui.IsChild(win.hwnd, child)
                                    and win32gui.GetAncestor(child, 2) == win.hwnd
                                    and self.identity.check(psutil.Process(pid)) == child_identity)
                        except (psutil.Error, OSError, win32gui.error):
                            return False
                    if not bound_client_click(win32gui, SimpleNamespace(hwnd=child), client_x, client_y,
                                              trusted_child, stopped):
                        return False
                    self.logger.info('Steam 窗口输入已发送：根窗口=%s 子窗口=%s 位置=(%s,%s)',
                                     win.hwnd, child, client_x, client_y)
                    return True
                try:
                    self.process_window(window, capture, bound_click, stopped, prepare)
                finally:
                    if not was_topmost and win32gui.IsWindow(window.hwnd):
                        win32gui.SetWindowPos(window.hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)

    def process_window(self, window, capture, click, stopped, prepare=lambda: True):
        if stopped.is_set() or not prepare():
            return
        screen = capture(window)
        state, center = recognize(screen, self.templates)
        pending = deepcopy(self.recovery)
        action = pending.step(window.hwnd, state, center, time.monotonic())
        if action:
            # Commit the transition only after revalidation and a successful click.
            if not prepare():
                return
            fresh = recognize(capture(window), self.templates)
            if fresh != (state, center) or stopped.is_set():
                return
            if click(window, *center) is False:
                return
            self.logger.info('Steam 进房恢复：%s；窗口=%s', action[0], window.hwnd)
        self.recovery = pending
