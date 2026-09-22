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


# Copy policy is "keep unless proven disposable".  A whitelist cannot know about
# hand-written integration folders (``hotai``, ``tlm_custom_pack``,
# ``patchouli_books`` ...), and silently dropping one of those produces a server
# that boots but fails at runtime.  We therefore copy every top-level entry and
# only skip the paths listed below, which are provably client-local or personal.
CONTENT_DIRS = ('mods', 'config', 'defaultconfigs', 'kubejs', 'scripts',
                'datapacks', 'serverconfig', 'openloader')

# Never copied: launcher/runtime state and per-player personal data.
DENY_TOP_LEVEL = {
    'saves', 'screenshots', 'logs', 'crash-reports', 'natives', 'shaderpacks',
    'resourcepacks', 'local', 'usercache.json', 'usernamecache.json',
    'options.txt', 'optionsof.txt', 'servers.dat', 'servers.dat_old',
    'realms_persistence.json', 'servers.dat_old', 'patchouli_data.json',
    'xaero', 'xaerominimap', 'xaeroworldmap', 'journeymap', 'sodium-options.json',
    'iris.properties', 'PCL', 'BakaXL', 'HMCL', 'modrinth.index.json',
    '.mixin.out', 'modernfix', 'fancymenu_data', 'kubejs/client_scripts',
    # Launcher-written instance descriptors (never server content).
    'amcl_instance.json', 'amcl_memory.json', 'rhino.local.properties',
}
# The launcher drops a name-versioned wrapper next to the instance root, e.g.
# ``地下酒吧.jar`` / ``地下酒吧.json``.  Those mirror the instance name, so they
# are detected by stem rather than by a fixed name.
LAUNCHER_WRAPPER_SUFFIXES = ('.jar', '.json')
# Runtime/launcher bookkeeping that must never be carried into a server.
# NOTE: ``.badiff`` is deliberately absent — those are Mod patch payloads (e.g.
# the ``hotai/`` folder) that a server needs, not disposable launcher state.
DENY_SUFFIXES = ('.log', '.log.gz', '.tmp', '.part')
DENY_NAMES = {'session.lock', '.DS_Store', 'Thumbs.db', 'desktop.ini', 'eula.txt'}

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


def _skip_disk(disk: Path, root: Path) -> bool:
    """True when a file is launcher/runtime noise rather than pack content."""
    if disk.name in DENY_NAMES:
        return True
    lowered = disk.name.casefold()
    if lowered.endswith(DENY_SUFFIXES):
        return True
    return False


def inspect_client_instance(instance_dir, *, selected_world=None,
                            max_files=100_000, max_bytes=16 * 1024**3):
    """Create a hash-bound copy plan for a client instance.

    A selected save is mapped to ``world/``. Disabled Mods, explicit client-only
    Mods and personal/runtime data are omitted. Unknown Mod side is deliberately
    retained, and any top-level folder that is not on the deny list is copied
    wholesale so hand-written integration folders survive conversion.
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
    skipped = []
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
            if _skip_disk(disk, root):
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

    # Keep-by-default sweep: anything else at the top level is copied unless it
    # is denied above.  This is what lets integrator folders such as hotai/ or
    # tlm_custom_pack/ reach the server instead of being silently filtered out.
    known = set(CONTENT_DIRS) | DENY_TOP_LEVEL
    for child in sorted(root.iterdir()):
        checkpoint()
        if child.name in known or child.name.startswith('.'):
            continue
        if _linked(child):
            raise ValueError(f'来源包含链接或目录联接：{child.name}')
        if child.is_dir():
            add_tree(child, child.name)
        elif child.is_file():
            if _skip_disk(child, root):
                continue
            # Skip the launcher's own name-versioned wrapper (instance-name.jar
            # and its .json sibling); a real pack never ships these at the root.
            if (child.suffix.casefold() in LAUNCHER_WRAPPER_SUFFIXES
                    and child.stem.casefold() == root.name.casefold()):
                continue
            relative_source = child.relative_to(root).as_posix()
            size = child.stat().st_size
            count += 1
            total += size
            if count > max_files or total > max_bytes:
                raise ValueError('候选服务端内容超过安全限制。')
            digest = sha256_file(child)
            if _secret_hint(child):
                secret_paths.append(relative_source)
            entries.append({'source': relative_source, 'target': relative_source,
                            'bytes': size, 'sha256': digest})

    for name in sorted(DENY_TOP_LEVEL):
        if (root / name).exists():
            skipped.append(name)
    if skipped:
        warnings.append(
            '已跳过 %d 项启动器/个人数据目录（%s）；如其中包含整合包必需内容，请手动补入。'
            % (len(skipped), '、'.join(skipped[:8]) + ('…' if len(skipped) > 8 else '')))

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
            'secretPaths': secret_paths, 'warnings': warnings,
            'modManifest': build_mod_manifest(mods)}


def build_mod_manifest(mods):
    """Record the shipped Mod naming exactly as it exists on disk.

    Filenames are deliberately *not* transliterated.  Chinese display prefixes
    such as ``[机械动力]`` are meaningful to the pack author, and rewriting them
    would both confuse existing docs and risk encoding problems when the pack is
    unpacked on a non-UTF-8 filesystem.  Instead we pin the original name, its
    ASCII-safe form and the Mod id here, so later tooling (including a headless /
    MCP front end) can map a Mod back to a stable identity without depending on
    the filename at all.
    """
    manifest = []
    for item in sorted(mods, key=lambda entry: entry['file'].casefold()):
        if item.get('action') != 'included':
            continue
        original = item['file']
        manifest.append({
            'file': original,
            'fileAscii': original.encode('ascii', 'replace').decode('ascii'),
            'modId': item.get('modId') or '',
            'name': item.get('name') or original,
            'environment': item.get('environment') or 'unknown',
            'renamed': False,
        })
    return manifest

