"""Windows keyboard input targeted to one explicitly supplied game PID."""
import ctypes
from ctypes import wintypes
import os
import time


def window_for_pid(pid):
    if os.name != 'nt':
        raise RuntimeError('Automatic game keyboard input currently requires Windows')
    api = ctypes.WinDLL('user32', use_last_error=True)
    api.IsWindowVisible.argtypes = [wintypes.HWND]
    api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    api.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, unused):
        value = wintypes.DWORD()
        api.GetWindowThreadProcessId(hwnd, ctypes.byref(value))
        if value.value == pid and api.IsWindowVisible(hwnd):
            name = ctypes.create_unicode_buffer(256)
            api.GetClassNameW(hwnd, name, len(name))
            if name.value.startswith(('GLFW', 'LWJGL')):
                found.append(hwnd)
        return True
    callback = callback_type(visit)
    api.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    api.EnumWindows(callback, 0)
    if len(found) != 1:
        raise RuntimeError(f'Expected one visible window for test PID {pid}; found {len(found)}')
    return found[0]


def send_chat(pid, text, method='message'):
    hwnd = window_for_pid(pid)
    api = ctypes.WinDLL('user32', use_last_error=True)
    api.SetForegroundWindow.argtypes = [wintypes.HWND]
    api.GetForegroundWindow.restype = wintypes.HWND
    api.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    api.SetForegroundWindow(hwnd)
    if api.GetForegroundWindow() != hwnd:
        raise RuntimeError('Cannot focus test game; no keys were sent')
    if method == 'message':
        api.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        def post(message, value, flags):
            if not api.PostMessageW(hwnd, message, value, flags):
                raise RuntimeError('Windows rejected targeted game input')
        def virtual_key(code):
            scan = api.MapVirtualKeyW(code, 0)
            post(0x0100, code, 1 | (scan << 16))
            time.sleep(.08)
            post(0x0101, code, 1 | (scan << 16) | (1 << 30) | (1 << 31))
        virtual_key(0x54)
        time.sleep(.25)
        encoded = text.encode('utf-16-le')
        for offset in range(0, len(encoded), 2):
            post(0x0102, int.from_bytes(encoded[offset:offset+2], 'little'), 1)
        virtual_key(0x0D)
        return
    class Keyboard(ctypes.Structure):
        _fields_ = [('vk', wintypes.WORD), ('scan', wintypes.WORD), ('flags', wintypes.DWORD),
                    ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]
    class Mouse(ctypes.Structure):
        _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG), ('data', wintypes.DWORD),
                    ('flags', wintypes.DWORD), ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]
    class Payload(ctypes.Union):
        _fields_ = [('keyboard', Keyboard), ('mouse', Mouse)]
    class Input(ctypes.Structure):
        _fields_ = [('type', wintypes.DWORD), ('payload', Payload)]
    api.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
    api.SendInput.restype = wintypes.UINT
    def emit(events):
        if api.GetForegroundWindow() != hwnd:
            raise RuntimeError('Test window lost focus; refusing keyboard input')
        inputs = (Input * len(events))(*(Input(1, Payload(keyboard=event)) for event in events))
        if api.SendInput(len(inputs), inputs, ctypes.sizeof(Input)) != len(inputs):
            raise RuntimeError('Windows rejected simulated keyboard input')
    def key(code):
        scan = api.MapVirtualKeyW(code, 0)
        emit([Keyboard(0, scan, 8, 0, 0)])
        time.sleep(.08)
        emit([Keyboard(0, scan, 10, 0, 0)])
    key(0x54)  # T opens the chat box; the test world must already be loaded.
    time.sleep(.25)  # Chat-open animation only; assertions use protocol state.
    encoded = text.encode('utf-16-le')
    for offset in range(0, len(encoded), 2):
        unit = int.from_bytes(encoded[offset:offset+2], 'little')
        emit([Keyboard(0, unit, 4, 0, 0), Keyboard(0, unit, 6, 0, 0)])
    key(0x0D)


