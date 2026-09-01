# -*- coding: utf-8 -*-
"""AI 操作的预览和审计记录。

这里不执行动作，只负责把模型的“工具调用”变成用户看得懂的变更说明，并把执行结果
追加到 AMCL/ai_actions.json。实际权限和执行仍由 assistant.build_executor 负责。
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from paths import data_dir


def preview(name: str, args: dict) -> str:
    """返回适合确认弹窗显示的中文变更清单。"""
    args = dict(args or {})
    if name == "install_mod":
        version = args.get("version") or "自动选择兼容最新版"
        return (f"安装 Mod\n实例：{args.get('instance', '未指定')}\n"
                f"Mod：{args.get('slug', '未指定')}\n版本：{version}\n"
                "位置：该实例的 .minecraft/versions/<实例>/mods\n"
                "执行前会创建实例备份；执行后可在操作记录中追踪。")
    if name == "install_mods":
        mods = args.get("slugs", [])
        mods = "、".join(map(str, mods)) if isinstance(mods, list) else str(mods)
        return (f"批量安装 Mod\n实例：{args.get('instance', '未指定')}\n"
                f"Mod：{mods or '未指定'}\n位置：该实例的 mods 目录\n"
                "执行前会创建实例备份。")
    if name == "set_setting":
        from settings import load_settings
        key = str(args.get("key", ""))
        before = load_settings().get(key, "（不存在）")
        return (f"修改启动器设置\n设置项：{key or '未指定'}\n"
                f"当前值：{before}\n新值：{args.get('value', '')}\n"
                "此类操作会记录旧值，可从操作记录中回退。")
    if name == "send_game_command":
        return (f"向游戏发送指令\n实例：{args.get('instance', '未指定')}\n"
                f"指令：/{str(args.get('command', '')).lstrip('/')}\n"
                "指令会立即影响当前世界；部分游戏指令无法由启动器撤销。")
    if name == "install_instance":
        return (f"创建游戏实例\nMinecraft：{args.get('version', '未指定')}\n"
                f"加载器：{args.get('loader') or '原版'}\n"
                "位置：.minecraft/versions；会下载游戏文件和依赖。")
    if name == "install_modpack":
        return (f"下载并导入整合包\n来源：{args.get('slug_or_url', '未指定')}\n"
                "会创建一个新的独立实例并下载整合包文件。")
    if name == "create_plugin":
        return (f"生成启动器插件\n名称：{args.get('name', '未指定')}\n"
                "位置：启动器 plugins 目录\n"
                "代码会在写入前做语法与危险 import 审计；生成后需要重启才能加载。")
    return f"执行操作：{name}\n参数：{args}"


def record(name: str, args: dict, result: str, approved: bool = True, undo: dict | None = None) -> dict:
    """保存最近 200 条操作记录。失败/取消也记录，方便追查 AI 做过什么。"""
    path = os.path.join(data_dir(), "ai_actions.json")
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
            rows = raw if isinstance(raw, list) else []
    except Exception:
        pass
    item = {
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "action": name,
        "args": dict(args or {}),
        "result": str(result or ""),
        "approved": bool(approved),
        "undo": dict(undo or {}),
    }
    rows.append(item)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows[-200:], f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return item


def undo_last_setting() -> str:
    """撤销最近一条可回退的设置修改；Mod 安装保留其自动备份，不在这里盲删文件。"""
    path = os.path.join(data_dir(), "ai_actions.json")
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
    except Exception:
        rows = []
    for row in reversed(rows if isinstance(rows, list) else []):
        undo = row.get("undo") or {}
        if undo.get("kind") != "setting":
            continue
        key = undo.get("key")
        if not key:
            continue
        from settings import load_settings, save_settings
        import paths
        settings = load_settings()
        settings[key] = undo.get("value")
        if key == "game_dir":
            paths.set_game_dir(settings[key])
        save_settings(settings)
        row["undo"] = {"kind": "used"}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rows[-200:], f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return f"已撤销 AI 对设置 {key} 的最近一次修改，恢复为：{settings[key]}"
    return "没有找到可撤销的 AI 设置修改。"
