# -*- coding: utf-8 -*-
"""
轻量国际化:根据系统语言自动选择界面语言(可在设置里覆盖)。
- language 设置:auto(跟随系统)/ zh / en
- t(zh, en):按当前语言返回文字;英文没提供时回退中文
- 切换语言后重启启动器生效(界面文字是启动时固定的)
"""
import locale

_current = "zh"


def detect_system_language() -> str:
    """检测系统语言:中文系统 → zh,其他 → en"""
    try:
        code = (locale.getdefaultlocale()[0] or "").lower()
    except Exception:
        code = ""
    return "zh" if code.startswith("zh") else "en"


def set_language(lang: str):
    """lang: auto(跟随系统)/ zh / en"""
    global _current
    _current = detect_system_language() if lang == "auto" else (lang or "zh")


def get_language() -> str:
    return _current


def t(zh: str, en: str = "") -> str:
    """取当前语言的文字;英文未提供时回退中文"""
    if _current == "en" and en:
        return en
    return zh
