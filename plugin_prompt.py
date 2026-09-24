# -*- coding: utf-8 -*-
"""「检测到 mod → 提示装对应插件」机制。

**为什么需要**:插件最大的问题是**没人知道它存在**。而「装了某个 mod 的人一定需要它
对应的管理页」是个强信号——所以核心在扫到实例装了某 mod、而对应插件还没启用时,
问用户一次。

红线(不做就会变成骚扰,见 docs/PLUGIN_IDEAS.md):
- **只问一次**;用户的选择(包括「不要」)要记住,之后不再打扰;
- **绝不静默安装或启用**插件;
- 只在**真的检测到**该 mod 时才问;
- 没有对应插件时什么都不做,不硬塞残缺的内置页。

本模块只做判断(纯逻辑),非模态提示与启用动作在 :mod:`main` 里。
"""
from __future__ import annotations

import os

#: 记录用户对「某插件」的提示结果:``{plugin_id: 'declined'}``。
#: 只有明确拒绝才写这条;同意后插件本身会处于启用状态,不需要额外记录。
DECLINED_KEY = 'plugin_prompt_declined'
#: 记录已经提示过但用户当场忽略的,避免同一次会话反复问。
SEEN_KEY = 'plugin_prompt_seen'


def watched_mods(plugin_module) -> tuple:
    """读插件元数据里声明的 ``WATCH_MODS``(缺失或格式不对则忽略)。"""
    value = getattr(plugin_module, 'WATCH_MODS', ()) or ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(str(item) for item in value if str(item).strip())
    except TypeError:
        return ()


def installed_mod_names(game_dir: str) -> set:
    """扫所有实例的 mods 目录,收集**已安装**的 mod 文件名(小写)。

    只看文件名:插件声明的 WATCH_MODS 是 mod id/关键字(如 ``kubejs``),
    而 mod 文件名里就含这个关键字的概率很高(``kubejs-forge-...jar``),
    这正是核心既有的 ``_has_mod`` 判定口径,保持一致。
    """
    names = set()
    versions = os.path.join(game_dir, 'versions')
    if not os.path.isdir(versions):
        return names
    try:
        folders = os.listdir(versions)
    except OSError:
        return names
    for folder in folders:
        if folder.startswith('_'):
            continue
        mods = os.path.join(versions, folder, 'mods')
        if not os.path.isdir(mods):
            continue
        try:
            entries = os.listdir(mods)
        except OSError:
            continue
        for entry in entries:
            if entry.lower().endswith(('.jar', '.jar.disabled')):
                names.add(entry.lower())
    return names


def mod_present(mods: set, keys) -> bool:
    """是否装了其中任一关键字对应的 mod(与核心 ``_has_mod`` 同口径)。"""
    if not mods:
        return False
    for key in keys or ():
        needle = str(key or '').strip().lower()
        if needle and any(needle in name for name in mods):
            return True
    return False


def pending_prompts(settings: dict, installed: set, candidates: list) -> list:
    """算出该提示哪些插件。

    ``candidates`` = ``[(plugin_id, plugin_name, watch_mods)]``,只包含**当前未启用**
    的插件(启用中的不需要提示)。返回 ``[{'id','name','mods'}]``。

    已经被拒绝过的、或已经提示过被忽略的,都不再出现在结果里。
    """
    declined = set((settings or {}).get(DECLINED_KEY, []) or [])
    seen = set((settings or {}).get(SEEN_KEY, []) or [])
    out = []
    for plugin_id, plugin_name, keys in candidates or []:
        if not plugin_id or not keys:
            continue
        if plugin_id in declined or plugin_id in seen:
            continue
        if mod_present(installed, keys):
            out.append({'id': plugin_id, 'name': plugin_name or plugin_id,
                        'mods': tuple(keys)})
    return out


def remember(settings: dict, plugin_id: str, *, declined: bool) -> dict:
    """把用户的选择写回设置副本(调用方负责 save_settings)。

    拒绝 → 记进 ``declined``(以后不再问);同意/忽略 → 记进 ``seen``。
    """
    data = dict(settings or {})
    key = DECLINED_KEY if declined else SEEN_KEY
    values = list(data.get(key, []) or [])
    if plugin_id and plugin_id not in values:
        values.append(plugin_id)
    data[key] = values
    return data


def missing_candidates(settings: dict) -> list:
    """当前**未启用**且声明了 WATCH_MODS 的插件 → ``[(id, name, mods)]``。

    已启用的插件不需要提示。候选 = **默认关闭、且用户没显式关掉**的插件:
    默认打开的不存在「装不装」的问题;而用户自己关掉的那个,他的关闭动作就是
    答案,再弹窗就是骚扰(红线之一)。
    """
    import plugin_manager as pm
    out = []
    try:
        metas = pm.discover_plugins_meta()
    except Exception:
        return out
    turned_off = set((settings or {}).get('plugins_disabled', []) or [])
    for name, meta in (metas or {}).items():
        if bool(meta.get('default_enabled', True)):
            continue                      # 默认启用,不存在"装不装"的问题
        if name in turned_off:
            continue                      # 用户主动关的,别再问
        if not pm.plugin_is_disabled(settings or {}, name):
            continue                      # 已经启用
        module = _load_meta_module(name)
        keys = watched_mods(module) if module is not None else ()
        if keys:
            out.append((name, str(meta.get('name') or name), keys))
    return out


def _load_meta_module(name: str):
    """按名字把插件模块加载起来,只为读取 WATCH_MODS。"""
    import plugin_manager as pm
    for candidate, path in pm.discover_plugins():
        if candidate == name:
            try:
                return pm._load_plugin_module(path)
            except Exception:
                return None
    return None
