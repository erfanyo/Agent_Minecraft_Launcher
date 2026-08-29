# -*- coding: utf-8 -*-
"""
设计 token 单一数据源(前端现代化改造 · 阶段 1)。

**定位**:所有颜色/间距/圆角/阴影/时长的唯一出处。`ui_style.py` 委托到这里读值,
页面新代码直接 `from ui_tokens import current_token, SPACING, RADIUS, ...`。

**为什么拆成独立模块**(见《前端现代化改造方案-评审意见与决策.md》P1 双数据源治理):
- `COLOR_SLOTS` 保持 21 个既有槽名不变 —— 这是 `ui_custom_colors` 唯一能覆盖的命名空间,
  `set_custom_colors()` 按此过滤,旧配置兼容。
- 新增语义色槽放 `COLOR_TOKENS`(bg 分层 / text 分层 / 边框 / focus / 遮罩 / 语义色),
  **不进 COLOR_SLOTS**,避免破坏 `set_custom_colors` 过滤语义。
- 非颜色 token(间距/圆角/阴影/时长)独立成 `SPACING`/`RADIUS`/`SHADOW`/`DURATION`。

**用法**:
    from ui_tokens import current_token, RADIUS, DURATION
    current_token("accent")   # 自定义主题优先 → 深浅色默认
    current_token("bg1")      # 新语义槽
    RADIUS["md"], DURATION["fade"]
"""
from PySide6.QtWidgets import QApplication


def is_dark_mode() -> bool:
    """判断当前系统主题是不是深色"""
    app = QApplication.instance()
    if app is None:
        return False
    try:
        scheme = app.styleHints().colorScheme()
        if hasattr(scheme, "name") and scheme.name == "Dark":
            return True
    except Exception:
        pass
    win = app.palette().window().color()
    return win.lightness() < 128


# ---------------- 颜色槽(深色默认, 浅色默认) ----------------
# COLOR_SLOTS:21 个既有槽,ui_custom_colors / set_custom_colors 只认这些名字。
# 名字与值与原 ui_style.py 完全一致,保持不变(第三方 import / 旧配置兼容)。
COLOR_SLOTS = {
    "text": ("#e7ecf5", "#1f2430"),
    "muted": ("#8b96a8", "#6b7280"),
    "hover": ("rgba(255,255,255,0.08)", "rgba(0,0,0,0.05)"),
    "panel_bg": ("rgba(255,255,255,0.045)", "rgba(0,0,0,0.035)"),
    "panel_border": ("rgba(255,255,255,0.11)", "rgba(20,30,60,0.12)"),
    "btn_bg": ("#2b2f3a", "#f4f6fa"),
    "btn_bg_pressed": ("#242833", "#e6ebf3"),
    "btn_border": ("#3a4150", "#cfd5e0"),
    "accent": ("#5B8DEF", "#3B8EEA"),
    "accent_bright": ("#4A8CF0", "#3D8BF2"),
    "accent_bg": ("#2E6FD8", "#1E6FD9"),
    "accent_bg_hover": ("#3D80E8", "#2F7FE8"),
    "accent_bg_pressed": ("#265FB8", "#175CB5"),
    "btn_disabled_bg": ("#44506A", "#B9C4D6"),
    "btn_disabled_text": ("#9AA4B8", "#EEF1F6"),
    "sel_bg": ("rgba(91,141,239,0.30)", "rgba(59,142,234,0.20)"),
    "list_hover": ("rgba(255,255,255,0.08)", "rgba(59,142,234,0.08)"),
    "menu_sel": ("rgba(91,141,239,0.20)", "rgba(59,142,234,0.16)"),
    "menu_hover": ("rgba(255,255,255,0.07)", "rgba(59,142,234,0.08)"),
    "tab_pane_border": ("rgba(255,255,255,0.10)", "rgba(20,30,60,0.14)"),
    "tab_sel_bg": ("rgba(91,141,239,0.16)", "rgba(59,142,234,0.14)"),
}

# ---------------- 新增语义色槽(不进 COLOR_SLOTS 命名空间) ----------------
# bg 分层(背景):bg0 最深(输入框底) → bg2 最浅(卡片/按钮底)
# text 分层:text0 正文 → text2 最弱(辅助/占位)
COLOR_TOKENS = {
    # 背景分层
    "bg0": ("#1a1d23", "#ffffff"),        # 输入框/编辑区底(等价旧 base)
    "bg1": ("#23272f", "#f5f6f9"),        # 窗口底(等价旧 window)
    "bg2": ("#2b2f3a", "#f4f6fa"),        # 卡片/按钮底(等价旧 btn_bg)
    # 文本分层
    "text0": ("#e7ecf5", "#1f2430"),      # 正文(= text)
    "text1": ("#8b96a8", "#6b7280"),      # 次要(= muted)
    "text2": ("#aab3c0", "#8a93a0"),      # 辅助/占位(更弱一级)
    # 边框 / 状态
    "border": ("#3a4150", "#cfd5e0"),     # 边框(= btn_border)
    "border_soft": ("rgba(255,255,255,0.10)", "rgba(20,30,60,0.14)"),
    "focus": ("#5B8DEF", "#3B8EEA"),      # 焦点环(补齐五态里的 focus 态)
    "mask": ("#000000", "#ffffff"),       # 壁纸可读性遮罩底色(阶段 2 用)
    # 语义色
    "danger": ("#E53935", "#D32F2F"),
    "success": ("#4CAF50", "#388E3C"),
    "warning": ("#F59E0B", "#F57C00"),
    "info": ("#5B8DEF", "#3B8EEA"),
    # 强调底上的白字 / 禁用文字
    "text_on_accent": ("#ffffff", "#ffffff"),
    "text_disabled": ("#9AA4B8", "#EEF1F6"),  # (= btn_disabled_text)
}