def capture_window(pid, destination):
    # Screen capture can include an overlapping application. Only capture when
    # the explicitly targeted game is the foreground window.
    api = ctypes.WinDLL('user32', use_last_error=True)
    api.GetForegroundWindow.restype = wintypes.HWND
    hwnd = window_for_pid(pid)
    if api.GetForegroundWindow() != hwnd:
        return False
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    return app.primaryScreen().grabWindow(hwnd).save(str(destination))


def click_client(pid, x_fraction, y_fraction):
    """Click inside the explicitly targeted game's client area only."""
    hwnd = window_for_pid(pid)
    api = ctypes.WinDLL('user32', use_last_error=True)
    api.SetForegroundWindow.argtypes = [wintypes.HWND]
    api.GetForegroundWindow.restype = wintypes.HWND
    api.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    api.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    api.SetForegroundWindow(hwnd)
    if api.GetForegroundWindow() != hwnd:
        raise RuntimeError('Cannot focus test game; no click was sent')
    rect = wintypes.RECT()
    api.GetClientRect(hwnd, ctypes.byref(rect))
    x, y = int(rect.right * x_fraction), int(rect.bottom * y_fraction)
    position = x | (y << 16)
    api.PostMessageW(hwnd, 0x0200, 0, position)
    api.PostMessageW(hwnd, 0x0201, 1, position)
    time.sleep(.1)
    api.PostMessageW(hwnd, 0x0202, 0, position)


def close_window(pid):
    hwnd = window_for_pid(pid)
    api = ctypes.WinDLL('user32', use_last_error=True)
    api.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    if not api.PostMessageW(hwnd, 0x0010, 0, 0):
        raise RuntimeError('Could not request normal test game shutdown')


def press_key(pid, code):
    hwnd = window_for_pid(pid)
    api = ctypes.WinDLL('user32', use_last_error=True)
    api.SetForegroundWindow.argtypes = [wintypes.HWND]
    api.GetForegroundWindow.restype = wintypes.HWND
    api.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    api.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    api.SetForegroundWindow(hwnd)
    if api.GetForegroundWindow() != hwnd:
        raise RuntimeError('Cannot focus test game; no key was sent')
    scan = api.MapVirtualKeyW(code, 0)
    api.PostMessageW(hwnd, 0x0100, code, 1 | (scan << 16))
    time.sleep(.1)
    api.PostMessageW(hwnd, 0x0101, code, 1 | (scan << 16) | (1 << 30) | (1 << 31))


def system_close(pid):
    """Ask Windows to close the foreground test game with Alt+F4."""
    hwnd = window_for_pid(pid)
    api = ctypes.WinDLL('user32', use_last_error=True)
    api.SetForegroundWindow.argtypes = [wintypes.HWND]
    api.GetForegroundWindow.restype = wintypes.HWND
    api.SetForegroundWindow(hwnd)
    class Keyboard(ctypes.Structure):
        _fields_ = [('vk', wintypes.WORD), ('scan', wintypes.WORD), ('flags', wintypes.DWORD),
                    ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]
    class Payload(ctypes.Union):
        _fields_ = [('keyboard', Keyboard), ('padding', ctypes.c_byte * 32)]
    class Input(ctypes.Structure):
        _fields_ = [('type', wintypes.DWORD), ('payload', Payload)]
    api.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
    if api.GetForegroundWindow() != hwnd:
        raise RuntimeError('Cannot focus test game; no system shortcut sent')
    events=(Input * 4)(*(Input(1,Payload(keyboard=Keyboard(vk,0,flags,0,0)))
        for vk,flags in ((0x12,0),(0x73,0),(0x73,2),(0x12,2))))
    if api.SendInput(4,events,ctypes.sizeof(Input)) != 4:
        raise RuntimeError('Windows rejected test game close shortcut')
