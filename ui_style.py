# -*- coding: utf-8 -*-
"""
深色/浅色 + 未来自定义配色方案(主题)统一入口。

**为什么要把颜色集中在这里**:所有"卡片/列表/标签/按钮/文字"的样式都从这里取,
这样:
- 深浅色自适应(按系统主题);
- **未来自定义配色方案(主题)**:只需要 `set_custom_colors({name: color})` 覆盖某些颜色槽,
  所有样式自动跟着变,不用改各页面代码(预留的变量见 COLOR_SLOTS / current_color)。

用法(页面里):`from ui_style import card_btn_style, text_color, ...` —— 和以前一样。
新增配色方案:读设置 → `load_theme_from_settings(settings)`(预留设置键 ui_custom_colors)。
"""
from ui_tokens import (   # 设计 token 单一数据源:颜色/非颜色 token 全部从 ui_tokens 取
    COLOR_SLOTS, COLOR_TOKENS,
    is_dark_mode, current_token,
    set_custom_colors, clear_custom_colors, get_custom_colors,
    SPACING, RADIUS, SHADOW, DURATION, EASING,
)

# ---------------- 兼容层:保留既有公开 API ----------------
# COLOR_SLOTS / set_custom_colors / clear_custom_colors / get_custom_colors / is_dark_mode
# 均从 ui_tokens 重导出,名字与行为不变(第三方 import 不破)。


def current_color(name: str) -> str:
    """取某颜色槽的当前值(委托 ui_tokens.current_token;签名/行为不变)。"""
    return current_token(name)


def load_theme_from_settings(settings: dict) -> None:
    """(预留)从设置读自定义配色主题并应用。设置键: ui_custom_colors(dict), ui_theme(str)。"""
    set_custom_colors((settings or {}).get("ui_custom_colors"))


# ---------------- 实时配色刷新 ----------------
# 自定义配色改了以后,要让整应用立即变色,而不只是下次重启。
# 机制:各页面在构造时把"用到 ui_style 颜色槽的控件"登记进来(register_refresh_widget),
# 换色后 refresh_theme() 遍历所有登记的控件重新 setStyleSheet(样式函数用最新 current_color)。
# 这样不用改每个页面的 setStyleSheet 调用(它们仍按原样写在构造处)。
_REFRESH_WIDGETS = {}   # id(widget) -> (callable_or_none, style_fn, args)


def register_refresh_widget(widget, style_fn, *args) -> None:
    """登记一个需要跟随配色刷新的控件。
    style_fn: 每次调用返回该控件样式表字符串的函数(如 card_btn_style / 自定义 lambda)。
    args: 传给 style_fn 的额外参数(如自定义的色变量)。"""
    try:
        _REFRESH_WIDGETS[id(widget)] = (widget, style_fn, args)
    except Exception:
        pass


def unregister_refresh_widget(widget) -> None:
    try:
        _REFRESH_WIDGETS.pop(id(widget), None)
    except Exception:
        pass


def refresh_widget(widget) -> None:
    """立即重刷某个已登记控件的样式(用最新配色)。"""
    entry = _REFRESH_WIDGETS.get(id(widget))
    if not entry:
        return
    _w, fn, args = entry
    try:
        _w.setStyleSheet(fn(*args))
    except Exception:
        pass


def refresh_theme() -> None:
    """换色后实时刷遍所有登记过的控件。供设置中心在改色/重置后调用。"""
    for _w, fn, args in list(_REFRESH_WIDGETS.values()):
        try:
            _w.setStyleSheet(fn(*args))
        except Exception:
            pass
    # 也把全局调色板改成最新配色(未登记/用默认色的对话框、菜单、下拉等跟随)
    try:
        app = QApplication.instance()
        if app is not None:
            apply_global_dark_palette(app)
    except Exception:
        pass
    # 主题色变了 → 主题化图标缓存作废,下次 theme_icon() 用新色重建(懒导入防循环)
    try:
        from theme_icon import recolor_icons
        recolor_icons()
    except Exception:
        pass


