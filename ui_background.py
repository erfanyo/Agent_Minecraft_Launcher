# -*- coding: utf-8 -*-
"""
背景引擎(阶段 2):主窗口壁纸 + 可读性遮罩 + 壁纸源管理。

- BackgroundWidget:主窗口内容区背景,重写 paintEvent 画壁纸(cover 缩放)+ 遮罩。
  **只用 paintEvent,不给父控件 setStyleSheet**(避免 v0.4.2「父控件 QSS 接管子控件渲染」教训)。
- 壁纸源三选一:
  1. 预设 —— 代码生成渐变/纯色(零版权、零网络、零体积);
  2. 用户本地图片 —— 文件选择器选后**复制进** AMCL/cache/wallpapers/(遵循文件放置约定);
  3. 官方壁纸 —— 首启下载到 AMCL/cache/wallpapers/(素材待项目方提供,离线自动降级到预设)。
- 遮罩:深色模式用深色遮罩、浅色模式用浅色遮罩,强度 0~80%(默认深 60 / 浅 50)。
- 决策 2:壁纸激活时,ui_tokens 把半透明面板底(panel_bg)抬高到近不透明,保证文字对比度。

**边界**:不改窗口框架(标题栏/菜单栏不动)、不改实例目录、不写用户目录(唯一例外 paths 退回)。
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from ui_tokens import is_dark_mode

# ---------------- 预设壁纸(代码生成,无版权) ----------------
# 渐变 (起色, 止色)。取 MC 意象的青绿/草绿/石灰 + 克制的深灰/浅灰。
PRESETS = {
    "slate":        ("#23272f", "#2b2f3a"),   # 克制深灰(默认,近原生)
    "teal":         ("#1f3a3a", "#2E8B8B"),   # MC 矿物青绿
    "grass":        ("#24301c", "#4a7c2e"),   # MC 草绿
    "lime":         ("#33351f", "#8a9a3a"),   # MC 石灰
    "deepslate":    ("#1a1f2a", "#2e5a7a"),   # 深板岩蓝
    "slate_light":  ("#eef1f5", "#dfe5ec"),   # 浅色预设(浅色主题用)
}
DEFAULT_PRESET = "teal"

# 遮罩默认强度(0~1):深色 0.6 / 浅色 0.5(见《阶段0基线报告》§三)
DEFAULT_MASK_DARK = 0.6
DEFAULT_MASK_LIGHT = 0.5

# 超大图先降采样的阈值(长边像素;超 4K 先缩小省内存)
_MAX_SIDE = 4096


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


def _load_pixmap(path: str) -> QPixmap | None:
    """从磁盘加载图片并降采样(超 4K 先缩小)。失败返回 None。"""
    if not path or not os.path.isfile(path):
        return None
    try:
        img = QPixmap(path)
    except Exception:
        return None
    if img.isNull():
        return None
    # 超 4K 降采样
    mx = max(img.width(), img.height())
    if mx > _MAX_SIDE:
        ratio = _MAX_SIDE / mx
        img = img.scaled(max(1, int(img.width() * ratio)),
                         max(1, int(img.height() * ratio)),
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return img


def preset_pixmap(preset_id: str, size=(1600, 900)) -> QPixmap:
    """生成预设渐变壁纸(代码绘制,无版权)。"""
    c1, c2 = PRESETS.get(preset_id, PRESETS[DEFAULT_PRESET])
    w, h = size
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0.0, QColor(c1))
    g.setColorAt(1.0, QColor(c2))
    p.fillRect(0, 0, w, h, g)
    p.end()
    return pm


def load_wallpaper(settings: dict) -> QPixmap | None:
    """按设置加载当前壁纸(返回 QPixmap;无壁纸/加载失败返回 None)。
    设置键:ui_wallpaper_source(none/preset/official/user) + 各源对应键。"""
    src = (settings or {}).get("ui_wallpaper_source", "none") or "none"
    if src == "preset":
        return preset_pixmap((settings or {}).get("ui_wallpaper_preset", DEFAULT_PRESET))
    if src == "user":
        rel = (settings or {}).get("ui_wallpaper_user_path", "")
        if rel:
            from paths import cache_dir
            return _load_pixmap(os.path.join(cache_dir(), rel))
        return None
    if src == "official":
        # 官方壁纸(首启下载):素材由项目方提供;未下载则回退预设(离线降级)。
        from paths import cache_dir
        oid = (settings or {}).get("ui_wallpaper_official_id", "")
        if oid:
            p = _load_pixmap(os.path.join(cache_dir(), "wallpapers", f"official_{oid}.png"))
            if p is not None:
                return p
        # 降级:官方不可用 → 预设
        return preset_pixmap((settings or {}).get("ui_wallpaper_preset", DEFAULT_PRESET))
    return None


def mask_strength(settings: dict) -> float:
    """当前遮罩强度(0~1)。设置 ui_wallpaper_mask 存 0~80 的百分比;未设取默认(深 0.6 / 浅 0.5)。"""
    v = (settings or {}).get("ui_wallpaper_mask", None)
    if v is None:
        return DEFAULT_MASK_DARK if is_dark_mode() else DEFAULT_MASK_LIGHT
    try:
        return max(0.0, min(1.0, float(v) / 100.0))
    except Exception:
        return DEFAULT_MASK_DARK if is_dark_mode() else DEFAULT_MASK_LIGHT


class BackgroundWidget(QWidget):
    """主窗口内容区背景:画壁纸(cover)+ 遮罩。无壁纸时完全透明(默认底色透出)。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = None       # 原始壁纸 QPixmap(未缩放)
        self._scaled = None       # 已 cover 缩放到当前尺寸的缓存
        self._mask = 0.6
        self._enabled = False

    def set_wallpaper(self, pixmap: QPixmap | None, mask: float = 0.6) -> None:
        """设置壁纸与遮罩强度(0~1)。pixmap 为 None = 关闭背景。"""
        self._source = pixmap
        self._mask = max(0.0, min(1.0, mask))
        self._enabled = pixmap is not None and not pixmap.isNull()
        self._scaled = None
        self.update()

    def clear(self) -> None:
        self.set_wallpaper(None)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._scaled = None   # 尺寸变了,重算 cover 缓存
        self.update()

    def paintEvent(self, _e):
        if not self._enabled or self._source is None:
            return   # 透明:让窗口默认底色透出
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # cover 缩放缓存
        if self._scaled is None or self._scaled.size() != self.size():
            self._scaled = _cover_scale(self._source, self.size())
        if self._scaled is not None:
            p.drawPixmap(0, 0, self._scaled)
        # 可读性遮罩(深浅色自动换遮罩色)
        if self._mask > 0.0:
            c = mask_color()
            c.setAlphaF(self._mask)
            p.fillRect(self.rect(), c)
        p.end()
