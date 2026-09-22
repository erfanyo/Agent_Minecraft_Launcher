# -*- coding: utf-8 -*-
"""KubeJS 工具的「选哪个整合实例/服务端」逻辑(纯函数,便于单测)。

插件不能像核心那样挂进实例详情/服务端详情的左菜单(插件 API 只提供主标签页与
联机中心页),所以插件自带一个目标选择器:列出**存在 kubejs 目录**的实例与服务端,
选中后打开对应目录。

这里只做「枚举 + 过滤 + 排序」,不碰 Qt;UI 在 ``plugins/kubejs_tools.py``。
"""
from __future__ import annotations

import os


def instance_targets(game_dir: str) -> list:
    """客户端实例中带 kubejs 目录的 → 目标列表。"""
    from instances import scan_instances
    out = []
    try:
        items = scan_instances(game_dir)
    except Exception:
        return out
    for inst in items:
        folder = inst.get('path') or os.path.join(
            game_dir, 'versions', str(inst.get('id') or ''))
        kubejs = os.path.join(folder, 'kubejs')
        if os.path.isdir(kubejs):
            out.append({
                'kind': 'client',
                'id': str(inst.get('id') or ''),
                'name': str(inst.get('name') or inst.get('id') or ''),
                'kubejs': kubejs,
            })
    return out


def server_targets(game_dir: str) -> list:
    """服务端中带 kubejs 目录的 → 目标列表。

    服务端的游戏目录是记录里的 ``path``(可能是包内的 ``server/`` 子目录)。
    """
    from server_packs import list_servers
    out = []
    try:
        items = list_servers(game_dir)
    except Exception:
        return out
    for server in items:
        root = server.get('path') or ''
        kubejs = os.path.join(root, 'kubejs')
        if root and os.path.isdir(kubejs):
            out.append({
                'kind': 'server',
                'id': str(server.get('id') or ''),
                'name': str(server.get('name') or server.get('id') or ''),
                'kubejs': kubejs,
            })
    return out


def all_targets(game_dir: str) -> list:
    """全部目标:int 端在前、服务端在后,各自按名字排序。

    客户端在前是因为「插件主要给整合包作者用」,作者改客户端脚本更频繁;
    服务端脚本也一起看得到,不至于要装两个插件。
    """
    client = sorted(instance_targets(game_dir), key=lambda t: t['name'].casefold())
    server = sorted(server_targets(game_dir), key=lambda t: t['name'].casefold())
    return client + server


def label_for(target: dict) -> str:
    """下拉里显示的文字;标明来源端,避免同名实例分不清。"""
    kind = '客户端' if target.get('kind') == 'client' else '服务端'
    return f"[{kind}] {target.get('name') or target.get('id')}"


def find_target(targets: list, target_id: str):
    """按 id 找目标;``target_id`` 形如 ``'client:地下酒吧'``。"""
    kind, _, ident = str(target_id or '').partition(':')
    for target in targets or []:
        if target.get('kind') == kind and target.get('id') == ident:
            return target
    return None


def target_key(target: dict) -> str:
    """稳定键,用于记住上次选择。"""
    return f"{target.get('kind')}:{target.get('id')}"


def script_count(kubejs_root: str) -> int:
    """脚本目录下的 .js 数量(只统计脚本目录,不含 assets/data)。"""
    total = 0
    for sub in ('server_scripts', 'startup_scripts', 'client_scripts'):
        root = os.path.join(kubejs_root, sub)
        if not os.path.isdir(root):
            continue
        for _base, _dirs, files in os.walk(root):
            total += sum(1 for name in files if name.lower().endswith('.js'))
    return total