def set_style(widget, style_fn, *args) -> None:
    """给控件上样式并登记为「跟随配色刷新」。
    用法:ui_style.set_style(btn, card_btn_style) 代替 btn.setStyleSheet(card_btn_style()).
    这样换色后 refresh_theme() 会用最新配色重刷该控件。"""
    widget.setStyleSheet(style_fn(*args))
    register_refresh_widget(widget, style_fn, *args)


def clear_registered_styles() -> None:
    """清空所有登记(窗口关闭/重建时调用,避免泄漏无效引用)。"""
    _REFRESH_WIDGETS.clear()


# ---------------- 可读性 / 色差检查 ----------------
# 目的:自定义配色后,防止"文字看不清"(前景/背景对比度不足)或强调色与背景难分辨(明暗/灰度接近)。
# 用 WCAG 相对亮度 + 对比度。文本可读≥4.5,装饰可区分≥3。
def hex_to_rgb(color: str) -> tuple:
    """'#RRGGBB' / '#RGB' → (r,g,b) 0-255。失败返回 (128,128,128)。"""
    c = (color or "").strip().lower()
    if c.startswith("#"):
        c = c[1:]
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) == 6:
        try:
            return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    # rgba(...) 等:取前三个数值,失败用默认
    if c.startswith("rgba"):
        import re
        nums = re.findall(r"[\d.]+", color)
        try:
            return (int(float(nums[0])), int(float(nums[1])), int(float(nums[2])))
        except Exception:
            return (128, 128, 128)
    return (128, 128, 128)


