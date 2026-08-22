# -*- coding: utf-8 -*-
"""
下载指示器:窗口左下角(状态栏左端)的圆形 ⬇ 按钮 + 外圈环形进度条。
- 下载中:显示并实时画进度弧
- 点击:弹出下载详情对话框(本次下载的状态消息流 + 进度)
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class DownloadIndicator(QWidget):
    """圆形下载按钮:中间 ⬇ 箭头,外圈环形进度条"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._maximum = 1
        self.setFixedSize(42, 42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("下载中,点击查看详情")
        self.setStyleSheet("background: transparent;")

    def set_progress(self, done: int, total: int):
        self._value = max(done, 0)
        self._maximum = max(total, 1)
        self.update()

    def set_active(self, active: bool):
        """active=False 时画成普通状态(无环/灰色),用于下载完成/空闲"""
        self._active = active
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(3, 3, -3, -3)
        # 背景环
        p.setPen(QPen(QColor(190, 190, 190, 120), 4))
        p.drawEllipse(rect)
        # 进度弧(从 12 点方向顺时针)
        if self._maximum > 0:
            ratio = max(0.0, min(1.0, self._value / self._maximum))
            span = int(360 * ratio)
            if span > 0:
                pen = QPen(QColor("#3E7CB1"), 4, cap=Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawArc(rect, 90 * 16, -span * 16)
        # 中间 ⬇ 箭头
        p.setPen(QPen(QColor("#3E7CB1"), 1))
        font = p.font()
        font.setPixelSize(17)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "⬇")
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            e.accept()


class DownloadDetailDialog(QDialog):
    """下载详情:状态消息流 + 当前进度"""

    def __init__(self, log_lines: list, done: int = 0, total: int = 1, parent=None):
        super().__init__(parent)
        self.setWindowTitle("下载详情")
        self.setMinimumSize(460, 320)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        for line in log_lines:
            self.log_view.appendPlainText(line)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)
        self.progress_label = QLabel(f"{done} / {total}")

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addWidget(QLabel("进度:"))
        row.addWidget(self.progress_bar, 1)
        row.addWidget(self.progress_label)
        row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("下载内容:"))
        layout.addWidget(self.log_view, 1)
        layout.addLayout(row)
