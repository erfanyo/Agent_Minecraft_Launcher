"""Shared GUI/AI maintenance service. World and Mod data are never reset."""
import json
import os
import shutil
import tempfile
import threading
import uuid
from safe_paths import safe_child, safe_component
from instance_metadata import atomic_json, read_metadata

_lock = threading.Lock()


def assert_not_maintaining():
    if _lock.locked():
        raise RuntimeError('实例维护尚未完成，请完成后再启动游戏。')


def maintenance_preview(name, args):
    descriptions = {
        'repair_instance_core': '重新安装相同游戏和加载器版本。替换前备份核心；保留存档、Mod 和配置。结果中提供备份路径，可手动恢复。',
        'complete_instance_files': '校验并补全客户端、依赖库和资源。不重新下载第三方 Mod，也不删除存档。',
        'reset_instance': '备份并移走 launch_options.json、options.txt、optionsof.txt，恢复默认启动、画面和按键设置。存档、Mod 和 Mod 配置保留；结果中提供恢复路径。',
    }
    return f"实例：{args.get('instance', '未指定')}\n请先退出游戏。\n" + descriptions[name]


def target(root, instance):
    safe_component(instance)
    folder = safe_child(os.path.join(root, 'versions'), instance)
    if not os.path.isdir(folder):
        raise ValueError('实例不存在')
    return folder


def assert_stopped(folder):
    # Covers other launchers too, when their Java command identifies this directory.
    import psutil
    folder = os.path.normcase(os.path.realpath(folder))
    for proc in psutil.process_iter(['name', 'cmdline']):
        if 'java' not in (proc.info['name'] or '').lower():
            continue
        command = os.path.normcase(' '.join(proc.info['cmdline'] or []))
        if folder in command:
            raise RuntimeError('这个实例正在运行，请先退出游戏再维护。')


def imported(folder):
    data = read_metadata(folder)
    return bool(data.get('source_type') == 'modpack' or any(os.path.exists(os.path.join(folder, f))
                for f in ('modrinth.index.json', 'manifest.json', 'mmc-pack.json')))


def current_core(root, instance):
    from launcher import resolve_inherited_json
    from instances import scan_instances
    detail = resolve_inherited_json(instance, root)
    info = next((row for row in scan_instances(root) if row['id'] == instance), {})
    loader = info.get('loader') or ''
    mc = info.get('base') or detail.get('clientVersion') or instance
    metadata = read_metadata(os.path.join(root, 'versions', instance))
    loader_version = str(metadata.get('loader_version') or '')
    for lib in detail.get('libraries', []):
        parts = str(lib.get('name', '')).split(':')
        if len(parts) < 3:
            continue
        if (loader == 'fabric' and parts[:2] == ['net.fabricmc', 'fabric-loader'] or
            loader == 'forge' and parts[:2] == ['net.minecraftforge', 'forge'] or
            loader == 'neoforge' and parts[0] == 'net.neoforged' and parts[1] in ('neoforge', 'forge')):
            loader_version = parts[2]
            if loader_version.startswith(mc + '-'):
                loader_version = loader_version[len(mc)+1:]
    # Flattened/imported NeoForge instances may carry the loader version only in
    # their launch arguments, without a net.neoforged:neoforge library coordinate.
    # These are the same local fields ModLauncher consumes during a real launch.
    game_args = (detail.get('arguments') or {}).get('game') or []
    flags = {}
    for index, value in enumerate(game_args[:-1]):
        if isinstance(value, str) and value.startswith('--fml.') and isinstance(game_args[index + 1], str):
            flags[value] = game_args[index + 1]
    if not loader_version:
        loader_version = flags.get({'neoforge': '--fml.neoForgeVersion',
                                    'forge': '--fml.forgeVersion'}.get(loader, ''), '')
    if (not info.get('base') and flags.get('--fml.mcVersion')):
        mc = flags['--fml.mcVersion']
    if loader not in ('', 'forge', 'fabric', 'neoforge') or loader and not loader_version:
        raise ValueError('未能确定原加载器版本，请从“修改”页指定版本后重建。')
    return mc, loader, loader_version


