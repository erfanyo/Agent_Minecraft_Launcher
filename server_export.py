"""Conservative runtime + Mod export, not a full configuration/world backup."""
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile
from server_launch import build_launch_plan, local_file
from task_context import checkpoint


def server_content_allowed(relative, directory=False):
    from archive_inspection import normalize_member
    try:
        relative = normalize_member(relative)
    except ValueError:
        return False
    parts = relative.lower().split('/')
    if parts[0] not in {'mods', 'config', 'defaultconfigs', 'kubejs', 'scripts', 'datapacks'}:
        return False
    if any(p.startswith('.') or p in {'logs', 'backups', 'playerdata', 'whitelist.json',
               'ops.json', 'usercache.json', 'server.properties', 'accounts.json', 'credentials.json'} for p in parts):
        return False
    if directory:
        return True
    if parts[0] == 'mods':
        return relative.lower().endswith('.jar')
    return not relative.lower().endswith(('.exe', '.dll', '.bat', '.cmd', '.ps1', '.sh', '.key', '.pem'))


def export_server_template(root, destination, files, mc, loader, loader_version):
    """Export explicitly selected content, never copy client launch/runtime files."""
    from archive_inspection import required_java
    import re
    if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', mc or ''):
        raise ValueError('无法确认游戏版本，请先检查实例版本信息。')
    if loader not in ('forge', 'neoforge', 'fabric', 'quilt', '', 'vanilla'):
        raise ValueError('无法识别加载器。')
    if loader_version and not re.fullmatch(r'[\w.+\-]+', loader_version):
        raise ValueError('加载器版本格式无效。')
    destination = Path(destination)
    if destination.exists():
        raise ValueError('目标文件已存在，请选择新文件名。')
    selected = []
    seen = set()
    for disk, relative in files:
        relative = relative.replace('\\', '/')
        if not server_content_allowed(relative):
            raise ValueError(f'服务端导出不允许包含：{relative}')
        verified = local_file(root, relative)
        if verified.resolve() != Path(disk).resolve() or relative.casefold() in seen:
            raise ValueError('文件来源不一致或路径重复。')
        seen.add(relative.casefold())
        selected.append((verified, relative))
    if not selected:
        raise ValueError('没有可导出的服务端内容。')
    manifest = {'schemaVersion': 1, 'name': 'AMCL 服务端内容包',
                'minecraftVersion': mc, 'loader': loader or 'vanilla',
                'loaderVersion': loader_version, 'requiredJava': required_java(mc),
                'serverRoot': 'server', 'contentProfile': 'server-content',
                'requiresRuntimeInstall': True, 'files': []}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.amcl-export-', dir=destination.parent) as temp:
        staged = Path(temp, 'pack.zip')
        with zipfile.ZipFile(staged, 'w', zipfile.ZIP_DEFLATED) as archive:
            for disk, relative in selected:
                digest = hashlib.sha256()
                size = 0
                with disk.open('rb') as src, archive.open('server/' + relative, 'w', force_zip64=True) as dst:
                    while chunk := src.read(1024 * 1024):
                        checkpoint()
                        digest.update(chunk)
                        size += len(chunk)
                        dst.write(chunk)
                manifest['files'].append({'path': 'server/' + relative, 'bytes': size, 'sha256': digest.hexdigest()})
            archive.writestr('amcl-server-pack.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        created = False
        try:
            with staged.open('rb') as src, destination.open('xb') as dst:
                created = True
                import shutil
                shutil.copyfileobj(src, dst)
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
    return str(destination)


def export_runtime_pack(root, destination):
    root = Path(root).resolve(strict=True)
    destination = Path(destination).absolute()
    if destination.exists():
        raise ValueError('目标文件已存在，请选择新文件名。')
    plan = build_launch_plan(root)
    if plan['loader'] not in ('forge', 'neoforge'):
        raise ValueError('运行包导出暂支持已验证的 Forge / NeoForge 服务端。')
    entry_parent = (root / plan['entry']).parent
    for platform, filename in [('windows', 'win_args.txt'), ('linux', 'unix_args.txt')]:
        if (entry_parent / filename).exists():
            build_launch_plan(root, platform)
    selected = []
    for directory in ('libraries', 'mods'):
        base = root / directory
        if not base.exists():
            continue
        if base.is_symlink() or getattr(base, 'is_junction', lambda: False)():
            raise ValueError('导出目录不能是链接或目录联接。')
        for path in base.rglob('*'):
            checkpoint()
            if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                raise ValueError('导出目录包含链接，已停止。')
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if path.suffix.lower() == '.jar' or (directory == 'libraries' and path.name in ('win_args.txt', 'unix_args.txt')):
                selected.append((relative, local_file(root, relative)))
    version = plan['entry'].split('/')[-2]
    if plan['loader'] == 'forge':
        version = version.split('-', 1)[1]
    manifest = {'schemaVersion': 1, 'name': 'AMCL 服务端运行包',
                'minecraftVersion': plan['minecraftVersion'], 'loader': plan['loader'],
                'loaderVersion': version, 'requiredJava': plan['requiredJava'],
                'serverRoot': 'server', 'contentProfile': 'runtime-and-mods',
                'omitted': ['config', 'worlds', 'logs', 'credentials', 'server.properties', 'eula.txt', 'client'],
                'files': []}
    # No source paths, arbitrary manifest fields, credentials or startCommand.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.amcl-export-', dir=destination.parent) as tmp:
        staged = Path(tmp, 'pack.zip')
        with zipfile.ZipFile(staged, 'w', zipfile.ZIP_DEFLATED) as archive:
            for relative, path in sorted(selected):
                digest = hashlib.sha256()
                size = 0
                with path.open('rb') as src, archive.open('server/' + relative, 'w', force_zip64=True) as dst:
                    while chunk := src.read(1024 * 1024):
                        checkpoint()
                        digest.update(chunk)
                        size += len(chunk)
                        dst.write(chunk)
                manifest['files'].append({'path': 'server/' + relative, 'bytes': size, 'sha256': digest.hexdigest()})
            archive.writestr('amcl-server-pack.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        # Exclusive creation: do not overwrite an export created in the meantime.
        created = False
        try:
            with staged.open('rb') as src, destination.open('xb') as dst:
                created = True
                import shutil
                shutil.copyfileobj(src, dst)
        except FileExistsError:
            raise ValueError('目标文件已经存在，未覆盖。')
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
    return str(destination)
