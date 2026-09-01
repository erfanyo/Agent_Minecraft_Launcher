# -*- coding: utf-8 -*-
"""AI actions: permission boundaries, previews, and an auditable local log."""
from __future__ import annotations

import json
import os
from datetime import datetime

from paths import BASE_DIR as WORKSPACE
from paths import CONFIG_DIR as AMCL_DIR
from paths import GAME_DIR as GAME_DIR_ACTIVE
from paths import data_dir

PERMISSIONS = [
    ("只读（不能修改任何文件）", "readonly"),
    ("启动器与游戏目录可写（默认）", "launcher_write"),
    ("工作区可写（可生成插件/改源码）", "workspace_write"),
]


class PermissionDenied(PermissionError):
    """AI action exceeded its allowed scope."""


def permission_allows_write(settings: dict) -> bool:
    return settings.get("ai_permission", "launcher_write") in {"launcher_write", "workspace_write"}


def permission_allows_workspace_write(settings: dict) -> bool:
    return settings.get("ai_permission", "launcher_write") == "workspace_write"


def permission_instructions(settings: dict) -> str:
    if permission_allows_workspace_write(settings):
        return ("你的文件权限：工作区可写。你可写启动器工作区、AMCL 私有数据目录和游戏目录，"
                "但绝不能写这些之外的路径。任何改动前先说明计划。")
    if permission_allows_write(settings):
        return ("你的文件权限：启动器与游戏目录可写。你可在 AMCL 私有数据目录和游戏目录(.minecraft)"
                "执行装 Mod、下载实例、修改设置等日常操作；不能写启动器源码或插件目录。任何改动前先说明计划。")
    return "你的文件权限：只读。你只能阅读和分析，绝不能修改、删除或创建任何文件。"


def _writable_roots(include_workspace: bool = False) -> list[str]:
    roots = (WORKSPACE, AMCL_DIR, GAME_DIR_ACTIVE) if include_workspace else (AMCL_DIR, GAME_DIR_ACTIVE)
    return [os.path.abspath(root) for root in roots if root]


def is_within_workspace(path: str, include_workspace: bool = False) -> bool:
    abs_path = os.path.abspath(path)
    return any(abs_path == root or abs_path.startswith(root + os.sep)
               for root in _writable_roots(include_workspace))


def require_launcher_write(settings: dict) -> None:
    if not permission_allows_write(settings):
        raise PermissionDenied("AI 当前是只读权限，不能修改文件（可切换到“启动器与游戏目录可写”）。")


def require_workspace_write(settings: dict) -> None:
    if not permission_allows_workspace_write(settings):
        raise PermissionDenied("此操作需要“工作区可写”权限；默认的“启动器与游戏目录可写”不包含源码和插件目录。")


def safe_write_path(settings: dict, path: str) -> str:
    require_launcher_write(settings)
    abs_path = os.path.abspath(path)
    if not is_within_workspace(abs_path, permission_allows_workspace_write(settings)):
        raise PermissionDenied(f"写入路径不在允许范围内，已拒绝：{abs_path}")
    return abs_path


def preview(name: str, args: dict) -> str:
    """Return a concise, user-facing change set before an action runs."""
    args = dict(args or {})
    if name == "install_mod":
        return (f"安装 Mod\n实例：{args.get('instance', '未指定')}\nMod：{args.get('slug', '未指定')}\n"
                f"版本：{args.get('version') or '自动选择兼容最新版'}\n位置：该实例的 mods 目录\n"
                "执行前会创建实例备份；执行后可在操作记录中追踪。")
    if name == "install_mods":
        mods = args.get("slugs", [])
        mods = "、".join(map(str, mods)) if isinstance(mods, list) else str(mods)
        return f"批量安装 Mod\n实例：{args.get('instance', '未指定')}\nMod：{mods or '未指定'}\n位置：该实例的 mods 目录\n执行前会创建实例备份。"
    if name == "set_setting":
        from settings import load_settings
        key = str(args.get("key", ""))
        return (f"修改启动器设置\n设置项：{key or '未指定'}\n当前值：{load_settings().get(key, '（不存在）')}\n"
                f"新值：{args.get('value', '')}\n此类操作会记录旧值，可从操作记录中回退。")
    if name == "send_game_command":
        return (f"向游戏发送指令\n实例：{args.get('instance', '未指定')}\n"
                f"指令：/{str(args.get('command', '')).lstrip('/')}\n指令会立即影响当前世界；部分游戏指令无法由启动器撤销。")
    if name == "install_instance":
        return f"创建游戏实例\nMinecraft：{args.get('version', '未指定')}\n加载器：{args.get('loader') or '原版'}\n位置：.minecraft/versions；会下载游戏文件和依赖。"
    if name == "install_modpack":
        return f"下载并导入整合包\n来源：{args.get('slug_or_url', '未指定')}\n会创建新的独立实例并下载整合包文件。"
    if name == "create_plugin":
        return f"生成启动器插件\n名称：{args.get('name', '未指定')}\n位置：启动器 plugins 目录\n写入前会做语法与危险 import 审计；生成后需要重启才能加载。"
    return f"执行操作：{name}\n参数：{args}"


def _load_rows(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def record(name: str, args: dict, result: str, approved: bool = True, undo: dict | None = None) -> dict:
    path = os.path.join(data_dir(), "ai_actions.json")
    rows = _load_rows(path)
    item = {"time": datetime.now().astimezone().isoformat(timespec="seconds"), "action": name,
            "args": dict(args or {}), "result": str(result or ""), "approved": bool(approved),
            "undo": dict(undo or {})}
    rows.append(item)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows[-200:], f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return item


def recent_text(limit: int = 30) -> str:
    rows = _load_rows(os.path.join(data_dir(), "ai_actions.json"))[-limit:]
    if not rows:
        return "还没有 AI 操作记录。"
    return "\n\n".join(
        f"{r.get('time', '')}\n{r.get('action', '')} · {'已确认' if r.get('approved') else '已取消'}\n"
        f"参数：{json.dumps(r.get('args', {}), ensure_ascii=False)}\n结果：{r.get('result', '')}\n"
        f"回退：{r.get('undo') or '不可自动回退'}" for r in reversed(rows))


def undo_last_setting() -> str:
    path = os.path.join(data_dir(), "ai_actions.json")
    rows = _load_rows(path)
    for row in reversed(rows):
        undo = row.get("undo") or {}
        if undo.get("kind") != "setting" or not undo.get("key"):
            continue
        from settings import load_settings, save_settings
        import paths
        settings = load_settings()
        settings[undo["key"]] = undo.get("value")
        if undo["key"] == "game_dir":
            paths.set_game_dir(settings[undo["key"]])
        save_settings(settings)
        row["undo"] = {"kind": "used"}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rows[-200:], f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return f"已撤销 AI 对设置 {undo['key']} 的最近一次修改，恢复为：{settings[undo['key']]}"
    return "没有找到可撤销的 AI 设置修改。"