def _lum(rgb: tuple) -> float:
    """WCAG 相对亮度 0-1。"""
    def ch(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(rgb[0]) + 0.7152 * ch(rgb[1]) + 0.0722 * ch(rgb[2])


def contrast_ratio(c1: str, c2: str) -> float:
    """两个颜色(hex)的 WCAG 对比度,范围 1-21。"""
    l1, l2 = _lum(hex_to_rgb(c1)), _lum(hex_to_rgb(c2))
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def luminance(c: str) -> float:
    return _lum(hex_to_rgb(c))


def color_difference(c1: str, c2: str) -> float:
    """感知色差(简化的欧氏距离 0-~441)。越小越接近。"""
    (r1, g1, b1), (r2, g2, b2) = hex_to_rgb(c1), hex_to_rgb(c2)
    return ((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) ** 0.5


def saturation(c: str) -> float:
    """饱和度 0-1(基于 HSV/HSL 的简化:最大值与最小值之差归一化)。"""
    r, g, b = hex_to_rgb(c)
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == 0:
        return 0.0
    return (mx - mn) / mx


def _blend_bg(bg: str) -> str:
    """把(可能半透明的)背景色叠到当前模式的基础窗口色上,得到"有效背景"用于对比度。
    这样 rgba(...,0.06) 在暗色下≈近黑,在亮色下≈近白,判读更准。"""
    if "rgba" not in bg:
        return bg
    import re
    nums = re.findall(r"[\d.]+", bg)
    try:
        r, g, b = int(float(nums[0])), int(float(nums[1])), int(float(nums[2]))
        a = float(nums[3]) if len(nums) > 3 else 1.0
    except Exception:
        a = 1.0
        r = g = b = 128
    # 基础窗口色(当前模式)
    base = "#f5f6f9" if not is_dark_mode() else "#23272f"
    br, bgc, bb = hex_to_rgb(base)
    nr = int(r * a + br * (1 - a)); ng = int(g * a + bgc * (1 - a)); nb = int(b * a + bb * (1 - a))
    return f"#{nr:02x}{ng:02x}{nb:02x}"


def check_readability(custom: dict) -> list:
    """检查自定义配色(text/accent 等)相对背景的可读性,返回提示列表(空=没问题)。
    规则:文字 vs 背景对比度≥4.5 才清晰;强调色 vs 背景需可区分(对比度≥3 或色差/明暗足够)。
    背景优先用自定义 panel_bg,半透明则按当前模式叠到窗口色上判读。"""
    msgs = []
    text = custom.get("text") or current_color("text")
    accent = custom.get("accent") or current_color("accent")
    bg = _blend_bg(custom.get("panel_bg") or current_color("panel_bg"))
    # 1) 文字 vs 背景(主可读性)
    tc = contrast_ratio(text, bg)
    if tc < 4.5:
        msgs.append(f"⚠️ 文字色与背景对比度仅 {tc:.1f}:1(<4.5),正常文字可能看不清。建议换更亮/更暗的文字色或调背景。")
    elif tc < 7:
        msgs.append(f"文字与背景对比度 {tc:.1f}:1(达标,但小字/细字仍建议≥7 更稳)。")
    # 2) 强调色 vs 背景(要能区分)
    ac = contrast_ratio(accent, bg)
    if ac < 3 and color_difference(accent, bg) < 100:
        msgs.append(f"⚠️ 强调色与背景太接近(对比度 {ac:.1f}:1),按钮/高亮/超链接可能看不清。换更醒目或更暗的强调色。")
    # 3) 灰度/明暗接近告警(色弱用户尤其明显)
    if abs(luminance(accent) - luminance(text)) < 0.05:
        msgs.append("强调色与文字明暗过于接近,色弱/灰度下可能难区分。可加粗或选更亮/更暗的强调色。")
    return msgs


# ---------------- 色盲 / 色弱配色模板 ----------------
# 无障碍预设:针对不同色觉障碍 + 高对比/灰度友好。
# 只覆盖【强调色一族】(accent* / 选中高亮),不碰 text/panel_bg——后者随当前深浅色自动走,
# 这样在两种模式下都保持文字/背景可读,色弱用户主要受益于"强调色不混淆"。
COLOR_BLIND_PRESETS = {
    "高对比(黑白分明)": {
        "description": "高对比强调色,最大可读性",
        "colors": {"accent": "#ffb400", "accent_bright": "#ffc93c", "accent_bg": "#c77c00",
                    "accent_bg_hover": "#d98e00", "accent_bg_pressed": "#a56500",
                    "sel_bg": "rgba(255,180,0,0.30)", "menu_sel": "rgba(255,180,0,0.22)"},
    },
    "红绿色盲(蓝/黄)": {
        "description": "避开红绿混淆,用蓝黄做强调",
        "colors": {"accent": "#1e88e5", "accent_bright": "#42a5f5",
                    "accent_bg": "#1565c0", "accent_bg_hover": "#1e78d2", "accent_bg_pressed": "#0d47a1",
                    "sel_bg": "rgba(30,136,229,0.30)", "menu_sel": "rgba(30,136,229,0.22)"},
    },
    "蓝黄色盲(红/绿)": {
        "description": "避开蓝黄混淆,用红绿做强调",
        "colors": {"accent": "#e53935", "accent_bright": "#ef5350",
                    "accent_bg": "#c62828", "accent_bg_hover": "#d33835", "accent_bg_pressed": "#b71c1c",
                    "sel_bg": "rgba(229,57,53,0.30)", "menu_sel": "rgba(229,57,53,0.22)"},
    },
    "灰度友好(不看色相)": {
        "description": "靠明暗/形状区分,不依赖颜色",
        "colors": {"accent": "#64b5f6", "accent_bright": "#90caf9",
                    "accent_bg": "#3f7fc4", "accent_bg_hover": "#4e93d4", "accent_bg_pressed": "#33689f",
                    "sel_bg": "rgba(100,181,246,0.28)", "menu_sel": "rgba(100,181,246,0.20)"},
    },
}


def apply_color_blind_preset(name: str) -> dict:
    """按预设名返回要写入 settings 的 ui_custom_colors(空 dict=无效名/无预设)。"""
    presets = COLOR_BLIND_PRESETS.get(name)
    return dict(presets["colors"]) if presets else {}


# ---------------- 基础配色 ---------------- 
def _tz(dark: str, light: str) -> str:
    """按当前主题返回 dark 或 light 值"""
    return dark if is_dark_mode() else light


def text_color() -> str:
    """正文文字颜色"""
    return current_color("text")


def muted_color() -> str:
    """次要/提示文字颜色"""
    return current_color("muted")


def hover_bg() -> str:
    """通用悬停底色(用于透明按钮/条目的 hover 背景)"""
    return current_color("hover")


def accent_color() -> str:
    """强调色(主色,用于悬停边框/链接/开关)"""
    return current_color("accent")


def danger_color() -> str:
    """语义色:危险/错误(红)"""
    return current_color("danger")


def success_color() -> str:
    """语义色:成功(绿)"""
    return current_color("success")


def warning_color() -> str:
    """语义色:警告/进行中(橙黄)"""
    return current_color("warning")


def info_color() -> str:
    """语义色:信息(蓝,默认同 accent)"""
    return current_color("info")


def panel_style() -> str:
    """卡片/面板:圆角 + 细边框 + 柔和背景,自适应深色。"""
    bg = current_color("panel_bg")
    border = current_color("panel_border")
    return f"border: 1px solid {border}; border-radius: 12px; background: {bg};"


def card_btn_style() -> str:
    """卡片感按钮(启动器设置/管理/刷新/实例卡片等):圆角 + 悬停蓝框。"""
    bg = current_color("btn_bg")
    border = current_color("btn_border")
    text = text_color()
    pressed = current_color("btn_bg_pressed")
    focus = current_color("focus")
    return (
        f"QPushButton {{ background: {bg}; color: {text}; border: 1px solid {border};"
        f" border-radius: 9px; padding: 8px 12px; }}"
        f"QPushButton:hover {{ border-color: {current_color('accent')}; }}"
        f"QPushButton:pressed {{ background: {pressed}; }}"
        f"QPushButton:focus {{ border: 2px solid {focus}; }}"
    )


def list_style() -> str:
    """列表(实例列表/结果列表):圆角条目 + 选中/悬停高亮,自适应主题。"""
    sel = current_color("sel_bg")
    hover = current_color("list_hover")
    text = text_color()
    return (
        f"QListWidget {{ background: transparent; border: none; outline: none; }}"
        f"QListWidget::item {{ padding: 8px 10px; margin: 3px 4px;"
        f" border-radius: 8px; color: {text}; }}"
        f"QListWidget::item:selected {{ background: {sel}; color: #ffffff; }}"
        f"QListWidget::item:hover {{ background: {hover}; }}"
    )


def tab_style() -> str:
    """标签页:圆角 + 选中高亮,自适应主题。QTabWidget/QTabBar 本身设透明,
    壁纸能从标签条/内容区透出(否则 QTabBar 默认画不透明底色,标签区遮住壁纸)。"""
    pane_border = current_color("tab_pane_border")
    sel_bg = current_color("tab_sel_bg")
    text = text_color()
    muted = muted_color()
    return (
        f"QTabWidget {{ background: transparent; }}"
        f"QTabWidget::pane {{ border: 1px solid {pane_border}; border-radius: 10px;"
        f" background: transparent; }}"
        f"QTabBar {{ background: transparent; }}"
        f"QTabBar::tab {{ background: transparent; padding: 7px 16px; margin-right: 4px;"
        f" color: {muted}; font-size: 14px; border-top-left-radius: 7px;"
        f" border-top-right-radius: 7px; }}"
        f"QTabBar::tab:selected {{ background: {sel_bg}; color: {text}; font-weight: bold; }}"
        f"QTabBar::tab:hover {{ color: {text}; }}"
    )


def launch_btn_style() -> str:
    """主操作大按钮(启动游戏):蓝色渐变 + 大圆角,自适应主题的蓝。"""
    return (
        "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        f" stop:0 {current_color('accent_bright')}, stop:1 {current_color('accent_bg')});"
        " color: #ffffff; border: none; border-radius: 12px; font-size: 17px;"
        " font-weight: bold; padding: 12px 14px; }"
        "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        f" stop:0 {current_color('accent_bright')}, stop:1 {current_color('accent_bg_hover')}); }}"
        f"QPushButton:pressed {{ background: {current_color('accent_bg_pressed')}; }}"
        f"QPushButton:focus {{ border: 2px solid {current_color('focus')}; }}"
        f"QPushButton:disabled {{ background: {current_color('btn_disabled_bg')};"
        f" color: {current_color('btn_disabled_text')}; }}"
    )


