# -*- coding: utf-8 -*-
"""OS / 架构检测(os_platform 模块)。

统一收口 `sys.platform` / 标准库 `platform.machine()` 的判断,避免各文件各写一套。
只依赖运行时平台,不触发任何系统调用。
"""
import platform as _plat
import sys


def is_windows() -> bool:
    """是否 Windows"""
    return sys.platform.startswith("win")


def is_macos() -> bool:
    """是否 macOS"""
    return sys.platform == "darwin"


def is_linux() -> bool:
    """是否 Linux(含 WSL)"""
    return sys.platform.startswith("linux")


def current_os_name() -> str:
    """返回 'windows' / 'osx' / 'linux'(与官方 Mojang 规则一致)"""
    if is_windows():
        return "windows"
    if is_macos():
        return "osx"
    return "linux"


def current_arch() -> str:
    """返回架构,如 'x86_64' / 'arm64' / 'aarch64'。amd64 → x86_64 归一化。"""
    a = _plat.machine().lower()
    if a in ("amd64", "x86_64"):
        return "x86_64"
    if a in ("arm64", "aarch64"):
        return "arm64"
    return a or "unknown"


def is_arm() -> bool:
    """是否 ARM 架构(Apple Silicon / 树莓派等)"""
    a = current_arch()
    return a in ("arm64", "aarch64", "armv7l", "armv6l")


def is_wsl() -> bool:
    """是否 Windows Subsystem for Linux(WSL 内运行)"""
    if not is_linux():
        return False
    try:
        with open("/proc/version", "r", encoding="utf-8", errors="replace") as f:
            return "microsoft" in (f.read() or "").lower()
    except OSError:
        return False
