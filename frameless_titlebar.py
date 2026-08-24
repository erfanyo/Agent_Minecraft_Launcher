# -*- coding: utf-8 -*-
"""
无边框自定义标题栏(跨平台)。

- 窗口去掉系统边框(setWindowFlags(FramelessWindowHint)),由本标题栏承担:
  拖动移动 / 双击最大化 / 最小化·最大化(还原)·关闭 按钮。
- 布局按平台:
  · macOS:左上角三个"红黄绿灯点"(保留 Mac 样式);启动器名称放**右上角**。
  · Windows / Linux:启动器名称放**左上角**;最小化/最大化/关闭按钮放**右上角**。
- 可插入一个"trailing"控件(如"已有 x 个运行中的实例")放在标题栏合适位置。
"""
import sys

from PySide6.QtCore import Qt, QPoint, QSize
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


def _is_mac() -> bool:
    return sys.platform == "darwin"


class FramelessTitleBar(QWidget):
    def __init__(self, window, title: str = "Agent Minecraft Launcher",
                 trailing_widget: QWidget = None, parent=None):
        super().__init__(parent)
        self._win = window
        self._drag_offset = None
        self.setFixedHeight(36)
        self.setObjectName("framelessTitleBar")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 6, 0)
        lay.setSpacing(6)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("titleLabel")
        self.title_label.setStyleSheet("font-weight: bold; color: #e7ecf5; font-size: 13px;")

        if _is_mac():
            # 三个点(红/黄/绿)在左,启动器名称靠右,trailing 控件也靠右
            lay.addWidget(self._dot("#FF5F57", self._close))
            lay.addWidget(self._dot("#FEBC2E", self._minimize))
            lay.addWidget(self._dot("#28C840", self._maximize))
            lay.addStretch(1)
            if trailing_widget is not None:
                lay.addWidget(trailing_widget)
                lay.addSpacing(8)
            lay.addWidget(self.title_label)
            lay.addSpacing(8)
        else:
            # 左上角名称,右侧 trailing 控件 + 最小化/最大化/关闭
            lay.addWidget(self.title_label)
            lay.addStretch(1)
            if trailing_widget is not None:
                lay.addWidget(trailing_widget)
                lay.addSpacing(6)
            lay.addWidget(self._btn("—", self._minimize, "最小化"))
            lay.addWidget(self._btn("□", self._maximize, "最大化/还原"))
            lay.addWidget(self._btn("✕", self._close, "关闭"))

        # 双击标题栏 → 最大化/还原
        self.setCursor(Qt.CursorShape.ArrowCursor)

    # ---- 控件 ----
    def _dot(self, color: str, fn) -> QPushButton:
        b = QPushButton()
        b.setFixedSize(14, 14)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip("关闭/最小化/最大化")
        b.setStyleSheet(
            f"QPushButton {{ background: {color}; border: none; border-radius: 7px; }}")
        b.clicked.connect(fn)
        return b

    def _btn(self, text: str, fn, tip: str) -> QPushButton:
        b = QPushButton(text)
        b.setFixedSize(38, 28)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip(tip)
        b.setStyleSheet(
            "QPushButton { background: transparent; color: #c6cdd8; border: none;"
            " border-radius: 6px; font-size: 14px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.12); color: #ffffff; }")
        b.clicked.connect(fn)
        return b

    # ---- 窗口操作 ----
    def _minimize(self):
        self._win.showMinimized()

    def _maximize(self):
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()

    def _close(self):
        self._win.close()

    # ---- 拖动移动 + 双击最大化 ----
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self._win.isMaximized():
                return
            self._drag_offset = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self._win.move(e.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_offset = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        self._maximize()
        super().mouseDoubleClickEvent(e)
