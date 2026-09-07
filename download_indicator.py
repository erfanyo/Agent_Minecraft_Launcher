# -*- coding: utf-8 -*-
"""
下载指示器:窗口左下角(状态栏左端)的圆形 ⬇ 按钮 + 外圈环形进度条。
- 下载中:显示并实时画进度弧
- 点击:弹出下载详情对话框(本次下载的状态消息流 + 进度)
"""
from PySide6.QtCore import QPointF, Qt, Signal, QVariantAnimation, QEasingCurve
from ui_style import current_color, accent_color, danger_color, success_color
from ui_anim import is_animations_enabled, track_animation
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
        self._completed = False
        self._failed = False
        self._dragging = None      # 悬浮球拖动偏移
        self._hover = 0.0
        self._hover_anim = QVariantAnimation(self)
        track_animation(self._hover_anim)
        self._hover_anim.setDuration(120)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._set_hover)
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
        # 新任务一开始就恢复为下载箭头；完成态由调用方明确设置，避免
        # 某些任务的 1/1 初始进度被误判为“已经完成”。
        self._completed = False
        self._failed = False
        self.update()

    def set_completed(self, completed: bool = True):
        """设置任务成功完成态：绿色勾替代下载箭头。"""
        self._completed = bool(completed)
        self._failed = False
        self.update()

    def set_failed(self, failed=True):
        self._failed = bool(failed)
        if failed:
            self._completed = False
        self.update()

    def set_active(self, active: bool):
        self._active = active
        self.update()

    def _set_hover(self, value):
        self._hover = float(value)
        self.update()

    def _animate_hover(self, target):
        self._hover_anim.stop()
        if not is_animations_enabled():
            self._set_hover(target)
            return
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def enterEvent(self, event):
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(3, 3, -3, -3)
        # 复用主题按钮底色与强调色，深浅色和自定义配色保持一致。
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(current_color('btn_bg_pressed' if self._dragging is not None else 'btn_bg')))
        p.drawEllipse(rect)
        tint = QColor(accent_color())
        tint.setAlphaF(0.10 * self._hover)
        p.setBrush(tint)
        p.drawEllipse(rect)
        # 背景环
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(current_color('btn_border')), 2))
        p.drawEllipse(rect)
        # 进度弧(从 12 点方向顺时针)
        if self._maximum > 0:
            ratio = max(0.0, min(1.0, self._value / self._maximum))
            span = max(int(360 * ratio), 2)
            if ratio > 0:
                pen = QPen(QColor(danger_color() if self._failed else success_color() if self._completed else accent_color()), 3)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawArc(rect, 90 * 16, -span * 16)
        if self._failed:
            pen = QPen(QColor(danger_color()), 2.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            cx, cy = self.width() / 2, self.height() / 2
            p.drawLine(QPointF(cx - 6, cy - 6), QPointF(cx + 6, cy + 6))
            p.drawLine(QPointF(cx - 6, cy + 6), QPointF(cx + 6, cy - 6))
            p.end()
            return
        if self._completed:
            # 成功完成后给一个一眼能读懂的静态结果，不再像还在下载。
            pen = QPen(QColor(success_color()), 2.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            cx, cy = self.width() / 2, self.height() / 2
            p.drawLine(QPointF(cx - 7, cy), QPointF(cx - 2, cy + 5))
            p.drawLine(QPointF(cx - 2, cy + 5), QPointF(cx + 7, cy - 5))
            p.end()
            return

        # 中间传统向下箭头(和 AI 面板"发送↑"同款但方向相反)
        cx = self.width() / 2
        cy = self.height() / 2
        pen = QPen(QColor(accent_color()), 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(cx, cy - 7), QPointF(cx, cy + 3))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(accent_color()))
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
            self.update()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._dragging is not None:
            self.move(e.globalPosition().toPoint() - self._dragging)
            e.accept()

    def mouseReleaseEvent(self, e):
        if self._dragging is not None:
            dist = (e.globalPosition().toPoint() - self._press_pos).manhattanLength()
            self._dragging = None
            self.update()
            if dist < 6:      # 基本没动 → 视为点击
                self.clicked.emit()
            e.accept()


class DownloadDetailWidget(QWidget):
    """下载详情内容(状态消息流 + 进度条),供 ContentOverlay 覆盖层承载(不再是对话框)。

    live: 可选 callable,返回 (log_lines, done, total);提供时用 QTimer 周期性刷新,
    这样下载/整合包导入过程中打开详情,能看到实时进度而不是打开时的快照。"""

    def __init__(self, log_lines: list, done: int = 0, total: int = 1, parent=None,
                 live=None, cancel=None, retry=None, running=None, retryable=None):
        super().__init__(parent)
        self._live = live
        self._running = running
        self._retryable = retryable

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        for line in log_lines:
            self.log_view.appendPlainText(line)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)
        self.progress_label = QLabel(f"{done} / {total}")

        row = QHBoxLayout()
        row.addWidget(QLabel("进度:"))
        row.addWidget(self.progress_bar, 1)
        row.addWidget(self.progress_label)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("下载内容:"))
        layout.addWidget(self.log_view, 1)
        layout.addLayout(row)
        actions = QHBoxLayout()
        self.cancel_btn = QPushButton("取消下载")
        self.retry_btn = QPushButton("重试下载")
        self.retry_btn.setToolTip("重新执行本次任务；已校验的文件会复用，不用全部重下")
        for button, callback in ((self.cancel_btn, cancel), (self.retry_btn, retry)):
            button.setVisible(callback is not None)
            if callback:
                button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)

        if self._live is not None:
            from PySide6.QtCore import QTimer
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._refresh)
            self._timer.start(500)

    def _refresh(self):
        try:
            if self._running:
                running = self._running()
                self.cancel_btn.setEnabled(running)
                self.retry_btn.setEnabled(self._retryable() if self._retryable else not running)
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
