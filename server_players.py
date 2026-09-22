# -*- coding: utf-8 -*-
"""服务端玩家名单文件:白名单 / OP / 封禁(玩家与 IP)。

这几个文件都是 JSON 数组,但直接手改容易出事:格式错会让**服务端启动失败**,
而空文件或写坏会让**整个名单一次性丢失**。所以这里做成:

- ``parse_*`` / ``render_*`` / ``add_entry`` / ``remove_entry`` 是**纯函数**,便于单测;
- 落盘集中在 :func:`apply_players`,保存前备份、原子写;
- **解析失败拒绝写**:读不出来就绝不覆盖(否则等于把名单删了);
- 服务端运行时拒绝写(与 ``server_properties`` 同一规则)。

各文件的记录结构不同(白名单只有 uuid+name,OP 有等级,封禁有原因),因此新增条目
按文件类型补齐字段,而不是套用同一种模板。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time

#: 文件类型 → (文件名, 中文名, 是否支持 reason 字段)
FILES = {
    'whitelist': ('whitelist.json', '白名单', False),
    'ops': ('ops.json', 'OP 管理员', False),
    'banned-players': ('banned-players.json', '封禁玩家', True),
    'banned-ips': ('banned-ips.json', '封禁 IP', True),
}

BACKUP_SUFFIX = '.bak'


def filename_for(kind: str) -> str:
    return FILES[kind][0]


def label_for(kind: str) -> str:
    return FILES[kind][1]


def file_path(server_root: str, kind: str) -> str:
    return os.path.join(str(server_root), filename_for(kind))


def parse_entries(text: str):
    """解析名单文件 → ``(entries, error)``。

    解析失败时 **entries 为 None** 且给出中文原因,调用方必须据此拒绝写入——
    把读不出来的文件覆盖掉等于销毁用户名单。
    """
    if not (text or '').strip():
        return [], ''      # 空文件视为空名单(服务端首次启动前就是空的)
    try:
        data = json.loads(text)
    except ValueError as error:
        return None, f'文件不是合法 JSON：{error}'
    if not isinstance(data, list):
        return None, '文件内容不是 JSON 数组，已拒绝改写以免丢失名单。'
    out = []
    for item in data:
        if isinstance(item, dict):
            out.append(item)
    return out, ''


def render_entries(entries: list) -> str:
    return json.dumps(entries, ensure_ascii=False, indent=2) + '\n'


def entry_name(entry: dict) -> str:
    """取显示名:玩家名优先,纯 IP 记录回落为 ip。"""
    if not isinstance(entry, dict):
        return ''
    return str(entry.get('name') or entry.get('ip') or '').strip()


def find_index(entries: list, name: str):
    """按名字(或 IP)定位,大小写不敏感。找不到返回 None。"""
    wanted = str(name or '').strip().casefold()
    if not wanted:
        return None
    for index, entry in enumerate(entries or []):
        if entry_name(entry).casefold() == wanted:
            return index
    return None


def add_entry(entries: list, kind: str, *, name: str, uuid: str = '',
              level: int = 4, reason: str = '', expires: str = 'forever'):
    """往名单里加一条;已存在则原样返回(不重复添加)。"""
    clean = str(name or '').strip()
    if not clean:
        raise ValueError('名字不能为空。')
    if find_index(entries, clean) is not None:
        return list(entries or [])
    out = list(entries or [])
    if kind == 'whitelist':
        out.append({'uuid': str(uuid or '').strip(), 'name': clean})
    elif kind == 'ops':
        out.append({'uuid': str(uuid or '').strip(), 'name': clean,
                    'level': int(level), 'bypassesPlayerLimit': False})
    elif kind == 'banned-players':
        out.append({'uuid': str(uuid or '').strip(), 'name': clean,
                    'created': time.strftime('%Y-%m-%d %H:%M:%S +0800'),
                    'source': 'AMCL', 'expires': expires,
                    'reason': reason or 'Banned by operator'})
    elif kind == 'banned-ips':
        out.append({'ip': clean,
                    'created': time.strftime('%Y-%m-%d %H:%M:%S +0800'),
                    'source': 'AMCL', 'expires': expires,
                    'reason': reason or 'Banned by operator'})
    else:
        raise ValueError(f'未知名单类型：{kind}')
    return out


def remove_entry(entries: list, name: str) -> list:
    """按名字(或 IP)移除一条;不存在则原样返回。"""
    index = find_index(entries, name)
    if index is None:
        return list(entries or [])
    out = list(entries or [])
    del out[index]
    return out


def read_entries(server_root: str, kind: str):
    """读磁盘 → ``(entries, error)``;文件不存在视为空名单。"""
    path = file_path(server_root, kind)
    if not os.path.isfile(path):
        return [], ''
    try:
        with open(path, encoding='utf-8', errors='replace') as stream:
            return parse_entries(stream.read())
    except OSError as error:
        return None, f'读取失败：{error}'


def server_running(server_root: str) -> bool:
    try:
        from server_host_client import managed_status
        state = managed_status(server_root, probe=False) or {}
    except Exception:
        return False
    return bool(state.get('running'))


def apply_entries(server_root: str, kind: str, entries: list, *,
                  allow_running: bool = False):
    """备份 + 原子写入名单。返回 ``{'ok','message','backup'}``。"""
    if server_running(server_root) and not allow_running:
        return {'ok': False, 'backup': None,
                'message': '服务端正在运行，改名单可能不会生效（服务端会在退出时'
                           '覆盖它）。请先停止服务端。'}
    existing, error = read_entries(server_root, kind)
    if error:
        return {'ok': False, 'backup': None,
                'message': f'没有写入：现有 {filename_for(kind)} {error}'}
    path = file_path(server_root, kind)
    backup = None
    if os.path.isfile(path):
        candidate = path + BACKUP_SUFFIX
        if not os.path.exists(candidate):
            try:
                shutil.copy2(path, candidate)
                backup = candidate
            except OSError as copy_error:
                return {'ok': False, 'backup': None,
                        'message': f'备份失败，已中止写入：{copy_error}'}
        else:
            backup = candidate
    folder = os.path.dirname(os.path.abspath(path)) or '.'
    os.makedirs(folder, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.amcl-list-', dir=folder)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(render_entries(entries))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as write_error:
        return {'ok': False, 'backup': backup,
                'message': f'写入失败：{write_error}'}
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {'ok': True, 'backup': backup,
            'message': f'已保存 {label_for(kind)}（{len(entries)} 条）'
                       + (f'，原始文件备份为 {os.path.basename(backup)}。' if backup else '。')}
