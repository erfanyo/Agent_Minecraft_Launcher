"""Wallpaper assets: source loading, preprocessing and cached pixmaps.

No main-window references or QWidget ownership. QPixmap and the legacy blur
adapter still require the GUI thread; this extraction does not make them async.
"""
from __future__ import annotations
import os
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap

PRESETS = {
    "slate":        ("#2e3440", "#3b4252"),   # 克制中灰(干净的中性灰,替代近黑)
    "teal":         ("#1a4a4a", "#3aa0a0"),   # MC 矿物青绿(更亮更纯)
    "grass":        ("#2a4020", "#5a9440"),   # MC 草绿(更亮更纯)
    "lime":         ("#3a4018", "#94a040"),   # MC 石灰(更亮)
    "deepslate":    ("#1e2a40", "#3a6e9a"),   # 深板岩蓝(更亮)
    "slate_light":  ("#eef1f5", "#dfe5ec"),   # 浅色预设(浅色主题用)
}

DEFAULT_PRESET = "teal"

BUNDLED_WALLPAPER = "-7878592509531134518.png"

def bundled_wallpaper_path() -> str:
    """Locate the shipped image in both source and PyInstaller builds."""
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(root, "assets", BUNDLED_WALLPAPER)

_MAX_SIDE = 4096

def prepare_shared_wallpaper(source: QPixmap, central_size, dock_width: int = 0) -> tuple:
    """把壁纸 cover 缩放到「中央区宽 + 右侧 dock 宽」× 中央区高(一张共享画布)。

    返回 (scaled, ox, oy):ox/oy = 画布左上角在缩放图里的裁剪偏移。
    - 中央区显示 (ox, oy);
    - AI dock 显示 (ox + 相对横移, oy + 相对纵移),横向连续、浮动移动时切片段。

    关键:画布宽度 = 中央 + dock(主窗靠「左右边缘」定宽、dock 靠「上下边缘」定高都
    包得住),不会出现 dock 跑出画布右侧导致的错位/空白。"""
    sw, sh = source.width(), source.height()
    cw, ch = central_size.width(), central_size.height()
    tw = cw + max(0, dock_width)
    th = ch
    if sw <= 0 or sh <= 0 or tw <= 0 or th <= 0:
        return None, 0, 0
    scale = max(tw / sw, th / sh)
    nw = max(1, int(sw * scale))
    nh = max(1, int(sh * scale))
    scaled = source.scaled(nw, nh, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    ox = (nw - tw) // 2
    oy = (nh - th) // 2
    return scaled, ox, oy

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
    g = QLinearGradient(0, 0, w, 0)   # 横向渐变(左→右),壁纸在主窗+dock 间横向连续
    g.setColorAt(0.0, QColor(c1))
    g.setColorAt(1.0, QColor(c2))
    p.fillRect(0, 0, w, h, g)
    p.end()
    return pm

def _load_wallpaper_source(settings: dict) -> QPixmap | None:
    """按设置加载当前壁纸(返回 QPixmap;无壁纸/加载失败返回 None)。
    设置键:ui_wallpaper_source(none/bundled/preset/official/user) + 各源对应键。"""
    src = (settings or {}).get("ui_wallpaper_source", "none") or "none"
    if src == "bundled":
        return _load_pixmap(bundled_wallpaper_path())
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

_wallpaper_cache_key = None

_wallpaper_original = None

_wallpaper_blurred = None

_wallpaper_blur_radius = None

def blur_strength(settings: dict) -> int:
    """0 disables blur; migrate the old boolean switch to its original radius."""
    value = (settings or {}).get('ui_wallpaper_blur', None)
    if value is None:
        return 5
    if isinstance(value, bool):
        return 24 if value else 0
    try:
        return max(0, min(80, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 0

def _bake_wallpaper_blur(source: QPixmap, radius: int = 24) -> QPixmap:
    """Render an offscreen effect once; never attach a live effect to the UI."""
    from PySide6.QtCore import QRectF
    from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem, QGraphicsBlurEffect
    # Bound preprocessing cost even for 4K images. Wallpaper does not need crisp detail.
    work = source.scaled(1600, 1600, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation) if max(source.width(), source.height()) > 1600 else source
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(work)
    scene.addItem(item)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    item.setGraphicsEffect(effect)
    rect = QRectF(work.rect())
    scene.setSceneRect(rect)
    result = QPixmap(work.size())
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    try:
        scene.render(painter, rect, rect)
    finally:
        painter.end()
    return result

def load_wallpaper(settings: dict) -> QPixmap | None:
    """Cache one source and its blurred variant; theme/mask/resize don't invalidate it."""
    global _wallpaper_cache_key, _wallpaper_original, _wallpaper_blurred, _wallpaper_blur_radius
    settings = settings or {}
    src = settings.get('ui_wallpaper_source', 'none')
    path = ''
    if src == 'bundled':
        path = bundled_wallpaper_path()
    elif src in ('user', 'official'):
        from paths import cache_dir
        rel = settings.get('ui_wallpaper_user_path', '') if src == 'user' else os.path.join(
            'wallpapers', f"official_{settings.get('ui_wallpaper_official_id', '')}.png")
        if rel:
            path = os.path.join(cache_dir(), rel)
    try:
        stat = os.stat(path)
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    key = (src, path, stamp, settings.get('ui_wallpaper_preset', DEFAULT_PRESET))
    if key != _wallpaper_cache_key:
        _wallpaper_original = _load_wallpaper_source(settings)
        _wallpaper_blurred = None
        _wallpaper_cache_key = key
    if _wallpaper_original is None:
        return None
    radius = blur_strength(settings)
    if radius == 0:
        return _wallpaper_original
    if _wallpaper_blurred is None or _wallpaper_blur_radius != radius:
        _wallpaper_blurred = _bake_wallpaper_blur(_wallpaper_original, radius)
        _wallpaper_blur_radius = radius
    return _wallpaper_blurred
