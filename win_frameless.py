# -*- coding: utf-8 -*-
"""
无边框窗口在 Windows 上的两个补丁(仅 win32 生效):
1. 任务栏点击最小化:给窗口补 WS_MINIMIZEBOX,并保证是"应用窗口"(WS_EX_APPWINDOW,
   去掉 WS_EX_TOOLWINDOW),这样任务栏点击图标能正常最小化。
2. 四边/四角拉伸:WM_NCHITTEST 边缘命中检测(返回 HTLEFT/HTRIGHT/HTTOP/HTBOTTOM/…),
   让无边框窗口四周都能拉拽缩放。
"""
import sys


def is_win() -> bool:
    return sys.platform == "win32"


def apply_win_styles(hwnd) -> None:
    """给无边框窗口补 WS_MINIMIZEBOX + 应用窗口样式(任务栏可点击最小化)。"""
    if not is_win():
        return
    import ctypes
    from ctypes import wintypes
    GWL_STYLE = -16
    GWL_EXSTYLE = -20
    WS_MINIMIZEBOX = 0x00020000
    WS_EX_APPWINDOW = 0x00040000
    WS_EX_TOOLWINDOW = 0x00000080
    GCLP_HBRBACKGROUND = -10
    user32 = ctypes.windll.user32
    style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    style |= WS_MINIMIZEBOX
    ex &= ~WS_EX_TOOLWINDOW
    ex |= WS_EX_APPWINDOW
    user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex)


def hit_test(hwnd, sx, sy) -> int:
    """WM_NCHITTEST:返回应命中的边缘/角(非边缘返回 1=HTCLIENT)。sx/sy 为屏幕坐标。"""
    import ctypes
    from ctypes import wintypes
    r = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
    b = 12   # 边缘命中判定范围(越宽越好抓;太窄不好拖)
    x = sx - r.left
    y = sy - r.top
    w = r.right - r.left
    h = r.bottom - r.top
    left = x < b
    right = x > w - b
    top = y < b
    bottom = y > h - b
    HTLEFT, HTRIGHT, HTTOP, HTBOTTOM = 10, 11, 12, 15
    HTTOPLEFT, HTTOPRIGHT, HTBOTTOMLEFT, HTBOTTOMRIGHT = 13, 14, 16, 17
    if top and left:
        return HTTOPLEFT
    if top and right:
        return HTTOPRIGHT
    if bottom and left:
        return HTBOTTOMLEFT
    if bottom and right:
        return HTBOTTOMRIGHT
    if left:
        return HTLEFT
    if right:
        return HTRIGHT
    if top:
        return HTTOP
    if bottom:
        return HTBOTTOM
    return 1