def menu_btn_style() -> str:
    """左侧菜单按钮(左菜单独立模块用):
    未选中半透明+灰字,悬停提亮,选中=高亮底色+蓝左条+加粗。自适应深色。"""
    sel = current_color("menu_sel")
    hover = current_color("menu_hover")
    text = text_color()
    muted = muted_color()
    return (
        f"QPushButton {{ background: transparent; color: {muted}; border: none;"
        f" border-left: 3px solid transparent; border-radius: 8px;"
        f" padding: 9px 12px; text-align: left; font-size: 13px; }}"
        f"QPushButton:hover {{ background: {hover}; color: {text}; }}"
        f"QPushButton:checked {{ background: {sel}; color: {text}; font-weight: bold;"
        f" border-left: 3px solid {current_color('accent')}; }}"
    )


# ---------------- 旧兼容样式 ----------------
def card_style() -> str:
    """可点击卡片(加载器/实例/Mod):未选中浅灰底,选中蓝框高亮"""
    if is_dark_mode():
        return (
            f"QPushButton {{ background: #2b2b2b; border: 2px solid #555555; border-radius: 6px;"
            f" color: {text_color()}; text-align: left; }}"
            f"QPushButton:hover {{ border-color: {accent_color()}; }}"
            f"QPushButton:checked {{ background: #1e3a5c; border: 2px solid {accent_color()}; color: #cfe3ff; }}"
        )
    return (
        f"QPushButton {{ background: #f5f5f5; border: 2px solid #999999; border-radius: 6px;"
        f" color: {text_color()}; text-align: left; }}"
        f"QPushButton:hover {{ border-color: {accent_color()}; }}"
        f"QPushButton:checked {{ background: #DCEBFF; border: 2px solid {accent_color()}; color: #10437F; }}"
    )