# 全部颜色槽 = COLOR_SLOTS ∪ COLOR_TOKENS(查询用;current_token 只读这两个表)
_ALL_COLORS = {**COLOR_SLOTS, **COLOR_TOKENS}

# 自定义配色覆盖(只认 COLOR_SLOTS 槽名;状态保持在这里,ui_style 委托)
_CUSTOM_COLORS = {}


def set_custom_colors(mapping: dict) -> None:
    """设置自定义配色主题(只认 COLOR_SLOTS 里的名字;空/不认识的忽略)。"""
    global _CUSTOM_COLORS
    _CUSTOM_COLORS = {k: v for k, v in (mapping or {}).items() if k in COLOR_SLOTS and v}


def clear_custom_colors() -> None:
    global _CUSTOM_COLORS
    _CUSTOM_COLORS = {}


def get_custom_colors() -> dict:
    return dict(_CUSTOM_COLORS)


def current_token(name: str) -> str:
    """取某颜色槽的当前值:自定义主题优先(仅 COLOR_SLOTS 槽),否则按深浅色默认。
    兼容 COLOR_SLOTS 与新增 COLOR_TOKENS 两类槽名。"""
    if _WALLPAPER_ACTIVE and name in _WALLPAPER_OVERRIDES:
        dark, light = _WALLPAPER_OVERRIDES[name]
        return dark if is_dark_mode() else light
    if name in _CUSTOM_COLORS:
        return _CUSTOM_COLORS[name]
    dark, light = _ALL_COLORS.get(name, ("#000000", "#000000"))
    return dark if is_dark_mode() else light


# ---------------- 壁纸模式状态(阶段 2 · 决策 2) ----------------
# 壁纸激活时,所有「面」(面板/按钮/输入底)统一抬高到近不透明的同档透明度(0.88),
# 让壁纸在整窗均匀透出(用户反馈:按钮/文本框原来不透明,画面不统一)。
# 切换后需 refresh_theme() 重刷样式。
_WALLPAPER_ACTIVE = False
_WALLPAPER_OVERRIDES = {
    # 深色用「灰底」(比默认底更浅的灰、白字更清楚);浅色用微灰白。统一 0.62 透明度,
    # 让壁纸透出更多(嵌套半透明叠两层也不会太实;之前 0.72 嵌套≈0.92 显得不透明)。
    "panel_bg":         ("rgba(52,58,68,0.62)",  "rgba(240,243,247,0.62)"),
    "btn_bg":           ("rgba(58,64,74,0.62)",  "rgba(246,248,252,0.62)"),
    "btn_bg_pressed":   ("rgba(48,54,63,0.62)",  "rgba(232,237,245,0.62)"),
    "btn_disabled_bg":  ("rgba(74,84,104,0.50)", "rgba(190,200,214,0.50)"),
    "bg0":              ("rgba(46,52,62,0.62)",  "rgba(255,255,255,0.62)"),
    "bg2":              ("rgba(58,64,74,0.62)",  "rgba(246,248,252,0.62)"),
}


def set_wallpaper_active(active: bool) -> None:
    global _WALLPAPER_ACTIVE
    _WALLPAPER_ACTIVE = bool(active)


def is_wallpaper_active() -> bool:
    return _WALLPAPER_ACTIVE


# ---------------- 非颜色 token ----------------
# 间距(4px 基准)
SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}

# 圆角(3 级:小输入框/按钮 · 中卡片/菜单 · 大弹窗/浮层)
RADIUS = {"sm": 8, "md": 12, "lg": 16}

# 阴影(3 档:卡片 / 浮层 / 弹窗)。QSS 无 box-shadow,这里供 QGraphicsDropShadowEffect 用
# (阶段 2/3 的 ui_background/ui_anim 读取);blur=模糊半径, dy=垂直偏移, alpha 深/浅各一套。
SHADOW = {
    "card":   {"blur": 2,  "dy": 1, "alpha_dark": 0.30, "alpha_light": 0.08},
    "float":  {"blur": 12, "dy": 4, "alpha_dark": 0.40, "alpha_light": 0.14},
    "dialog": {"blur": 24, "dy": 8, "alpha_dark": 0.50, "alpha_light": 0.20},
}

# 动画时长(ms),easing 统一 OutCubic(阶段 3 ui_anim.py 读取)
DURATION = {
    "hover": 150,    # hover 微反馈
    "fade": 200,     # 淡入 / 遮罩过渡
    "tab": 250,      # 标签切换
    "slide": 320,    # 实例详情滑入(现有值,保留)
}
EASING = "OutCubic"
