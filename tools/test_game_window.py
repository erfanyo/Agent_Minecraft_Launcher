"""Inspect/interact only with the game PID belonging to an isolated live test."""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import time


def window(root):
    import psutil
    process_meta = json.loads((root / 'process.json').read_text(encoding='utf-8'))
    pid = process_meta['pid']
    process = psutil.Process(pid)
    command = ' '.join(process.cmdline()).lower()
    expected_paths = [str(root).lower()]
    baseline_file = root / 'baseline.json'
    if baseline_file.is_file():
        baseline = json.loads(baseline_file.read_text(encoding='utf-8'))
        instance = process_meta.get('instance') or baseline.get('instance')
        if baseline.get('game_root') and instance:
            expected_paths.append(str(Path(baseline['game_root']) / 'versions' / instance).lower())
    if not any(expected in command for expected in expected_paths):
        raise RuntimeError('PID no longer belongs to the isolated test game')
    handles = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and ctypes.windll.user32.IsWindowVisible(hwnd):
            rect = wintypes.RECT()
            ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect))
            if rect.right > 400 and rect.bottom > 300:
                handles.append(hwnd)
        return True
    ctypes.windll.user32.EnumWindows(callback_type(visit), 0)
    if not handles:
        raise RuntimeError('No visible test-game window')
    return handles[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['capture', 'click', 'key', 'text', 'command', 'close'])
    parser.add_argument('--root', required=True)
    parser.add_argument('--x', type=int, default=0)
    parser.add_argument('--y', type=int, default=0)
    parser.add_argument('--value', default='')
    args = parser.parse_args()
    root = Path(args.root).resolve()
    user = ctypes.windll.user32
    try:
        user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass
    hwnd = window(root)
    user.ShowWindow(hwnd, 9)
    user.SetForegroundWindow(hwnd)
    time.sleep(0.2)
    if args.action == 'click':
        position = (args.y << 16) | (args.x & 0xffff)
        user.PostMessageW(hwnd, 0x200, 0, position)
        user.PostMessageW(hwnd, 0x201, 1, position)
        user.PostMessageW(hwnd, 0x202, 0, position)
    elif args.action == 'key':
        key = int(args.value)
        scan = user.MapVirtualKeyW(key, 0)
        user.PostMessageW(hwnd, 0x100, key, (scan << 16) | 1)
        user.PostMessageW(hwnd, 0x101, key, (scan << 16) | 0xc0000001)
    elif args.action == 'command':
        # Caller first resumes the world. Send only to the validated game window.
        user.PostMessageW(hwnd, 0x100, 0x54, 1)
        user.PostMessageW(hwnd, 0x101, 0x54, 0xc0000001)
        time.sleep(0.2)
        for char in args.value:
            user.PostMessageW(hwnd, 0x102, ord(char), 1)
        time.sleep(0.1)
        user.PostMessageW(hwnd, 0x100, 0x0d, 1)
        user.PostMessageW(hwnd, 0x101, 0x0d, 0xc0000001)
    elif args.action == 'text':
        for char in args.value:
            user.PostMessageW(hwnd, 0x102, ord(char), 1)
    elif args.action == 'close':
        user.PostMessageW(hwnd, 0x10, 0, 0)
    else:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import QPoint
        app = QGuiApplication.instance() or QGuiApplication([])
        rect = wintypes.RECT()
        point = wintypes.POINT(0, 0)
        user.GetClientRect(hwnd, ctypes.byref(rect))
        user.ClientToScreen(hwnd, ctypes.byref(point))
        screen = app.screenAt(QPoint(point.x, point.y)) or app.primaryScreen()
        image = screen.grabWindow(hwnd)
        destination = root / ('screen-' + str(time.time_ns()) + '.png')
        if image.isNull() or not image.save(str(destination)):
            raise RuntimeError('Window capture failed')
        print(destination)
        print('client', rect.right, rect.bottom, 'image', image.width(), image.height())


if __name__ == '__main__':
    main()
