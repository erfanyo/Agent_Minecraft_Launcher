# -*- coding: utf-8 -*-
"""
下载指示器:窗口左下角(状态栏左端)的圆形 ⬇ 按钮 + 外圈环形进度条。
- 下载中:显示并实时画进度弧
- 点击:弹出下载详情对话框(本次下载的状态消息流 + 进度)
"""
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
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
    """圆形下载按钮:中间向下箭头(矢量绘制),外圈环形进度条"""

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
            span = max(int(360 * ratio), 2)   # 至少画 2°,小进度也能看见
            if ratio > 0:
                pen = QPen(QColor("#3E7CB1"), 4)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawArc(rect, 90 * 16, -span * 16)
        # 中间向下箭头(QPainter 矢量绘制,不依赖 emoji 字体,任何系统都正常显示)
        cx = self.width() / 2
        cy = self.height() / 2
        arrow = QPolygonF([
            QPointF(cx, cy + 7),
            QPointF(cx - 6, cy - 1),
            QPointF(cx + 6, cy - 1),
        ])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#3E7CB1"))
        p.drawPolygon(arrow)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            e.accept()


class DownloadDetailDialog(QDialog):
    """下载详情:状态消息流 + 当前进度(支持 live 回调实时刷新)。

    live: 可选 callable,返回 (log_lines, done, total);提供时用 QTimer 周期性刷新,
    这样下载/整合包导入过程中打开详情,能看到实时进度而不是打开时的快照。"""

    def __init__(self, log_lines: list, done: int = 0, total: int = 1, parent=None,
                 live=None):
        super().__init__(parent)
        self.setWindowTitle("下载详情")
        self.setMinimumSize(460, 320)
        self._live = live

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
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

        if self._live is not None:
            from PySide6.QtCore import QTimer
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._refresh)
            self._timer.start(500)

    def _refresh(self):
        try:
            lines, done, total = self._live()
            n = len(lines)
            # 只在行数变化时全量重设(避免频繁重绘闪烁)
            if n != getattr(self, "_n", -1):
                self.log_view.clear()
                for line in lines:
                    self.log_view.appendPlainText(line)
                self._n = n
            else:
                self.log_view.verticalScrollBar().setValue(
                    self.log_view.verticalScrollBar().maximum())
            self.progress_bar.setMaximum(max(total, 1))
            self.progress_bar.setValue(done)
            self.progress_label.setText(f"{done} / {total}")
        except Exception:
            pass
