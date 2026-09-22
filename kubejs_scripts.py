# -*- coding: utf-8 -*-
"""KubeJS 脚本目录的读取工具(纯逻辑,供插件与核心共用)。

**为什么放在核心而不是插件里**:插件目录 ``plugins/`` 的每个 ``.py`` 都会被
插件系统当成一个插件去加载(会要求 ``register(api)``),所以插件**不能**靠"再放一个
``.py``"来拆分模块——那样会被误当成第二个插件。因此可复用的纯逻辑放核心,
插件只放界面与装配。

这些函数都不碰 Qt,便于单测;也不做任何写入。
"""
from __future__ import annotations

import os

#: 单个脚本的显示上限(字符)。超过只显示开头,并明确提示。
MAX_PREVIEW_CHARS = 200_000

#: 视为「可查看文本」的后缀。
TEXT_SUFFIXES = ('.js', '.json', '.txt', '.snbt', '.properties', '.toml',
                 '.md', '.mcfunction', '.csv', '.yml', '.yaml')


def build_script_tree(root: str) -> list:
    """把 ``kubejs`` 目录扫成 ``[{'name','path','is_dir','children'}]``。

    纯函数式(只读目录),方便单测;不跟随符号链接,跳过隐藏项。
    """
    out = []
    if not root or not os.path.isdir(root):
        return out
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for name in names:
        if name.startswith('.'):
            continue
        full = os.path.join(root, name)
        if os.path.islink(full):
            continue
        if os.path.isdir(full):
            out.append({'name': name, 'path': full, 'is_dir': True,
                        'children': build_script_tree(full)})
        else:
            out.append({'name': name, 'path': full, 'is_dir': False,
                        'children': []})
    return out


def is_viewable(path: str) -> bool:
    """该文件是否属于可预览的文本类型。"""
    return os.path.splitext(path)[1].lower() in TEXT_SUFFIXES


def read_script(path: str):
    """读脚本 → ``(text, truncated, error)``。任何失败都返回可展示的说明。"""
    if not path or not os.path.isfile(path):
        return '', False, '文件不存在'
    try:
        size = os.path.getsize(path)
    except OSError as error:
        return '', False, f'读取失败：{error}'
    try:
        with open(path, encoding='utf-8', errors='replace') as stream:
            text = stream.read(MAX_PREVIEW_CHARS + 1)
    except OSError as error:
        return '', False, f'读取失败：{error}'
    truncated = len(text) > MAX_PREVIEW_CHARS or size > MAX_PREVIEW_CHARS
    if truncated:
        text = text[:MAX_PREVIEW_CHARS]
    return text, truncated, ''
