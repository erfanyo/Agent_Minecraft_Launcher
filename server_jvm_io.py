# -*- coding: utf-8 -*-
"""``user_jvm_args.txt`` 的落盘层:读取、备份、原子写入、运行中拒绝写。

与 :mod:`server_jvm` 的分工保持一致:那边是纯解析/合并/校验,这边碰磁盘。
安全规则沿用 :mod:`server_properties_io` 的先例(那套已经过验证):

1. 服务端运行中拒绝写(运行中的进程不会重读该文件,改了也不生效,还容易被覆盖);
2. 首次修改备份为 ``user_jvm_args.txt.bak``,且**不覆盖已有备份**;
3. 原子写(临时文件 + ``os.replace``);
4. 写入前统一校验,校验不过就不落盘。
"""
from __future__ import annotations

import os
import shutil
import tempfile

import server_jvm

ENCODING = 'utf-8'
BACKUP_SUFFIX = '.bak'
FILENAME = 'user_jvm_args.txt'


def jvm_args_path(server_root: str) -> str:
    return os.path.join(str(server_root), FILENAME)


def read_text(path: str) -> str:
    if not os.path.isfile(path):
        return ''
    try:
        with open(path, encoding=ENCODING, errors='replace') as stream:
            return stream.read()
    except OSError:
        return ''


def read_records(server_root: str) -> list:
    return server_jvm.parse_records(read_text(jvm_args_path(server_root)))


def server_running(server_root: str) -> bool:
    try:
        from server_host_client import managed_status
        state = managed_status(server_root, probe=False) or {}
    except Exception:
        return False
    return bool(state.get('running'))


def current_settings(server_root: str) -> dict:
    """读当前设置,供 UI 回显。

    返回 ``{'max','min','extras','unsupported','text'}``;``unsupported`` 是文件里
    已存在但启动器不接受的参数(只做提示,不自动删——那是用户的文件)。
    """
    records = read_records(server_root)
    memory = server_jvm.read_memory(records)
    args = server_jvm.all_args(records)
    managed = set(server_jvm.memory_flags(parse_gb(memory['max']),
                                          parse_gb(memory['min'])))
    extras = [arg for arg in args
              if arg not in managed and server_jvm.is_supported(arg)]
    return {'max': memory['max'], 'min': memory['min'], 'extras': extras,
            'unsupported': server_jvm.unsupported_args(args),
            'text': read_text(jvm_args_path(server_root))}


def parse_gb(value):
    """``'4G'`` → ``4``;无法解析返回 None。"""
    if not value:
        return None
    try:
        return int(str(value).rstrip('GgMmKk'))
    except (TypeError, ValueError):
        return None


def plan_update(server_root: str, *, max_gb=None, min_gb=None, extras=None,
                replace_extras: bool = False):
    """算出改动结果但不落盘 → ``{'ok','records','text','problems'}``。

    校验不通过时**直接返回**,不再尝试合并——否则非数字输入会在 int() 处抛异常,
    把「填错了」变成「启动器崩了」。
    """
    ok, problems = server_jvm.validate(max_gb=max_gb, min_gb=min_gb,
                                       extras=extras)
    if not ok:
        return {'ok': False, 'records': [], 'text': '', 'problems': list(problems)}
    records = server_jvm.merge(read_records(server_root), max_gb=max_gb,
                               min_gb=min_gb, extras=extras,
                               replace_extras=replace_extras)
    text = server_jvm.serialize_records(records)
    # 合并结果也必须过启动侧那一关(例如文件里原本就有不支持的参数)
    leftover = server_jvm.unsupported_args(server_jvm.all_args(records))
    if leftover:
        problems = list(problems) + [
            '文件里仍有启动器不接受的参数,保存后服务端将无法启动:'
            + '、'.join(leftover)]
    return {'ok': not problems, 'records': records, 'text': text,
            'problems': problems}


def apply_update(server_root: str, *, max_gb=None, min_gb=None, extras=None,
                 replace_extras: bool = False, allow_running: bool = False):
    """校验 + 备份 + 原子写入 → ``{'ok','message','backup','path'}``。"""
    if server_running(server_root) and not allow_running:
        return {'ok': False, 'backup': None, 'path': None,
                'message': '服务端正在运行。运行中的进程不会重读这个文件,'
                           '请先停止服务端再修改运行配置。'}
    plan = plan_update(server_root, max_gb=max_gb, min_gb=min_gb,
                       extras=extras, replace_extras=replace_extras)
    if not plan['ok']:
        return {'ok': False, 'message': '没有写入 —— ' + '；'.join(plan['problems']),
                'backup': None, 'path': jvm_args_path(server_root)}

    path = jvm_args_path(server_root)
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
            backup = candidate

    folder = os.path.dirname(os.path.abspath(path)) or '.'
    os.makedirs(folder, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.amcl-jvm-', dir=folder)
    try:
        with os.fdopen(handle, 'w', encoding=ENCODING, newline='\n') as stream:
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

    return {'ok': True, 'path': path, 'backup': backup,
            'message': '已保存运行配置。'
                       + (f' 原始文件备份在 {os.path.basename(backup)}。'
                          if backup else '')}
