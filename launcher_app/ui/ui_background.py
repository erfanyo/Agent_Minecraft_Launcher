# -*- coding: utf-8 -*-
"""
背景引擎(阶段 2):主窗口壁纸 + 可读性遮罩 + 壁纸源管理。

- BackgroundWidget:主窗口内容区背景,重写 paintEvent 画壁纸(cover 缩放)+ 遮罩。
  **只用 paintEvent,不给父控件 setStyleSheet**(避免 v0.4.2「父控件 QSS 接管子控件渲染」教训)。
- 壁纸源:随包内置截图、代码生成的预设渐变、用户本地图片和旧版官方缓存。
- 遮罩:深色模式用深色遮罩、浅色模式用浅色遮罩,强度 0~80%(默认深 60 / 浅 50)。
- 决策 2:壁纸激活时,ui_tokens 把半透明面板底(panel_bg)抬高到近不透明,保证文字对比度。

**边界**:不改窗口框架(标题栏/菜单栏不动)、不改实例目录、不写用户目录(唯一例外 paths 退回)。
"""
from __future__ import annotations
from launcher_app.core.i18n import t
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from launcher_app.ui.ui_tokens import is_dark_mode
from launcher_app.ui.wallpaper_assets import (
    PRESETS, DEFAULT_PRESET, BUNDLED_WALLPAPER, bundled_wallpaper_path,
    preset_pixmap, blur_strength, load_wallpaper, prepare_shared_wallpaper,
)

# 遮罩默认强度(0~1):深色 0.55 / 浅色 0.65。
DEFAULT_MASK_DARK = 0.55
DEFAULT_MASK_LIGHT = 0.65

def mask_color() -> QColor:
    """当前模式的遮罩色:深色=黑、浅色=白(随主题自动换)。"""
    return QColor(0, 0, 0) if is_dark_mode() else QColor(255, 255, 255)