def accent_border_style() -> str:
    """右侧 AI 条展开按钮:暗底 + 圆角 + 悬停强调色边框。跟随配色刷新。"""
    bg = current_color("btn_bg")
    border = current_color("btn_border")
    text = text_color()
    return (
        f"QPushButton {{ background: {bg}; color: {text}; border: 1px solid {border};"
        f" border-radius: 8px; font-weight: bold; }}"
        f"QPushButton:hover {{ border-color: {current_color('accent')}; }}"
        f"QPushButton:pressed {{ background: {current_color('btn_bg_pressed')}; }}"
        f"QPushButton:focus {{ border: 2px solid {current_color('focus')}; }}"
    )


def arrow_style() -> str:
    """卡片右侧的展开箭头按钮"""
    return f"QPushButton {{ border: none; background: transparent; color: {muted_color()}; }}"


def primary_btn_style() -> str:
    """主操作按钮(蓝底白字):深浅色模式用不同蓝色适配,可读性更好"""
    return (
        f"QPushButton {{ background: {current_color('accent_bg')}; color: #FFFFFF; border: none;"
        f" border-radius: 6px; padding: 6px 14px; font-weight: bold; }}"
        f"QPushButton:hover {{ background: {current_color('accent_bg_hover')}; }}"
        f"QPushButton:pressed {{ background: {current_color('accent_bg_pressed')}; }}"
        f"QPushButton:focus {{ border: 2px solid {current_color('focus')}; }}"
        f"QPushButton:disabled {{ background: {current_color('btn_disabled_bg')};"
        f" color: {current_color('btn_disabled_text')}; }}"
    )


