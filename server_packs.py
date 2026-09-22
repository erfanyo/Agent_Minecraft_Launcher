"""GUI-independent server pack import. No scripts or manifest commands are executed."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import zipfile

from archive_inspection import inspect_archive, normalize_member
from safe_paths import safe_child


_IMPORT_LOCK = threading.Lock()


def _server_record(folder):
    metadata = folder / '.amcl-server.json'
    if (not metadata.is_file() or metadata.is_symlink()
            or metadata.stat().st_size > 32 * 1024 * 1024):
        return None
    data = json.loads(metadata.read_text(encoding='utf-8'))
    report = data.get('report', {})
    if not isinstance(report, dict):
        return None
    server_root = report.get('serverRoot')
    launch_root = safe_child(folder, server_root) if server_root else str(folder)
    build_report = folder / 'amcl-build-report.json'
    return {'id': folder.name, 'name': str(data.get('name', folder.name)),
            'path': launch_root, 'packagePath': str(folder), 'report': report,
            'launchJar': data.get('launchJar'),
            'candidate': build_report.is_file() and not build_report.is_symlink(),
            '_registeredAt': metadata.stat().st_mtime_ns}


def _existing_import(root, sha256):
    """Return the earliest completed import of an identical archive, if any."""
    matches = []
    for folder in root.iterdir():
        if (folder.name.startswith('.') or not folder.is_dir() or folder.is_symlink()
                or (folder / '.amcl-importing').exists()):
            continue
        try:
            record = _server_record(folder)
            if record and record['report'].get('sha256') == sha256:
                matches.append(record)
        except (OSError, ValueError, TypeError):
            continue
    if not matches:
        return None
    return min(matches, key=lambda item: (item['_registeredAt'], item['id']))


def list_servers(game_dir):
    root = Path(game_dir) / 'servers'
    records = []
    if root.is_dir():
        for folder in sorted(root.iterdir()):
            if (folder.name.startswith('.') or not folder.is_dir() or folder.is_symlink()
                    or (folder / '.amcl-importing').exists()):
                continue
            try:
                record = _server_record(folder)
                if record:
                    records.append(record)
            except (OSError, ValueError, TypeError):
                continue
    # Older builds could register the exact same archive more than once. Keep
    # the earliest entry visible without deleting either directory.
    result = []
    by_hash = {}
    for record in sorted(records, key=lambda item: (item['_registeredAt'], item['id'])):
        sha256 = record['report'].get('sha256')
        if sha256 and sha256 in by_hash:
            by_hash[sha256].setdefault('duplicatePackagePaths', []).append(
                record['packagePath'])
            continue
        record.pop('_registeredAt', None)
        result.append(record)
        if sha256:
            by_hash[sha256] = record
    return result


def read_candidate_report(server):
    """Read the bounded local builder report; never follow a package link."""
    path = Path(server['packagePath'], 'amcl-build-report.json')
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schemaVersion') != 1:
        return None
    return data


def set_server_launch_jar(server, jar_path):
    """Persist an optional, user-selected JAR relative to the actual launch root."""
    launch_root = Path(server['path']).resolve(strict=True)
    if jar_path:
        jar = Path(jar_path).resolve(strict=True)
        try:
            relative = jar.relative_to(launch_root).as_posix()
        except ValueError as exc:
            raise ValueError('启动 JAR 必须位于当前服务端目录内') from exc
        if jar.suffix.lower() != '.jar' or jar.is_symlink():
            raise ValueError('请选择当前服务端目录内的普通 JAR 文件')
    else:
        relative = None
    metadata = Path(server['packagePath'], '.amcl-server.json')
    data = json.loads(metadata.read_text(encoding='utf-8'))
    if relative:
        data['launchJar'] = relative
    else:
        data.pop('launchJar', None)
    pending = metadata.with_name('.amcl-server.pending')
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(pending, metadata)
    server['launchJar'] = relative
    return relative


def read_server_ui_state(server, key, default=None):
    """读某个服务端的界面状态(如「高级选项」是否展开)。

    与客户端一致地放在服务端自身的 ``.amcl-server.json`` 里,让每个服务端各自
    记忆展开状态,而不是全局一份。
    """
    try:
        path = Path(server['packagePath'], '.amcl-server.json')
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, KeyError, TypeError):
        return default
    state = data.get('ui_state')
    if not isinstance(state, dict):
        return default
    return state.get(key, default)


def write_server_ui_state(server, key, value):
    """写服务端界面状态;失败返回 False(点一下菜单不该让界面崩)。"""
    try:
        path = Path(server['packagePath'], '.amcl-server.json')
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return False
        state = data.get('ui_state')
        if not isinstance(state, dict):
            state = {}
        state[str(key)] = value
        data['ui_state'] = state
        pending = path.with_name('.amcl-server.pending')
        pending.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding='utf-8')
        os.replace(pending, path)
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def import_server_pack(path, game_dir, expected_sha256, status_callback=None,
                       progress_callback=None, display_name=None):
    """Import in place with an incomplete marker; never rename the whole directory."""
    status = status_callback or (lambda _: None)
    status('正在复核压缩包，确认它与预览时一致…')
    report = inspect_archive(path, status_callback=status_callback, progress_callback=progress_callback)
    if report['sha256'] != expected_sha256:
        raise ValueError('压缩包在预览后发生变化，请重新扫描。')
    root = Path(game_dir) / 'servers'
    root.mkdir(parents=True, exist_ok=True)
    with _IMPORT_LOCK:
        existing = _existing_import(root, report['sha256'])
        if existing:
            status(f"这个服务端包已经导入过了，已复用“{existing['name']}”。")
            if progress_callback:
                progress_callback(report['expandedBytes'], report['expandedBytes'])
            return existing['packagePath']
        return _extract_server_pack(path, root, report, status, progress_callback,
                                    display_name)


def _extract_server_pack(path, root, report, status, progress_callback, display_name):
    destination = Path(tempfile.mkdtemp(prefix='server-', dir=root))
    marker = destination / '.amcl-importing'
    marker.write_text('Import incomplete; do not launch.\n', encoding='utf-8')
    try:
        staging = destination
        status('正在解压并核对文件；完成前不会加入服务端列表…')
        prefix = (report['packageRoot'] + '/') if report['packageRoot'] else ''
        extracted = 0
        seen = set()
        import time
        last_progress = 0.0
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = normalize_member(info.filename)
                if name not in report['files'] or name in seen:
                    raise ValueError('压缩包文件列表在扫描后发生变化。')
                seen.add(name)
                relative = name[len(prefix):]
                if relative.casefold() in ('.amcl-server.json', '.amcl-importing', '.amcl-server.pending'):
                    raise ValueError('压缩包使用了启动器保留的文件名。')
                target = Path(safe_child(staging, relative))
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                count = 0
                with archive.open(info) as src, target.open('xb') as dst:
                    while chunk := src.read(1024 * 1024):
                        count += len(chunk)
                        extracted += len(chunk)
                        if count > info.file_size:
                            raise ValueError('解压大小与扫描结果不一致。')
                        if extracted > report['expandedBytes']:
                            raise ValueError('解压总大小与扫描结果不一致。')
                        digest.update(chunk)
                        dst.write(chunk)
                        if progress_callback and time.monotonic() - last_progress >= 0.2:
                            progress_callback(extracted, report['expandedBytes'])
                            last_progress = time.monotonic()
                if digest.hexdigest() != report['files'].get(name):
                    raise ValueError('解压内容与扫描结果不一致。')
        if seen != set(report['files']):
            raise ValueError('压缩包文件列表在扫描后发生变化。')
        status('文件校验完成，正在登记服务端…')
        metadata = {'name': str(display_name or Path(path).stem), 'report': report}
        pending = destination / '.amcl-server.pending'
        pending.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(pending, destination / '.amcl-server.json')
        if progress_callback:
            progress_callback(report['expandedBytes'], report['expandedBytes'])
        marker.unlink()
    except Exception as exc:
        raise RuntimeError(f'服务端导入失败：{exc}\n未完成的文件保留在：{destination}\n'
                           '不会加入可启动列表；原压缩包未修改。') from exc
    return str(destination)
