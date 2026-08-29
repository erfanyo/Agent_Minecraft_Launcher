# -*- coding: utf-8 -*-
"""
轻量动画工具:统一时长/easing 的 QPropertyAnimation 封装(阶段 3 · 方案§7)。

- 原则:短(150~320ms)、统一 easing(OutCubic)、只作用于少量顶层控件、可一键关闭
  (ui_animations_enabled)。
- 不引第三方库;QPainter 自绘控件(下载环 / Mod 依赖力导向图)继续用 QTimer 节流,不走这里。
- 时长/easing 读 ui_tokens.DURATION / EASING。
"""
from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect

from ui_tokens import DURATION, EASING

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


def is_animations_enabled() -> bool:
    return _ANIMATIONS_ENABLED


def _easing():
    return _EASING_MAP.get(EASING, QEasingCurve.Type.OutCubic)


def _animate_opacity(widget, start: float, end: float, duration_ms: int, on_done=None):
    """对 widget 做透明度动画(start→end)。动画关闭时直接跳到终态。"""
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
