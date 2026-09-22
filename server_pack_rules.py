"""Deterministic rules for turning a client instance into a server candidate.

This module never mutates the source instance and never uses filenames alone as
proof that a Mod is client-only.  Unknown Mods stay in the candidate and are
called out for human review.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re

from mod_deps import read_mod_metadata
from task_context import checkpoint


CONTENT_DIRS = ('mods', 'config', 'defaultconfigs', 'kubejs', 'scripts',
                'datapacks', 'serverconfig', 'openloader')
SECRET_PATTERN = re.compile(
    r'(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|'
    r'webhook|rcon[_-]?password|client[_-]?secret)\s*[=:]')
TEXT_SUFFIXES = {'.json', '.toml', '.yaml', '.yml', '.properties', '.cfg', '.conf', '.txt'}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            checkpoint()
            digest.update(chunk)
    return digest.hexdigest()


def _linked(path: Path) -> bool:
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def _secret_hint(path: Path) -> bool:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return False
        return bool(SECRET_PATTERN.search(path.read_text(encoding='utf-8', errors='replace')))
    except OSError:
        return False


def inspect_client_instance(instance_dir, *, selected_world=None,
                            max_files=100_000, max_bytes=16 * 1024**3):
    """Create a hash-bound copy plan for a client instance.

    A selected save is mapped to ``world/``. Disabled Mods, explicit client-only
    Mods and personal/runtime data are omitted. Unknown Mod side is deliberately
    retained.
    """
    supplied_root = Path(instance_dir)
    if _linked(supplied_root):
        raise ValueError('客户端实例目录必须是普通文件夹，不能是链接或目录联接。')
    root = supplied_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('客户端实例目录必须是普通文件夹，不能是链接或目录联接。')
    entries = []
    mods = []
    warnings = []
    secret_paths = []
    count = total = 0

    def add_tree(source: Path, target_prefix: str):
        nonlocal count, total
        if not source.exists():
            return
        if not source.is_dir() or _linked(source):
            raise ValueError(f'来源不是安全目录：{source.name}')
        for disk in sorted(source.rglob('*')):
            checkpoint()
            if _linked(disk):
                raise ValueError(f'来源包含链接或目录联接：{disk.relative_to(root)}')
            if not disk.is_file():
                continue
            relative_source = disk.relative_to(root).as_posix()
            relative_inside = disk.relative_to(source).as_posix()
            target = f'{target_prefix}/{relative_inside}'
            if target.casefold().startswith('kubejs/client_scripts/'):
                continue
            size = disk.stat().st_size
            count += 1
            total += size
            if count > max_files:
                raise ValueError('实例文件数量超过 100000，已停止转换。')
            if total > max_bytes:
                raise ValueError('候选服务端内容超过 16 GiB，已停止转换。')
            digest = sha256_file(disk)
            if _secret_hint(disk):
                secret_paths.append(relative_source)
            entries.append({'source': relative_source, 'target': target,
                            'bytes': size, 'sha256': digest})

    mods_dir = root / 'mods'
    if mods_dir.is_dir():
        for disk in sorted(mods_dir.iterdir()):
            checkpoint()
            if _linked(disk):
                raise ValueError(f'Mods 目录包含链接：{disk.name}')
            if not disk.is_file() or not disk.name.lower().endswith(('.jar', '.jar.disabled')):
                continue
            metadata = read_mod_metadata(str(disk)) or {}
            side = metadata.get('environment', 'unknown')
            record = {'file': disk.name, 'modId': metadata.get('id') or '',
                      'name': metadata.get('name') or disk.name,
                      'environment': side}
            if disk.name.lower().endswith('.disabled'):
                record.update(action='excluded', reason='实例中已禁用')
                mods.append(record)
                continue
            if side == 'client':
                record.update(action='excluded', reason='Mod 内部元数据明确声明仅客户端')
                mods.append(record)
                continue
            record.update(action='included', reason=(
                'Mod 内部元数据声明可在服务端加载' if side in ('server', 'both')
                else '适用端无法可靠判断，按保守策略保留并要求人工审核'))
            mods.append(record)
            size = disk.stat().st_size
            count += 1
            total += size
            if count > max_files or total > max_bytes:
                raise ValueError('候选服务端内容超过安全限制。')
            entries.append({'source': disk.relative_to(root).as_posix(),
                            'target': f'mods/{disk.name}', 'bytes': size,
                            'sha256': sha256_file(disk)})

    for directory in CONTENT_DIRS[1:]:
        add_tree(root / directory, directory)

    if selected_world:
        name = str(selected_world)
        if not name or name in ('.', '..') or '/' in name or '\\' in name:
            raise ValueError('存档名称无效。')
        world = root / 'saves' / name
        if not world.is_dir():
            raise ValueError('选择的存档不存在。')
        add_tree(world, 'world')
        warnings.append('已选择存档；其中可能包含玩家 UUID、聊天或其他个人游玩数据，请在分享前复核。')

    unknown = sum(1 for item in mods
                  if item['action'] == 'included' and item['environment'] == 'unknown')
    if unknown:
        warnings.append(f'{unknown} 个 Mod 无法可靠判断适用端，已保留，首次启动后需根据日志复核。')
    if secret_paths:
        warnings.append(f'{len(secret_paths)} 个配置文件疑似包含密钥或密码字段，导出前请人工复核。')
    return {'sourceRoot': str(root), 'files': entries, 'mods': mods,
            'selectedWorld': selected_world, 'bytes': total, 'fileCount': count,
            'secretPaths': secret_paths, 'warnings': warnings}
