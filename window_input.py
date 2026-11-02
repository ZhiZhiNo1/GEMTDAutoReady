"""HWND-bound input shared by recovery handlers; no global mouse input."""

def bound_client_click(gui, window, x, y, verify, stopped=None):
    """Deliver to the verified HWND only; never send elevated global mouse input."""
    if stopped is not None and stopped.is_set():
        return False
    if not verify(window):
        raise RuntimeError('Target identity changed before window click')
    width, height = gui.GetClientRect(window.hwnd)[2:]
    x, y = int(x), int(y)
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError('Click outside target client')
    point = (y << 16) | x
    # WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP. HWND routing prevents a
    # disappearing or click-through overlay from redirecting input elsewhere.
    gui.SendMessageTimeout(window.hwnd, 0x0200, 0, point, 0x0002, 1000)
    if not verify(window) or (stopped is not None and stopped.is_set()):
        return False
    try:
        gui.SendMessageTimeout(window.hwnd, 0x0201, 1, point, 0x0002, 1000)
    finally:
        gui.SendMessageTimeout(window.hwnd, 0x0202, 0, point, 0x0002, 1000)
    return True