def hint_style() -> str:
    """灰色提示文字(两种主题下都可读)"""
    return f"color: {muted_color()};"


def inner_style() -> str:
    """卡片内部的标签(透明底,跟卡片背景一致)"""
    return "background: transparent;"


def apply_global_dark_palette(app) -> None:
    """系统是深色主题时,给整个应用设一套深色 QPalette。

    让那些"没写死色"的默认控件(对话框 / QMenu / QTabWidget / QComboBox 下拉 /
    QMessageBox 等)也变深色,与启动器整体风格一致。已用样式表写死色的不受影响。"""
    if not is_dark_mode():
        return
    from PySide6.QtGui import QColor, QPalette
    p = QPalette()
    bg = QColor("#23272f")
    base = QColor("#1a1d23")
    text = QColor("#e7ecf5")
    muted = QColor("#8b96a8")
    accent = QColor(current_color("accent"))
    p.setColor(QPalette.ColorRole.Window, bg)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, base)
    p.setColor(QPalette.ColorRole.AlternateBase, bg)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.Button, bg)
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.Highlight, accent)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.ToolTipBase, base)
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.PlaceholderText, muted)
    app.setPalette(p)


def dialog_dark_style() -> str:
    """对话框级深色风格(实例详情等用):把默认控件(按钮/下拉/菜单/输入框/列表)统一成
    启动器的深色圆角样子。浅色主题下返回空串(用系统默认)。"""
    if not is_dark_mode():
        return ""
    border = current_color("border_soft")
    bg = current_color("bg1")
    base = current_color("bg0")
    focus = current_color("focus")
    text = text_color()
    return (
        f"QMenu {{ background: {bg}; border: 1px solid {border}; border-radius: 8px; padding: 4px; }}"
        f"QMenu::item {{ padding: 6px 16px; border-radius: 5px; color: {text}; }}"
        f"QMenu::item:selected {{ background: {current_color('menu_sel')}; }}"
        f"QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}"
        f"QComboBox {{ background: {bg}; color: {text}; border: 1px solid {border};"
        f" border-radius: 6px; padding: 4px 8px; }}"
        f"QComboBox:focus {{ border-color: {focus}; }}"
        f"QComboBox QAbstractItemView {{ background: {base}; color: {text};"
        f" selection-background-color: {current_color('sel_bg')}; border: 1px solid {border}; }}"
        f"QPushButton {{ background: {current_color('btn_bg')}; color: {text}; border: 1px solid {border};"
        f" border-radius: 6px; padding: 5px 11px; }}"
        f"QPushButton:hover {{ border-color: {current_color('accent')}; }}"
        f"QPushButton:pressed {{ background: {current_color('btn_bg_pressed')}; }}"
        f"QPushButton:focus {{ border-color: {focus}; }}"
        f"QLineEdit, QSpinBox {{ background: {base}; color: {text}; border: 1px solid {border};"
        f" border-radius: 6px; padding: 3px 6px; }}"
        f"QLineEdit:focus, QSpinBox:focus {{ border-color: {focus}; }}"
        f"QListWidget {{ background: {base}; color: {text}; border: 1px solid {border};"
        f" border-radius: 8px; }}"
        f"QListWidget::item {{ padding: 4px 6px; border-radius: 4px; }}"
        f"QListWidget::item:selected {{ background: {current_color('sel_bg')}; }}"
        f"QCheckBox {{ color: {text}; }}"
        f"QTextEdit, QPlainTextEdit {{ background: {base}; color: {text}; border: 1px solid {border}; }}"
        f"QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {focus}; }}"
        f"QToolTip {{ background: {bg}; color: {text}; border: 1px solid {border}; }}"
    )
