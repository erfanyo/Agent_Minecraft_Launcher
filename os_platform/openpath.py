# -*- coding: utf-8 -*-
"""跨平台打开文件 / 文件夹(os_platform 模块)。

替代 Windows 专用的 `os.startfile`(在 macOS/Linux 会 AttributeError)。
- Windows:os.startfile
- macOS:  open <path>
- Linux:  xdg-open <path>

其余(打开 URL)仍用 Qt 的 QDesktopServices.openUrl(它已跨平台,不在此重复)。
"""
import os
import shutil
import subprocess

from .system import is_macos, is_windows


def open_path(path: str) -> bool:
    """用系统默认程序打开一个文件/文件夹。成功返回 True,失败返回 False(不抛异常)。

    兼容 Windows(mac/linux 无 os.startfile),错误静默(打开失败不干扰主流程)。
    """
    if not path:
        return False
    path = os.path.abspath(path)
    try:
        if is_windows():
            os.startfile(path)
            return True
        opener = _opener_cmd()
        if opener:
            subprocess.Popen([opener, path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except Exception:
        pass
    return False


def _opener_cmd() -> str | None:
    """返回当前平台打开文件用的命令名(mac:open / linux:xdg-open),None=未知。"""
    if is_macos():
        return shutil.which("open") or "open"
    if not is_windows():
        return shutil.which("xdg-open") or "xdg-open"
    return None
