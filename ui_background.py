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
# 深色系要更亮更纯:60% 黑遮罩会压暗,起色太暗就"脏";这里把深色渐变换成更干净的中灰/高饱和色。
PRESETS = {
    "slate":        ("#2e3440", "#3b4252"),   # 克制中灰(干净的中性灰,替代近黑)
    "teal":         ("#1a4a4a", "#3aa0a0"),   # MC 矿物青绿(更亮更纯)
    "grass":        ("#2a4020", "#5a9440"),   # MC 草绿(更亮更纯)
    "lime":         ("#3a4018", "#94a040"),   # MC 石灰(更亮)
    "deepslate":    ("#1e2a40", "#3a6e9a"),   # 深板岩蓝(更亮)
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


def input_style_qss() -> str:
    """壁纸模式下文本框/下拉框/列表的透明化 QSS(深/浅自适应)。
    文本框/下拉/列表默认走 QPalette(不透明),这里用全局 QSS 把它们统一成与面板同档的透明度,
    解决「按钮/文本框/列表是不透明硬块、画面不统一」的问题。"""
    if is_dark_mode():
        bg = "rgba(46,52,62,0.72)"
        base_bg = "rgba(40,46,56,0.72)"   # 列表/下拉弹出层底(略深一档)
        border = "rgba(255,255,255,0.14)"
        sel = "rgba(91,141,239,0.32)"
    else:
        bg = "rgba(255,255,255,0.72)"
        base_bg = "rgba(255,255,255,0.72)"
        border = "rgba(0,0,0,0.12)"
        sel = "rgba(59,142,234,0.22)"
    return (
        f"QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{"
        f" background: {bg}; border: 1px solid {border}; border-radius: 6px; }}"
        f"QComboBox QAbstractItemView {{ background: {base_bg}; selection-background-color: {sel}; }}"
        f"QListWidget, QTreeWidget, QTableWidget {{ background: {base_bg};"
        f" border: 1px solid {border}; border-radius: 6px; }}"
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
        self._mask = 0.6
        self._enabled = False

    def set_wallpaper(self, pixmap: QPixmap | None, mask: float = 0.6) -> None:
        """cover 模式:壁纸 cover 缩放到自身。pixmap 为 None = 关闭。"""
        self._source = pixmap
        self._mask = max(0.0, min(1.0, mask))
        self._enabled = pixmap is not None and not pixmap.isNull()
        self._cover = None
        self._shared = None
        self.update()

    def set_shared_view(self, scaled: QPixmap | None, vx: int, vy: int, mask: float = 0.6) -> None:
        """共享模式:用主窗统一的缩放壁纸 + 视口偏移。scaled 为 None = 关闭。"""
        self._shared = scaled
        self._vx = int(vx)
        self._vy = int(vy)
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
            # 共享模式:画缩放壁纸,负偏移让对应片段落在窗口内;
            # 偏移夹取到画布范围内,浮动移出画布时贴边(不出黑边)
            w, h = self.width(), self.height()
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