def perform(root, instance, action, version='', loader='', loader_version='', status=None):
    status = status or (lambda message: None)
    folder = target(root, instance)
    if action not in ('repair_core', 'complete_files', 'reset', 'modify'):
        raise ValueError('未知维护操作')
    if not _lock.acquire(blocking=False):
        raise RuntimeError('已有实例维护任务正在执行，请稍等。')
    try:
        assert_stopped(folder)
        if action == 'complete_files':
            from launcher import resolve_inherited_json
            from game_files import install_version_files
            from downloader import download_with_mirror
            detail = resolve_inherited_json(instance, root)
            client = detail.get('downloads', {}).get('client')
            if client:
                download_with_mirror(client['url'], os.path.join(folder, instance+'.jar'), sha1=client.get('sha1'))
            _, failures = install_version_files(detail, root, status_callback=status)
            if failures:
                raise RuntimeError(f'{len(failures)} 个文件仍未补齐：{failures[0][0]}')
            return '游戏核心依赖与资源已校验补全；不包含第三方 Mod 的重新下载。'
        backup = safe_child(os.path.join(root, 'versions', '_maintenance'), instance+'-'+uuid.uuid4().hex)
        os.makedirs(backup)
        if action == 'reset':
            from settings import load_settings
            if not load_settings().get('version_isolation', True):
                raise ValueError('当前关闭了版本隔离，游戏设置由多个实例共享；请先开启隔离再重置。')
            names = ('launch_options.json', 'options.txt', 'optionsof.txt')
            changed = []
            try:
                for name in names:
                    path = safe_child(folder, name)
                    if os.path.isfile(path):
                        shutil.move(path, os.path.join(backup, name))
                        changed.append(name)
            except Exception:
                for name in changed:
                    shutil.move(os.path.join(backup, name), os.path.join(folder, name))
                raise
            return '已重置启动选项和游戏画面/按键设置。存档、Mod、Mod 配置保留。恢复时把备份文件复制回实例目录。备份：'+backup
        if action == 'repair_core':
            version, loader, loader_version = current_core(root, instance)
        from diagnostic_tools import check_constraint
        check_constraint(instance, version, loader)
        safe_component(version)
        if loader not in ('', 'forge', 'fabric', 'neoforge'):
            raise ValueError('不支持的加载器')
        if loader_version:
            safe_component(loader_version)
        # Install fully away from the existing instance, then publish only launch files.
        from instance_install_service import InstanceInstallService
        from launcher import resolve_inherited_json
        with tempfile.TemporaryDirectory(prefix='amcl-core-') as stage:
            service = InstanceInstallService(lambda: stage, lambda: True)
            generated = service.create_instance(version, loader or None, loader or None, False, False,
                                                loader_version=loader_version or None, status_cb=status)
            # Installer currently returns the id; accept structured results only explicitly.
            if not isinstance(generated, str):
                raise RuntimeError('安装器未返回有效的实例 ID')
            detail = resolve_inherited_json(generated, stage)
            jar = os.path.join(stage, 'versions', generated, generated+'.jar')
            if not os.path.isfile(jar):
                raise RuntimeError('安装后未找到客户端核心，原实例未修改。')
            detail['id'] = instance
            detail.pop('inheritsFrom', None)
            def relocate(value):
                if isinstance(value, str):
                    return value.replace(stage, root).replace(stage.replace('\\', '/'), root.replace('\\', '/'))
                if isinstance(value, list):
                    return [relocate(v) for v in value]
                if isinstance(value, dict):
                    return {k: relocate(v) for k, v in value.items()}
                return value
            detail = relocate(detail)
            for directory in ('libraries', 'assets'):
                source = os.path.join(stage, directory)
                if os.path.isdir(source):
                    shutil.copytree(source, os.path.join(root, directory), dirs_exist_ok=True)
            assert_stopped(folder)
            names = (instance+'.json', instance+'.jar', 'amcl_instance.json')
            existed = []
            for name in names:
                path = safe_child(folder, name)
                if os.path.isfile(path):
                    shutil.copy2(path, os.path.join(backup, name))
                    existed.append(name)
            try:
                shutil.copy2(jar, os.path.join(folder, instance+'.jar'))
                atomic_json(os.path.join(folder, instance+'.json'), detail)
                metadata = read_metadata(folder)
                metadata.update(minecraft_version=version, loader=loader or None)
                atomic_json(os.path.join(folder, 'amcl_instance.json'), metadata)
            except Exception:
                for name in names:
                    path = os.path.join(folder, name)
                    if name in existed:
                        shutil.copy2(os.path.join(backup, name), path)
                    elif os.path.isfile(path):
                        os.remove(path)
                raise
        return '核心已更新，存档与 Mod 保留。若版本不同，请先检查 Mod 兼容性并备份存档再启动。原核心备份：'+backup
    finally:
        _lock.release()
