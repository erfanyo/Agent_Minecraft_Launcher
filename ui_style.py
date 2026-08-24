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


# ---------------- 自定义配色方案(预留) ----------------
# 所有颜色槽 = (深色默认, 浅色默认)。自定义主题只覆盖需要的槽。
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

_CUSTOM_COLORS = {}   # name -> color(自定义主题覆盖)


def set_custom_colors(mapping: dict) -> None:
    """设置自定义配色主题(只认 COLOR_SLOTS 里的名字;空/不认识的忽略)。"""
    global _CUSTOM_COLORS
    _CUSTOM_COLORS = {k: v for k, v in (mapping or {}).items() if k in COLOR_SLOTS and v}


def clear_custom_colors() -> None:
    global _CUSTOM_COLORS
    _CUSTOM_COLORS = {}


def get_custom_colors() -> dict:
    return dict(_CUSTOM_COLORS)


def current_color(name: str) -> str:
    """取某颜色槽的当前值:自定义主题优先,否则按深浅色默认。"""
    if name in _CUSTOM_COLORS:
        return _CUSTOM_COLORS[name]
    dark, light = COLOR_SLOTS.get(name, ("#000000", "#000000"))
    return dark if is_dark_mode() else light


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


def set_style(widget, style_fn, *args) -> None:
    """给控件上样式并登记为「跟随配色刷新」。
    用法:ui_style.set_style(btn, card_btn_style) 代替 btn.setStyleSheet(card_btn_style()).
    这样换色后 refresh_theme() 会用最新配色重刷该控件。"""
    widget.setStyleSheet(style_fn(*args))
    register_refresh_widget(widget, style_fn, *args)


def clear_registered_styles() -> None:
    """清空所有登记(窗口关闭/重建时调用,避免泄漏无效引用)。"""
    _REFRESH_WIDGETS.clear()


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
    return (
        f"QPushButton {{ background: {bg}; color: {text}; border: 1px solid {border};"
        f" border-radius: 9px; padding: 8px 12px; }}"
        f"QPushButton:hover {{ border-color: {current_color('accent')}; }}"
        f"QPushButton:pressed {{ background: {pressed}; }}"
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
    """标签页:圆角 + 选中高亮,自适应主题。"""
    pane_border = current_color("tab_pane_border")
    sel_bg = current_color("tab_sel_bg")
    text = text_color()
    muted = muted_color()
    return (
        f"QTabWidget::pane {{ border: 1px solid {pane_border}; border-radius: 10px; }}"
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
            "QPushButton { background: #2b2b2b; border: 2px solid #555555; border-radius: 6px;"
            " color: #e8e8e8; text-align: left; }"
            "QPushButton:hover { border-color: #5B8DEF; }"
            "QPushButton:checked { background: #1e3a5c; border: 2px solid #5B8DEF; color: #cfe3ff; }"
        )
    return (
        "QPushButton { background: #f5f5f5; border: 2px solid #999999; border-radius: 6px;"
        " color: #222222; text-align: left; }"
        "QPushButton:hover { border-color: #3B8EEA; }"
        "QPushButton:checked { background: #DCEBFF; border: 2px solid #3B8EEA; color: #10437F; }"
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
    )


def arrow_style() -> str:
    """卡片右侧的展开箭头按钮"""
    return "QPushButton { border: none; background: transparent; color: #888888; }"


def primary_btn_style() -> str:
    """主操作按钮(蓝底白字):深浅色模式用不同蓝色适配,可读性更好"""
    return (
        f"QPushButton {{ background: {current_color('accent_bg')}; color: #FFFFFF; border: none;"
        f" border-radius: 6px; padding: 6px 14px; font-weight: bold; }}"
        f"QPushButton:hover {{ background: {current_color('accent_bg_hover')}; }}"
        f"QPushButton:pressed {{ background: {current_color('accent_bg_pressed')}; }}"
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
    border = "rgba(255,255,255,0.10)"
    bg = "#23272f"
    base = "#1a1d23"
    text = text_color()
    return (
        f"QMenu {{ background: {bg}; border: 1px solid {border}; border-radius: 8px; padding: 4px; }}"
        f"QMenu::item {{ padding: 6px 16px; border-radius: 5px; color: {text}; }}"
        f"QMenu::item:selected {{ background: rgba(91,141,239,0.25); }}"
        f"QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}"
        f"QComboBox {{ background: {bg}; color: {text}; border: 1px solid {border};"
        f" border-radius: 6px; padding: 4px 8px; }}"
        f"QComboBox QAbstractItemView {{ background: {base}; color: {text};"
        f" selection-background-color: rgba(91,141,239,0.30); border: 1px solid {border}; }}"
        f"QPushButton {{ background: #2b2f3a; color: {text}; border: 1px solid {border};"
        f" border-radius: 6px; padding: 5px 11px; }}"
        f"QPushButton:hover {{ border-color: #5B8DEF; }}"
        f"QPushButton:pressed {{ background: #242833; }}"
        f"QLineEdit, QSpinBox {{ background: {base}; color: {text}; border: 1px solid {border};"
        f" border-radius: 6px; padding: 3px 6px; }}"
        f"QListWidget {{ background: {base}; color: {text}; border: 1px solid {border};"
        f" border-radius: 8px; }}"
        f"QListWidget::item {{ padding: 4px 6px; border-radius: 4px; }}"
        f"QListWidget::item:selected {{ background: rgba(91,141,239,0.30); }}"
        f"QCheckBox {{ color: {text}; }}"
        f"QTextEdit, QPlainTextEdit {{ background: {base}; color: {text}; border: 1px solid {border}; }}"
        f"QToolTip {{ background: {bg}; color: {text}; border: 1px solid {border}; }}"
    )
