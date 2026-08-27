# -*- coding: utf-8 -*-
"""系统通知(os_platform 模块)。

统一"发一条系统通知"的入口——之前散落/未收口。优先用 Qt 托盘
(QSystemTrayIcon.showMessage,跨平台),Qt 不可用或失败时静默降级(不抛异常)。

注意:QSystemTrayIcon 需要持有引用直到消息显示,否则会被 GC。本模块模块级缓存一个图标,避免被回收。
"""
from __future__ import annotations

# 延迟导入 Qt:import os_platform.notify 不应拉 Qt 图形依赖(Linux 无头缺 libEGL 等会崩)。
# 只在真正发通知时才 import PySide6。

_TRAY: "QSystemTrayIcon | None" = None  # 模块级持引用,防 GC


def notify(title: str, message: str, timeout_ms: int = 4000) -> bool:
    """发一条系统级通知。成功返回 True;环境不支持(Qt 缺失/无 GUI)返回 False。

    - Windows:托盘气泡(需系统托盘可用)
    - macOS/Linux:同走 Qt 托盘 showMessage(对 macOS 是原生通知,Linux 视桌面环境)
    """
    try:
        from PySide6.QtWidgets import QApplication, QSystemTrayIcon
        if QApplication.instance() is None or not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        if _tray() is None:
            _make_tray()
        tray = _tray()
        if tray is None:
            return False
        tray.showMessage(title, message,
                         QSystemTrayIcon.MessageIcon.Information, timeout_ms)
        return True
    except Exception:
        return False


def _tray() -> "QSystemTrayIcon | None":
    return _TRAY


def _make_tray() -> None:
    global _TRAY
    try:
        from PySide6.QtGui import QIcon
        _TRAY = QSystemTrayIcon()
        _TRAY.setIcon(QIcon())
    except Exception:
        _TRAY = None
