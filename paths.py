# -*- coding: utf-8 -*-
"""路径常量:整个项目共用的游戏目录位置。

支持在设置/首次引导里改路径:
- set_game_dir() 更新模块级 GAME_DIR / RUNTIME_DIR,改完立即全局生效
- 模块导入时会先读 config.json 里保存的 game_dir(有则优先,没有就用默认 .minecraft)
"""
import json
import os

_BASE = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_BASE, "config.json")
DEFAULT_GAME_DIR = os.path.join(_BASE, ".minecraft")


def _saved_game_dir() -> str:
    """config.json 里用户保存的游戏目录(空 = 未配置)"""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        g = data.get("game_dir")
        if isinstance(g, str) and g.strip():
            return g.strip()
    except Exception:
        pass
    return ""


GAME_DIR = _saved_game_dir() or DEFAULT_GAME_DIR
RUNTIME_DIR = os.path.join(GAME_DIR, "runtime")


def set_game_dir(path: str) -> None:
    """更新全局游戏目录(设置/引导界面保存后调用)。空值回到默认位置。"""
    global GAME_DIR, RUNTIME_DIR
    p = (path or "").strip()
    GAME_DIR = p if p else DEFAULT_GAME_DIR
    RUNTIME_DIR = os.path.join(GAME_DIR, "runtime")


def looks_like_game_dir(path: str) -> bool:
    """粗略判断一个目录是不是 .minecraft(有 versions / assets / libraries 之一)"""
    if not path:
        return False
    for sub in ("versions", "assets", "libraries"):
        if os.path.isdir(os.path.join(path, sub)):
            return True
    return False
