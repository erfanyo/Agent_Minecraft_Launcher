# -*- coding: utf-8 -*-
"""
引导式教程(演示):spotlight 遮罩 + 箭头 + 说明气泡 + 上一步/下一步/跳过。

**模块化**:步骤数据 = {route, arrow, text}(见 GuideDriver.DEMO/最终放 tutorial_steps)。
框架只按数据把"遮罩/箭头/气泡"画到目标控件上;UI 改了只改 route(见 ui_route.py)。
"""
import math

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal, QObject, QPointF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QBrush, QPolygonF
from PySide6.QtWidgets import (
    QDialog, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget,
)

import ui_route


def _window_global_geom(w):
    top_left = w.mapToGlobal(QPoint(0, 0))
    return QRect(top_left, w.size())


class GuideOverlay(QWidget):
    """半透明 spotlight 遮罩:调暗目标窗口,在目标控件处挖洞高亮,画箭头+气泡+控制条。"""

    def __init__(self, host_window, parent=None):
        super().__init__(parent)   # 顶层窗口(无父),定位在 host_window 上方
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._host = host_window
        self._target_rect = None       # 目标控件在遮罩坐标系内的矩形
        self._arrow = "below"
        self._text = ""
        self._bubble_rect = None
        self.on_next = None
        self.on_prev = None
        self.on_skip = None
        self._first = True
        self._last = True
        self._build_controls()
        self.setGeometry(_window_global_geom(host_window))

    def _build_controls(self):
        self.skip_btn = QPushButton("跳过", self)
        self.prev_btn = QPushButton("上一步", self)
        self.next_btn = QPushButton("下一步", self)
        for b in (self.skip_btn, self.prev_btn, self.next_btn):
            b.setFixedHeight(30)
            b.setStyleSheet(
                "QPushButton{background:#2a3240;color:#e8ecf2;border:1px solid #3a4556;"
                "border-radius:14px;padding:0 14px;} QPushButton:hover{background:#3a4556;}")
        self.skip_btn.clicked.connect(lambda: self.on_skip and self.on_skip())
        self.prev_btn.clicked.connect(lambda: self.on_prev and self.on_prev())
        self.next_btn.clicked.connect(lambda: self.on_next and self.on_next())

    def show_step(self, target_global_rect, arrow, text, first, last):
        tl = self.geometry().topLeft()
        self._target_rect = QRect(target_global_rect.topLeft() - tl, target_global_rect.size())
        self._arrow = arrow or "below"
        self._text = text
        self._first, self._last = first, last
        self.update()
        self._layout_controls()

    def _layout_controls(self):
        w, h = self.width(), self.height()
        x = w - 360
        self.skip_btn.move(x, h - 40)
        self.next_btn.move(w - 110, h - 40)
        self.prev_btn.move(w - 210, h - 40)
        self.skip_btn.setText("完成" if self._last else "跳过")

    def mousePressEvent(self, event):
        """在遮罩区域(除按钮外的任意处)左键 → 进入下一步。"""
        if (event.button() == Qt.MouseButton.LeftButton
                and self._target_rect is not None and self.on_next):
            # 点到遮罩本体(按钮是子控件,会自己处理,不会走到这里)
            self.on_next()
            return
        super().mousePressEvent(event)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 1) 调暗除了目标洞以外的区域
        dim = QPainterPath()
        dim.addRect(QRectF(self.rect()))
        if self._target_rect:
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(self._target_rect).adjusted(-4, -4, 4, 4), 8, 8)
            dim = dim.subtracted(hole)
        p.fillPath(dim, QColor(0, 0, 0, 130))
        # 2) 目标控件外框高亮
        if self._target_rect:
            p.setPen(QPen(QColor(90, 141, 239, 220), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self._target_rect).adjusted(-4, -4, 4, 4), 8, 8)
        # 3) 箭头 + 气泡说明
        if self._text and self._target_rect:
            self._draw_bubble_and_arrow(p)

    def _draw_bubble_and_arrow(self, p):
        tr = self._target_rect
        if tr is None:
            return
        # 气泡宽度:固定 300,但窗口太窄时收窄,保证不超出窗口
        W = min(300, max(120, self.width() - 16))
        fm = p.fontMetrics()
        # 精确按文本排版算高度(中文换行/宽字符都按真实排版)
        text_rect = fm.boundingRect(
            QRect(0, 0, W - 28, 10000),
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
            self._text)
        H = max(52, text_rect.height() + 20)
        # 上限:不超过窗口可用高度(给底部控制条留 48)
        H = min(H, self.height() - 48 - 8)

        def _place_below():
            bx = tr.center().x() - W // 2
            by = tr.bottom() + 18
            return bx, by

        def _place_above():
            bx = tr.center().x() - W // 2
            by = tr.top() - H - 18
            return bx, by

        bx, by = _place_below()
        # 下方放不下 → 放上方(目标上方有足够空间时)
        if by + H > self.height() - 48 and tr.top() - H - 18 >= 8:
            bx, by = _place_above()
        # 上下都不行(目标几乎占满窗口)→ 放窗口内安全区(紧贴底部控制条上方)
        if by + H > self.height() - 48 or by < 8:
            by = max(8, self.height() - H - 48 - 8)
        # 水平 clamp 到窗口内
        bx = max(8, min(bx, self.width() - W - 8))
        bubble = QRect(bx, by, W, H)
        self._bubble_rect = bubble
        # 气泡背景
        p.setPen(QPen(QColor(42, 50, 64)))
        p.setBrush(QBrush(QColor(30, 37, 48, 235)))
        p.drawRoundedRect(QRectF(bubble), 10, 10)
        # 箭头(从气泡边缘指向目标)
        p.setPen(QPen(QColor(90, 141, 239), 2))
        p.setBrush(QBrush(QColor(80, 120, 230)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        # 文字
        p.setPen(QColor("#e8ecf2"))
        p.setFont(self.font())
        p.drawText(QRectF(bubble).adjusted(14, 10, -14, -10),
                   Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
                   | Qt.TextFlag.TextWordWrap, self._text)
        # 箭头三角(指向目标:气泡在目标下方 → 三角朝上,反之朝下)
        cx = bubble.center().x()
        p.setBrush(QBrush(QColor(90, 141, 239)))
        p.setPen(Qt.PenStyle.NoPen)
        if bubble.bottom() < tr.top():
            p.drawPolygon(QPolygonF([QPointF(cx, bubble.bottom()),
                                     QPointF(cx - 8, bubble.bottom() + 12),
                                     QPointF(cx + 8, bubble.bottom() + 12)]))
        else:
            p.drawPolygon(QPolygonF([QPointF(cx, bubble.top()),
                                     QPointF(cx - 8, bubble.top() - 12),
                                     QPointF(cx + 8, bubble.top() - 12)]))


class GuideDriver(QObject):
    """引导式教程驱动:按步骤列表逐个"指向某控件+说明"。"""

    finished = Signal()

    def __init__(self, main_window, steps):
        super().__init__()
        self.main = main_window
        self.steps = steps or []
        self.idx = 0
        self.overlay = None

    def start(self):
        if not self.steps:
            return
        self.idx = 0
        self._show()

    def _show(self):
        if self.idx < 0 or self.idx >= len(self.steps):
            self.finish()
            return
        st = self.steps[self.idx]
        target, top = ui_route.resolve(self.main, st.get("route", []))
        if target is None:
            # 定位不到:跳过该步
            self.idx += 1
            self._show()
            return
        if self.overlay is None or self.overlay._host is not top:
            if self.overlay is not None:
                self.overlay.close()
            self.overlay = GuideOverlay(top)
        self.overlay.on_next = self.next
        self.overlay.on_prev = self.prev
        self.overlay.on_skip = self.finish
        self.overlay.show()
        TOP = self.overlay
        # 目标控件全局矩形 → 遮罩坐标
        tl = target.mapToGlobal(QPoint(0, 0))
        grect = QRect(tl, target.size())
        TOP.show_step(grect, st.get("arrow", "below"), st.get("text", ""),
                      first=(self.idx == 0),
                      last=(self.idx == len(self.steps) - 1))

        # 目标窗口移动/改尺寸时,让遮罩跟随
        self._sync_geom()

    def _sync_geom(self):
        if self.overlay is not None:
            self.overlay.setGeometry(_window_global_geom(self.overlay._host))
            self.overlay.update()

    def next(self):
        self.idx += 1
        self._show()

    def prev(self):
        self.idx -= 1
        self._show()

    def finish(self):
        if self.overlay is not None:
            self.overlay.close()
            self.overlay = None
        self.finished.emit()
