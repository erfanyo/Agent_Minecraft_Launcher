# -*- coding: utf-8 -*-
"""
深色模式兼容:根据系统主题返回合适的卡片/箭头/提示文字样式。

之前用写死的浅色背景(#f5f5f5),系统是深色主题时文字是白的 → 白底白字。
现在所有"卡片"样式统一从这里取,深浅色各一套。

这里还集中放了「我的版本」首页与「下载新资源」共用的一套圆角/卡片/列表/标签页样式,
做成主题自适应,并在 version_home 与 resource_center 之间保持一致。
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


# ---------------- 基础配色 ----------------
def _tz(dark: str, light: str) -> str:
    """按当前主题返回 dark 或 light 值"""
    return dark if is_dark_mode() else light


def text_color() -> str:
    """正文文字颜色"""
    return _tz("#e7ecf5", "#1f2430")


def muted_color() -> str:
    """次要/提示文字颜色"""
    return _tz("#8b96a8", "#6b7280")


def hover_bg() -> str:
    """通用悬停底色(用于透明按钮/条目的 hover 背景)"""
    return _tz("rgba(255,255,255,0.08)", "rgba(0,0,0,0.05)")


def panel_style() -> str:
    """卡片/面板:圆角 + 细边框 + 柔和背景,自适应深色。"""
    bg = _tz("rgba(255,255,255,0.045)", "rgba(0,0,0,0.035)")
    border = _tz("rgba(255,255,255,0.11)", "rgba(20,30,60,0.12)")
    return f"border: 1px solid {border}; border-radius: 12px; background: {bg};"


def card_btn_style() -> str:
    """卡片感按钮(启动器设置/管理/刷新/实例卡片等):圆角 + 悬停蓝框。"""
    bg = _tz("#2b2f3a", "#f4f6fa")
    border = _tz("#3a4150", "#cfd5e0")
    text = text_color()
    pressed = _tz("#242833", "#e6ebf3")
    return (
        f"QPushButton {{ background: {bg}; color: {text}; border: 1px solid {border};"
        f" border-radius: 9px; padding: 8px 12px; }}"
        f"QPushButton:hover {{ border-color: #5B8DEF; }}"
        f"QPushButton:pressed {{ background: {pressed}; }}"
    )


def list_style() -> str:
    """列表(实例列表/结果列表):圆角条目 + 选中/悬停高亮,自适应主题。"""
    sel = _tz("rgba(91,141,239,0.30)", "rgba(59,142,234,0.20)")
    hover = _tz("rgba(255,255,255,0.08)", "rgba(59,142,234,0.08)")
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
    pane_border = _tz("rgba(255,255,255,0.10)", "rgba(20,30,60,0.14)")
    sel_bg = _tz("rgba(91,141,239,0.16)", "rgba(59,142,234,0.14)")
    text = text_color()
    muted = muted_color()
    return (
        f"QTabWidget::pane {{ border: 1px solid {pane_border}; border-radius: 10px; }}"
        f"QTabBar::tab {{ background: transparent; padding: 7px 16px; margin-right: 4px;"
        f" color: {muted}; border-top-left-radius: 7px; border-top-right-radius: 7px; }}"
        f"QTabBar::tab:selected {{ background: {sel_bg}; color: {text}; font-weight: bold; }}"
        f"QTabBar::tab:hover {{ color: {text}; }}"
    )


def launch_btn_style() -> str:
    """主操作大按钮(启动游戏):蓝色渐变 + 大圆角,自适应主题的蓝。"""
    if is_dark_mode():
        return (
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 #3D80E8, stop:1 #2E6FD8); color: #ffffff; border: none;"
            " border-radius: 12px; font-size: 17px; font-weight: bold; padding: 12px 14px; }"
            "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 #4A8CF0, stop:1 #3D80E8); }"
            "QPushButton:pressed { background: #265FB8; }"
            "QPushButton:disabled { background: #44506A; color: #9AA4B8; }"
        )
    return (
        "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        " stop:0 #2F7FE8, stop:1 #1E6FD9); color: #ffffff; border: none;"
        " border-radius: 12px; font-size: 17px; font-weight: bold; padding: 12px 14px; }"
        "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        " stop:0 #3D8BF2, stop:1 #2F7FE8); }"
        "QPushButton:pressed { background: #175CB5; }"
        "QPushButton:disabled { background: #B9C4D6; color: #EEF1F6; }"
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


def arrow_style() -> str:
    """卡片右侧的展开箭头按钮"""
    return "QPushButton { border: none; background: transparent; color: #888888; }"


def primary_btn_style() -> str:
    """主操作按钮(蓝底白字):深浅色模式用不同蓝色适配,可读性更好"""
    if is_dark_mode():
        return (
            "QPushButton { background: #2E6FD8; color: #FFFFFF; border: none;"
            " border-radius: 6px; padding: 6px 14px; font-weight: bold; }"
            "QPushButton:hover { background: #3D80E8; }"
            "QPushButton:pressed { background: #265FB8; }"
            "QPushButton:disabled { background: #44506A; color: #9AA4B8; }"
        )
    return (
        "QPushButton { background: #1E6FD9; color: #FFFFFF; border: none;"
        " border-radius: 6px; padding: 6px 14px; font-weight: bold; }"
        "QPushButton:hover { background: #2F7FE8; }"
        "QPushButton:pressed { background: #175CB5; }"
        "QPushButton:disabled { background: #B9C4D6; color: #EEF1F6; }"
    )


def menu_btn_style() -> str:
    """左侧菜单按钮(左菜单独立模块用):
    未选中半透明+灰字,悬停提亮,选中=高亮底色+蓝左条+加粗。自适应深色。"""
    sel = _tz("rgba(91,141,239,0.20)", "rgba(59,142,234,0.16)")
    hover = _tz("rgba(255,255,255,0.07)", "rgba(59,142,234,0.08)")
    text = text_color()
    muted = muted_color()
    return (
        f"QPushButton {{ background: transparent; color: {muted}; border: none;"
        f" border-left: 3px solid transparent; border-radius: 8px;"
        f" padding: 9px 12px; text-align: left; font-size: 13px; }}"
        f"QPushButton:hover {{ background: {hover}; color: {text}; }}"
        f"QPushButton:checked {{ background: {sel}; color: {text}; font-weight: bold;"
        f" border-left: 3px solid #5B8DEF; }}"
    )


def hint_style() -> str:
    """灰色提示文字(两种主题下都可读)"""
    return f"color: {muted_color()};"


def apply_global_dark_palette(app) -> None:
    """系统是深色主题时,给整个应用设一套深色 QPalette。

    让那些"没写死色"的默认控件(对话框 / QMenu / QTabWidget / QComboBox 下拉 /
    QMessageBox 等)也变深色,与启动器整体风格一致(此前在 实例详情 等对话框里
    默认控件是系统浅色 → 不搭)。已用样式表写死色的不受影响。"""
    if not is_dark_mode():
        return
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication
    p = QPalette()
    bg = QColor("#23272f")
    base = QColor("#1a1d23")
    text = QColor("#e7ecf5")
    muted = QColor("#8b96a8")
    accent = QColor("#5B8DEF")
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


def inner_style() -> str:
    """卡片内部的标签(透明底,跟卡片背景一致)"""
    return "background: transparent;"
