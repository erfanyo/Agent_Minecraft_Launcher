"""Plain-language checks for the game directory selected during onboarding."""
from __future__ import annotations

from dataclasses import dataclass
import os
import tempfile


@dataclass(frozen=True)
class PathAssessment:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _inside(path: str, parent: str) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(path), os.path.normcase(parent)]) == os.path.normcase(parent)
    except (OSError, ValueError):
        return False


def assess_game_path(path: str, environment=None) -> PathAssessment:
    """Find early path problems without creating or changing any directories."""
    raw = (path or "").strip()
    if not raw:
        return PathAssessment(errors=("还没有选择游戏文件夹。",))
    expanded = os.path.abspath(os.path.expanduser(os.path.expandvars(raw)))
    errors = []
    warnings = []

    if os.path.exists(expanded) and not os.path.isdir(expanded):
        errors.append("这里是一个文件，不是文件夹。")
    ancestor = expanded
    while ancestor and not os.path.exists(ancestor):
        parent = os.path.dirname(ancestor)
        if parent == ancestor:
            break
        ancestor = parent
    if ancestor and os.path.exists(ancestor) and not os.access(ancestor, os.W_OK):
        errors.append("这个位置不能写入，请换到你有权限的文件夹。")

    if any(ord(char) > 127 for char in expanded):
        warnings.append("路径含中文或特殊字符；少数旧 Java、加载器或驱动可能无法识别。")
    if expanded.startswith("\\\\"):
        warnings.append("这是网络共享位置；断网或共享断开时，游戏和 Java 会无法启动。")
    if len(expanded) > 120:
        warnings.append("路径已经很长，安装 Mod 后可能超过 Windows 的长度限制。")

    env = os.environ if environment is None else environment
    temp_root = os.path.abspath(tempfile.gettempdir())
    if _inside(expanded, temp_root):
        warnings.append("这是临时文件夹，Windows 清理空间时可能把游戏一起删除。")
    onedrive = (env.get("OneDrive") or env.get("OneDriveConsumer") or "").strip()
    if onedrive and _inside(expanded, os.path.abspath(onedrive)):
        warnings.append("这是同步盘目录，文件同步可能与游戏更新互相冲突。")

    return PathAssessment(tuple(dict.fromkeys(errors)), tuple(dict.fromkeys(warnings)))

