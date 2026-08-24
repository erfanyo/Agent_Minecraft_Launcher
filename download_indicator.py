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
    """圆形下载球:中间传统下箭头 + 外圈环形进度条。可作为悬浮球(可拖动、置顶)。"""

    clicked = Signal()
    shown = Signal()   # 显示时发出,主窗口据此把悬浮球摆到默认位置

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._maximum = 1
        self._dragging = None      # 悬浮球拖动偏移
        self.setFixedSize(46, 46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("下载中,点击查看详情")

    def make_floating(self):
        """变成悬浮球:无边框、置顶、可拖动的顶层窗(带半透明背景,圆球外观)。"""
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_progress(self, done: int, total: int):
        self._value = max(done, 0)
        self._maximum = max(total, 1)
        self.update()

    def set_active(self, active: bool):
        self._active = active
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(3, 3, -3, -3)
        # 球底(半透明深色圆,悬浮时更像"球")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(30, 37, 48, 235))
        p.drawEllipse(rect)
        # 背景环
        p.setPen(QPen(QColor(190, 190, 190, 120), 4))
        p.drawEllipse(rect)
        # 进度弧(从 12 点方向顺时针)
        if self._maximum > 0:
            ratio = max(0.0, min(1.0, self._value / self._maximum))
            span = max(int(360 * ratio), 2)
            if ratio > 0:
                pen = QPen(QColor("#3E7CB1"), 4)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawArc(rect, 90 * 16, -span * 16)
        # 中间传统向下箭头(和 AI 面板"发送↑"同款但方向相反)
        cx = self.width() / 2
        cy = self.height() / 2
        pen = QPen(QColor("#9fd0f0"), 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(cx, cy - 7), QPointF(cx, cy + 3))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#9fd0f0"))
        head = QPolygonF([
            QPointF(cx - 6, cy + 2),
            QPointF(cx + 6, cy + 2),
            QPointF(cx, cy + 9),
        ])
        p.drawPolygon(head)
        p.end()

    def showEvent(self, e):
        super().showEvent(e)
        self.shown.emit()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            # 悬浮球:按下即进入拖动;单击(无位移)视为点击查看详情
            self._dragging = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press_pos = e.globalPosition().toPoint()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._dragging is not None:
            self.move(e.globalPosition().toPoint() - self._dragging)
            e.accept()

    def mouseReleaseEvent(self, e):
        if self._dragging is not None:
            dist = (e.globalPosition().toPoint() - self._press_pos).manhattanLength()
            self._dragging = None
            if dist < 6:      # 基本没动 → 视为点击
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