def _cover_scale(src: QPixmap, size) -> QPixmap | None:
    """cover 缩放:等比放大到铺满 size,再居中裁剪。失败返回 None。"""
    sw, sh = src.width(), src.height()
    tw, th = size.width(), size.height()
    if sw <= 0 or sh <= 0 or tw <= 0 or th <= 0:
        return None
    scale = max(tw / sw, th / sh)
    nw = max(1, int(sw * scale))
    nh = max(1, int(sh * scale))
    scaled = src.scaled(nw, nh, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
    return scaled.copy((nw - tw) // 2, (nh - th) // 2, tw, th)


def mask_strength(settings: dict) -> float:
    """当前遮罩强度(0~1)。未自定义时深色 0.55、浅色 0.65。"""
    v = (settings or {}).get("ui_wallpaper_mask", None)
    if v is None:
        return DEFAULT_MASK_DARK if is_dark_mode() else DEFAULT_MASK_LIGHT
    try:
        return max(0.0, min(1.0, float(v) / 100.0))
    except Exception:
        return DEFAULT_MASK_DARK if is_dark_mode() else DEFAULT_MASK_LIGHT


def input_style_qss() -> str:
    """壁纸模式下文本框/下拉框/列表的透明化 QSS(深/浅自适应)。
    文本框/下拉/列表默认走 QPalette(不透明),这里用全局 QSS 把它们统一成与面板同档的透明度,
    解决「按钮/文本框/列表是不透明硬块、画面不统一」的问题。"""
    if is_dark_mode():
        bg = "rgba(46,52,62,0.82)"
        base_bg = "rgba(40,46,56,0.94)"
        border = "rgba(170,185,210,0.30)"
        sel = "rgba(91,141,239,0.32)"
    else:
        bg = "rgba(255,255,255,0.86)"
        base_bg = "rgba(255,255,255,0.96)"
        border = "rgba(55,75,105,0.27)"
        sel = "rgba(59,142,234,0.22)"
    # 下拉选项文字必须跟主题(浅色黑/深色白),否则 hover/选中项在浅底上「白底白字」看不清。
    from launcher_app.ui.ui_style import text_color as _tc
    _combo_text = _tc()
    return (
        f"QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{"
        f" background: {bg}; color: {_combo_text}; border: 1px solid {border}; border-radius: 10px; }}"
        f"QComboBox QAbstractItemView {{ background: {base_bg}; selection-background-color: {sel};"
        f" selection-color: {_combo_text}; }}"
        f"QComboBox QAbstractItemView::item {{ color: {_combo_text};"
        f" padding: 5px 10px; }}"
        f"QComboBox QAbstractItemView::item:hover {{ background: {sel}; color: {_combo_text}; }}"
        f"QComboBox QAbstractItemView::item:selected {{ background: {sel}; color: {_combo_text}; }}"
        f"QListWidget, QTreeWidget, QTableWidget {{ background: {base_bg};"
        f" border: 1px solid {border}; border-radius: 10px; }}"
    )


def scroll_surface_qss() -> str:
    """Style the native scrollbar track and the QScrollArea viewport separately.

    On some Linux Qt styles the viewport/track otherwise paints an opaque black
    rectangle even when the content widget itself has a transparent stylesheet.
    """
    from launcher_app.ui.ui_tokens import current_token
    groove = current_token('bg1')
    handle = current_token('btn_border')
    hover = current_token('accent')
    return (
        'QCheckBox, QRadioButton { background: transparent; }'
        'QPlainTextEdit, QTextEdit, QListWidget, QTreeWidget, QTableWidget {'
        ' border-radius: 10px; }'
        'QScrollArea > QWidget { background: transparent; }'
        f'QScrollBar:vertical {{ background: {groove}; width: 10px; margin: 0; }}'
        f'QScrollBar:horizontal {{ background: {groove}; height: 10px; margin: 0; }}'
        f'QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{'
        f' background: {handle}; border-radius: 4px; min-height: 24px; min-width: 24px; }}'
        f'QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{'
        f' background: {hover}; }}'
        'QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; }'
        f'QScrollBar::add-page, QScrollBar::sub-page {{ background: {groove}; }}'
        f'QAbstractScrollArea::corner {{ background: {groove}; }}'
    )


class BackgroundWidget(QWidget):
    """内容区背景:画壁纸 + 遮罩。两种模式:
    - cover 模式(set_wallpaper):壁纸 cover 缩放到自身(独立窗口用)。
    - 共享模式(set_shared_view):按主窗统一的缩放壁纸 + 视口偏移画,让 AI dock 与
      主窗壁纸横向/纵向连续;拆出浮动后随移动切换所显示片段。
    无壁纸时完全透明(默认底色透出)。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = None     # cover 模式:原始壁纸
        self._cover = None      # cover 模式:已缩放缓存
        self._shared = None     # 共享模式:主窗统一的缩放壁纸
        self._vx = 0            # 共享模式视口偏移(缩放坐标)
        self._vy = 0
        self._wrap_shared = False
        self._mask = DEFAULT_MASK_DARK
        self._enabled = False

    def set_wallpaper(self, pixmap: QPixmap | None, mask: float = DEFAULT_MASK_DARK) -> None:
        """cover 模式:壁纸 cover 缩放到自身。pixmap 为 None = 关闭。"""
        self._source = pixmap
        self._mask = max(0.0, min(1.0, mask))
        self._enabled = pixmap is not None and not pixmap.isNull()
        self._cover = None
        self._shared = None
        self._wrap_shared = False
        self.update()

    def set_shared_view(self, scaled: QPixmap | None, vx: int, vy: int,
                        mask: float = DEFAULT_MASK_DARK, *, wrap: bool = False) -> None:
        """共享模式:用主窗统一的缩放壁纸 + 视口偏移。scaled 为 None = 关闭。"""
        self._shared = scaled
        self._vx = int(vx)
        self._vy = int(vy)
        self._wrap_shared = bool(wrap)
        self._mask = max(0.0, min(1.0, mask))
        self._enabled = scaled is not None and not scaled.isNull()
        self._source = None
        self._cover = None
        self.update()

    def clear(self) -> None:
        self.set_wallpaper(None)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._source is not None:
            self._cover = None   # cover 模式:尺寸变了重算
        self.update()

    def paintEvent(self, _e):
        if not self._enabled:
            return   # 透明:让窗口默认底色透出
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self._shared is not None:
            # 浮窗可移出主窗共享画布；重复取样使拖动时仍随相对位置变化。
            # 停靠中的视口仍按原来的边界裁切。
            w, h = self.width(), self.height()
            if self._wrap_shared:
                p.drawTiledPixmap(0, 0, w, h, self._shared, self._vx, self._vy)
            else:
                sx = max(0, min(self._vx, max(0, self._shared.width() - w)))
                sy = max(0, min(self._vy, max(0, self._shared.height() - h)))
                p.drawPixmap(-sx, -sy, self._shared)
        elif self._source is not None:
            # cover 模式:cover 缩放到自身
            if self._cover is None or self._cover.size() != self.size():
                self._cover = _cover_scale(self._source, self.size())
            if self._cover is not None:
                p.drawPixmap(0, 0, self._cover)
        # 可读性遮罩(深浅色自动换遮罩色)
        if self._mask > 0.0:
            c = mask_color()
            c.setAlphaF(self._mask)
            p.fillRect(self.rect(), c)
        p.end()


# ===================== Merged from wallpaper_picker.py =====================
"""Keyboard-accessible wallpaper picker and local-file drop target."""
import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton


class WallpaperDropButton(QPushButton):
    fileDropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__('点击选择图片，或把图片拖到这里', parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(90)
        self.setToolTip(t('支持 PNG、JPG、BMP、WebP；一次选择一张本机图片'))

    @staticmethod
    def local_image(mime):
        urls = mime.urls() if mime.hasUrls() else []
        if len(urls) != 1 or not urls[0].isLocalFile():
            return ''
        path = urls[0].toLocalFile()
        if os.path.isfile(path) and os.path.splitext(path)[1].lower() in {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}:
            return path
        return ''

    def dragEnterEvent(self, event):
        if self.isEnabled() and self.local_image(event.mimeData()):
            self.setDown(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.isEnabled() and self.local_image(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setDown(False)
        event.accept()

    def dropEvent(self, event):
        self.setDown(False)
        path = self.local_image(event.mimeData())
        if self.isEnabled() and path:
            event.acceptProposedAction()
            self.fileDropped.emit(path)
        else:
            event.ignore()


# ===================== Merged from wallpaper_picker.py =====================
"""Keyboard-accessible wallpaper picker and local-file drop target."""
import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton


class WallpaperDropButton(QPushButton):
    fileDropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__('点击选择图片，或把图片拖到这里', parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(90)
        self.setToolTip(t('支持 PNG、JPG、BMP、WebP；一次选择一张本机图片'))

    @staticmethod
    def local_image(mime):
        urls = mime.urls() if mime.hasUrls() else []
        if len(urls) != 1 or not urls[0].isLocalFile():
            return ''
        path = urls[0].toLocalFile()
        if os.path.isfile(path) and os.path.splitext(path)[1].lower() in {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}:
            return path
        return ''

    def dragEnterEvent(self, event):
        if self.isEnabled() and self.local_image(event.mimeData()):
            self.setDown(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.isEnabled() and self.local_image(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setDown(False)
        event.accept()

    def dropEvent(self, event):
        self.setDown(False)
        path = self.local_image(event.mimeData())
        if self.isEnabled() and path:
            event.acceptProposedAction()
            self.fileDropped.emit(path)
        else:
            event.ignore()
