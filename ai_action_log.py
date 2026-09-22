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
from log_privacy import redact, sensitive_key


def recent_text(limit=30):
    from ai_actions import recent_text as read_recent
    return read_recent(limit)


def _plain_preview(name: str, args: dict) -> str:
    instance = args.get('instance') or '当前实例'
    enabled = bool(args.get('enabled'))
    reason = str(args.get('reason') or '')
    mod_change = (f'这个 Mod 是给另一个游戏版本或加载器的，当前实例不能用，所以会从本次启动中移出；'
                  f'原文件仍会保留：“{args.get("filename") or "这个 Mod"}”。'
                  if not enabled and reason in {'wrong_game_version', 'wrong_loader'} else
                  f'{"恢复到本次启动" if enabled else "暂时从本次启动中移出"}“{args.get("filename") or "这个 Mod"}”；文件不会删除。')
    summaries = {
        'snapshot_instance': f'保存“{instance}”当前状态，方便出现问题时恢复。',
        'restore_instance_snapshot': f'把“{instance}”恢复到之前保存的状态；现在的状态也会保留。',
        'repair_instance_core': f'补齐“{instance}”缺少或损坏的游戏文件；存档和 Mod 会保留。',
        'complete_instance_files': f'补齐“{instance}”运行需要的文件；存档和 Mod 会保留。',
        'reset_instance': f'恢复“{instance}”的启动、画面和按键设置；存档和 Mod 会保留。',
        'set_mod_enabled': mod_change,
        'replace_mod_version': f'把“{args.get("filename") or "这个 Mod"}”换成兼容版本；旧文件会保留。',
        'install_mod': f'给“{instance}”安装 {args.get("slug") or "这个 Mod"}。',
        'install_mods': f'给“{instance}”安装选中的一组 Mod。',
        'set_setting': f'把启动器设置“{args.get("key") or "指定项目"}”改为“{args.get("value", "")}”。',
        'send_game_command': f'立即在“{instance}”的当前世界执行一条游戏指令。',
        'install_instance': '保留当前实例，创建一个新的独立游戏实例，并下载运行所需文件。',
        'install_modpack': '创建一个新的独立整合包实例，不覆盖当前实例。',
        'create_plugin': '给启动器添加一项新功能；需要重启启动器后生效。',
        'set_server_mod_enabled': (
            f'{"恢复启用" if enabled else "暂时停用"}服务端“{args.get("server") or "当前服务端"}”中的'
            f'“{args.get("filename") or "这个 Mod"}”；只重命名文件，不会删除。'),
    }
    return summaries.get(name, '执行完成当前任务所需的一项操作。')


def preview(name: str, args: dict, response_style: str = 'technical') -> str:
    """返回适合确认弹窗显示的中文变更清单。"""
    args = dict(args or {})
    if response_style == 'plain':
        return _plain_preview(name, args)
    if name in {'snapshot_instance', 'restore_instance_snapshot', 'set_mod_enabled',
                'replace_mod_version', 'set_server_mod_enabled'}:
        scopes = {'snapshot_instance': '复制完整实例，默认锁定 MC 和加载器；需要额外磁盘空间。',
                  'restore_instance_snapshot': '恢复指定快照，当前实例先移到保留目录；不是合并文件。',
                  'set_mod_enabled': '改变指定 Mod 启用状态，可能影响依赖和存档内容；不删除文件。',
                  'replace_mod_version': '下载并校验指定版本后替换旧 JAR；旧文件保留，前置不自动安装。',
                  'set_server_mod_enabled': '改变单个服务端 Mod 的启用状态；服务端必须已停止，只重命名文件，不删除。'}
        return scopes[name] + '\n具体参数：' + json.dumps(args, ensure_ascii=False)
    if name in {'repair_instance_core', 'complete_instance_files', 'reset_instance'}:
        from instance_maintenance import maintenance_preview
        return maintenance_preview(name, args)
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
    from settings import load_settings
    rows = redact(rows, load_settings())
    for row in rows:
        if sensitive_key((row.get("undo") or {}).get("key", "")):
            row["undo"] = {}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows[-200:], f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return rows[-1]


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
        if not key or sensitive_key(key):
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
