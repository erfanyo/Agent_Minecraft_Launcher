# -*- coding: utf-8 -*-
"""
深色模式兼容:根据系统主题返回合适的卡片/箭头/提示文字样式。

之前用写死的浅色背景(#f5f5f5),系统是深色主题时文字是白的 → 白底白字。
现在所有"卡片"样式统一从这里取,深浅色各一套。
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
        # 深色模式用亮一些的蓝,白字更醒目
        return (
            "QPushButton { background: #2E6FD8; color: #FFFFFF; border: none;"
            " border-radius: 6px; padding: 6px 14px; font-weight: bold; }"
            "QPushButton:hover { background: #3D80E8; }"
            "QPushButton:pressed { background: #265FB8; }"
            "QPushButton:disabled { background: #44506A; color: #9AA4B8; }"
        )
    # 浅色模式用标准蓝
    return (
        "QPushButton { background: #1E6FD9; color: #FFFFFF; border: none;"
        " border-radius: 6px; padding: 6px 14px; font-weight: bold; }"
        "QPushButton:hover { background: #2F7FE8; }"
        "QPushButton:pressed { background: #175CB5; }"
        "QPushButton:disabled { background: #B9C4D6; color: #EEF1F6; }"
    )


def hint_style() -> str:
    """灰色提示文字(两种主题下都可读)"""
    return "color: #888888;"


def inner_style() -> str:
    """卡片内部的标签(透明底,跟卡片背景一致)"""
    return "background: transparent;"
