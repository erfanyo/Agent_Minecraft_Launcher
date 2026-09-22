# -*- coding: utf-8 -*-
"""``server.properties`` 的落盘层:读取、备份、写入,以及「服务端运行中拒绝写」。

与 :mod:`server_properties` 的分工:那个模块是**纯函数**(解析/校验/序列化),
本模块负责**碰磁盘**的部分,便于单测里把纯逻辑与 IO 分开。

安全规则(与 ``agent_tools.set_server_mod_enabled`` 一致的先例):

1. **运行中拒绝写**。服务端运行时会持有/重写该文件,此时写入要么无效要么被覆盖;
   因此先用 ``server_host_client.managed_status`` 判断,运行中直接拒绝并说明原因。
2. **写前必备份**。首次修改生成 ``server.properties.bak``(已存在则不覆盖,保留
   用户最早的原始版本),避免改坏之后无从回退。
3. **原子写**。临时文件 + ``os.replace``,避免写一半断电留下半截文件。
4. **编码**。官方规范是 ISO-8859-1(latin-1);用 ``errors='replace'`` 读,写回尽量
   保持 latin-1,遇到无法编码的字符则退回 UTF-8 并在返回值里说明。
"""
from __future__ import annotations

import os
import shutil
import tempfile

from server_properties import parse, serialize, set_values, validate_all

#: 官方规范编码。Minecraft 原生按 latin-1 读取该文件。
ENCODING = 'latin-1'
BACKUP_SUFFIX = '.bak'


def properties_path(server_root: str) -> str:
    return os.path.join(str(server_root), 'server.properties')


def read_text(path: str):
    """读文件 → ``(text, encoding_used)``;不存在返回 ``('', ENCODING)``。

    编码判定顺序很关键:**先试 UTF-8,失败才退回官方的 latin-1**。
    反向(先 latin-1)是错的——latin-1 能解出任意字节序列、永不报错也永不产生
    U+FFFD,于是「用替换符判断是否 UTF-8」这一支永远不会命中;实测整合包作者
    用 UTF-8 存的中文注释会被整片解成乱码。
    纯 ASCII 两种编码结果一致,因此先试 UTF-8 不会改变常见文件的读法。
    """
    if not os.path.isfile(path):
        return '', ENCODING
    with open(path, 'rb') as stream:
        raw = stream.read()
    try:
        return raw.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        return raw.decode(ENCODING, errors='replace'), ENCODING


def read_values(server_root: str) -> dict:
    """读取当前键值映射(文件不存在返回空 dict)。"""
    text, _encoding = read_text(properties_path(server_root))
    from server_properties import as_dict
    return as_dict(parse(text))


def server_running(server_root: str) -> bool:
    """服务端是否正由 AMCL 托管运行。探测失败按「未运行」处理但不吞错。"""
    try:
        from server_host_client import managed_status
        state = managed_status(server_root, probe=False) or {}
    except Exception:
        return False
    return bool(state.get('running'))


def plan_update(server_root: str, changes: dict):
    """计算「改这些键」的结果,但不落盘。

    返回 ``{'ok','path','text','problems','before','after'}``;
    ``problems`` 非空时 ``ok=False``,调用方应把校验信息展示给用户。
    """
    path = properties_path(server_root)
    text, encoding = read_text(path)
    records = parse(text)
    problems = validate_all(changes)
    updated = set_values(records, changes)
    new_text = serialize(updated)
    # 用 latin-1 编码失败(例如中文 motd)时退回 UTF-8——服务端多数版本可读,
    # 但要在结果里标注,避免用户以为一定兼容。
    if encoding == 'latin-1':
        try:
            new_text.encode(ENCODING)
        except UnicodeEncodeError:
            encoding = 'utf-8'
    return {
        'ok': not problems, 'path': path, 'text': new_text,
        'encoding': encoding, 'problems': problems,
        'before': {record['key']: record.get('value', '')
                   for record in records if record.get('kind') == 'entry'},
        'changed': dict(changes or {}),
    }


def apply_update(server_root: str, changes: dict, *, allow_running: bool = False):
    """校验 + 备份 + 原子写入。返回 ``{'ok','message','backup','path'}``。

    这是唯一会写 ``server.properties`` 的入口,保证「运行中拒绝写」不会漏。
    """
    if not changes:
        return {'ok': False, 'message': '没有任何改动。', 'backup': None, 'path': None}
    if server_running(server_root) and not allow_running:
        return {'ok': False, 'backup': None, 'path': None,
                'message': '服务端正在运行，直接改配置文件可能被它覆盖。'
                           '请先正常停止服务端再修改。'}
    plan = plan_update(server_root, changes)
    if not plan['ok']:
        detail = '；'.join(f'{key}：{reason}' for key, reason in plan['problems'])
        return {'ok': False, 'message': f'没有写入，取值不合法 —— {detail}',
                'backup': None, 'path': plan['path']}

    path = plan['path']
    backup = None
    if os.path.isfile(path):
        candidate = path + BACKUP_SUFFIX
        if not os.path.exists(candidate):
            try:
                shutil.copy2(path, candidate)
                backup = candidate
            except OSError as error:
                return {'ok': False, 'backup': None, 'path': path,
                        'message': f'备份失败，已中止修改：{error}'}
        else:
            backup = candidate      # 已存在:保留最早的原始备份,不覆盖

    folder = os.path.dirname(os.path.abspath(path)) or '.'
    os.makedirs(folder, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.amcl-props-', dir=folder)
    try:
        with os.fdopen(handle, 'w', encoding=plan['encoding'],
                       errors='replace', newline='\n') as stream:
            stream.write(plan['text'])
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as error:
        return {'ok': False, 'backup': backup, 'path': path,
                'message': f'写入失败：{error}'}
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    note = '' if plan['encoding'] == ENCODING else f'（已按 {plan["encoding"]} 写入，含非拉丁字符）'
    return {'ok': True, 'path': path, 'backup': backup,
            'message': f'已保存 {len(changes)} 项改动{note}。'
                       + (f' 原始文件备份在 {os.path.basename(backup)}。' if backup else ''),
            'encoding': plan['encoding']}
