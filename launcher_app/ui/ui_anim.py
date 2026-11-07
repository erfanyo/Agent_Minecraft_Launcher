# -*- coding: utf-8 -*-
"""
轻量动画工具:统一时长/easing 的 QPropertyAnimation 封装(阶段 3 · 方案§7)。

- 原则:短(150~320ms)、统一 easing(OutCubic)、只作用于少量顶层控件、可一键关闭
  (ui_animations_enabled)。
- 不引第三方库;QPainter 自绘控件(下载环 / Mod 依赖力导向图)继续用 QTimer 节流,不走这里。
- 时长/easing 读 ui_tokens.DURATION / EASING。
"""
from PySide6.QtCore import QEvent, QObject, Qt, QEasingCurve, QPropertyAnimation, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton, QApplication, QGraphicsOpacityEffect, QWidget

from launcher_app.ui.ui_tokens import DURATION, EASING
import weakref

_ACTIVE = weakref.WeakSet()


def track_animation(animation):
    _ACTIVE.add(animation)

_ANIMATIONS_ENABLED = True

_EASING_MAP = {
    "OutCubic": QEasingCurve.Type.OutCubic,
    "InOutCubic": QEasingCurve.Type.InOutCubic,
    "OutQuad": QEasingCurve.Type.OutQuad,
    "Linear": QEasingCurve.Type.Linear,
}


def set_animations_enabled(enabled: bool) -> None:
    """全局动画开关(设置 ui_animations_enabled;关闭后动画立即跳到终态)。"""
    global _ANIMATIONS_ENABLED
    _ANIMATIONS_ENABLED = bool(enabled)
    if not enabled:
        for animation in list(_ACTIVE):
            try:
                animation.setCurrentTime(animation.duration())
            except RuntimeError:
                pass


def is_animations_enabled() -> bool:
    return _ANIMATIONS_ENABLED


def _easing():
    return _EASING_MAP.get(EASING, QEasingCurve.Type.OutCubic)


def _animate_opacity(widget, start: float, end: float, duration_ms: int, on_done=None):
    """对 widget 做透明度动画(start→end)。动画关闭时直接跳到终态。"""
    old = getattr(widget, '_ui_anim', None)
    if old is not None:
        try:
            old.stop()
            old.deleteLater()
        except RuntimeError:
            pass
        widget._ui_anim = None
    if not _ANIMATIONS_ENABLED:
        try:
            widget.setGraphicsEffect(None)
        except Exception:
            pass
        if on_done:
            on_done()
        return
    try:
        eff = widget.graphicsEffect()
        if not isinstance(eff, QGraphicsOpacityEffect):
            eff = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(eff)
        eff.setOpacity(start)
        anim = QPropertyAnimation(eff, b"opacity", widget)
        anim.setDuration(duration_ms)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(_easing())

        def _finish():
            try:
                widget.setGraphicsEffect(None)
            except Exception:
                pass
            if on_done:
                on_done()

        anim.finished.connect(_finish)
        widget._ui_anim = anim   # 存引用防 GC
        track_animation(anim)
        anim.start()
    except Exception:
        try:
            widget.setGraphicsEffect(None)
        except Exception:
            pass
        if on_done:
            on_done()


def fade_in(widget, duration_ms: int | None = None, on_done=None) -> None:
    """淡入(0→1)。duration_ms 缺省取 DURATION['fade']。"""
    _animate_opacity(widget, 0.0, 1.0,
                     duration_ms if duration_ms is not None else DURATION.get("fade", 200),
                     on_done)


def fade_out(widget, duration_ms: int | None = None, on_done=None) -> None:
    """淡出(1→0)。"""
    _animate_opacity(widget, 1.0, 0.0,
                     duration_ms if duration_ms is not None else DURATION.get("fade", 200),
                     on_done)


class _FeedbackLayer(QWidget):
    """Animate a tint without offscreen compositing the entire widget subtree."""

    def __init__(self, target):
        super().__init__(target)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.amount = 0.0
        self.color = QColor()
        self.animation = QVariantAnimation(self)
        self.animation.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.animation.valueChanged.connect(self._frame)
        self.animation.finished.connect(self._finished)
        track_animation(self.animation)
        target.installEventFilter(self)
        self.hide()

    def play(self, color, start, end, duration):
        self.animation.stop()
        self.color = QColor(color)
        self.setGeometry(self.parentWidget().rect())
        self.animation.setDuration(duration)
        self.animation.setStartValue(start)
        self.animation.setEndValue(end)
        self._frame(start)
        self.show()
        self.raise_()
        self.animation.start()

    def _frame(self, amount):
        self.amount = float(amount)
        self.update()

    def _finished(self):
        if self.amount <= 0 or not is_animations_enabled():
            self.hide()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        elif event.type() == QEvent.Type.Hide:
            self.animation.stop()
            self.amount = 0.0
            self.hide()
        return False

    def paintEvent(self, event):
        painter = QPainter(self)
        color = QColor(self.color)
        color.setAlphaF(max(0.0, min(1.0, self.amount)))
        painter.fillRect(event.rect(), color)


def _feedback_layer(widget):
    layer = getattr(widget, '_ui_feedback_layer', None)
    if layer is None:
        layer = _FeedbackLayer(widget)
        widget._ui_feedback_layer = layer
    return layer


def reveal(widget):
    """轻微显现，不给整页控件树添加透明度效果或改变布局。"""
    if _ANIMATIONS_ENABLED and widget is not None and widget.isVisible():
        from launcher_app.ui.ui_style import current_color
        _feedback_layer(widget).play(current_color('bg0'), 0.30, 0.0, 220)


class InteractionFeedback(QObject):
    """Give buttons a short press/release response without delaying their actions."""

    def __init__(self, root):
        super().__init__(root)
        self.root = root

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                        QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        if not isinstance(obj, QAbstractButton) or not self.root.isAncestorOf(obj):
            return False
        if not _ANIMATIONS_ENABLED or not obj.isVisible() or not obj.isEnabled():
            return False
        if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            if event.button() != Qt.MouseButton.LeftButton:
                return False
        elif event.key() not in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return False
        if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
            if kind != QEvent.Type.KeyPress or not event.isAutoRepeat():
                obj._interaction_pressed = True
                layer = _feedback_layer(obj)
                layer.play(obj.palette().highlight().color(), layer.amount, 0.18, 85)
        elif getattr(obj, '_interaction_pressed', False):
            if kind == QEvent.Type.KeyRelease and event.isAutoRepeat():
                return False
            obj._interaction_pressed = False
            layer = _feedback_layer(obj)
            layer.play(obj.palette().highlight().color(), layer.amount, 0.0, 160)
        return False


def install_interaction_feedback(root):
    """Install one nonblocking button feedback filter for a window tree."""
    animator = InteractionFeedback(root)
    QApplication.instance().installEventFilter(animator)
    return animator
