"""Stable instance IDs and atomic player-facing metadata, independent of Qt."""
import json
import os
import tempfile
from safe_paths import safe_child, safe_component

def atomic_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.amcl-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def read_metadata(folder):
    try:
        with open(os.path.join(folder, 'amcl_instance.json'), encoding='utf-8') as file:
            value = json.load(file)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}

def rename_display(game_root, instance_id, name):
    from instances import scan_instances
    safe_component(instance_id)
    safe_component(name)
    if name.startswith('_'):
        raise ValueError('名称不能以下划线开头')
    folder = safe_child(os.path.join(game_root, 'versions'), instance_id)
    if not os.path.isfile(os.path.join(folder, instance_id + '.json')):
        raise ValueError('实例文件不完整，请刷新列表后再试')
    for item in scan_instances(game_root):
        if item['id'] != instance_id and name.casefold() in {
                item['id'].casefold(), item['name'].casefold()}:
            raise ValueError('这个名称已经被另一个实例使用了')
    data = read_metadata(folder)
    data['display_name'] = name
    atomic_json(safe_child(folder, 'amcl_instance.json'), data)


def rename_instance(game_root, instance_id, name):
    """Rename installation and direct references, rolling back on write failure."""
    from instances import scan_instances
    safe_component(instance_id)
    safe_component(name)
    if name.startswith('_'):
        raise ValueError('名称不能以下划线开头')
    versions = os.path.join(game_root, 'versions')
    source = safe_child(versions, instance_id)
    target = safe_child(versions, name)
    if name == instance_id:
        return
    if name.casefold() == instance_id.casefold():
        raise ValueError('只调整大小写时，请先改成一个不同名称，再改成目标名称')
    if os.path.lexists(target) or os.path.exists(os.path.join(versions, '_versions', name)):
        raise ValueError('这个名称已有安装目录或基础版本，请换一个名称')
    items = scan_instances(game_root)
    for item in items:
        if item['id'] != instance_id and name.casefold() == item['name'].casefold():
            raise ValueError('这个名称已经被另一个实例使用了')
    current = next((item for item in items if item['id'] == instance_id), None)
    if current is None:
        raise ValueError('实例文件不完整或尚未安装完，请刷新列表后再试')
    # Plan every JSON update before touching the filesystem.
    changes = {}
    def read(path):
        with open(path, encoding='utf-8') as file:
            return json.load(file)
    own_json = safe_child(source, instance_id + '.json')
    own = read(own_json)
    own['id'] = name
    if own.get('jar') == instance_id:
        own['jar'] = name
    changes[own_json] = own
    meta = read_metadata(source)
    meta['display_name'] = name
    meta['minecraft_version'] = current['base']
    changes[safe_child(source, 'amcl_instance.json')] = meta
    for root in (versions, os.path.join(versions, '_versions')):
        if not os.path.isdir(root):
            continue
        for entry in os.listdir(root):
            if entry.startswith('_') or (root == versions and entry == instance_id):
                continue
            path = safe_child(root, entry + '/' + entry + '.json')
            if not os.path.isfile(path):
                continue
            data = read(path)
            if data.get('inheritsFrom') == instance_id or data.get('jar') == instance_id:
                inherited = data.get('inheritsFrom') == instance_id
                if inherited:
                    data['inheritsFrom'] = name
                    child_meta_path = safe_child(root, entry + '/amcl_instance.json')
                    child_meta = read_metadata(os.path.dirname(path))
                    child_meta.setdefault('minecraft_version', current['base'])
                    changes[child_meta_path] = child_meta
                if data.get('jar') == instance_id:
                    data['jar'] = name
                changes[path] = data
    record = os.path.join(versions, '实例记录.json')
    if os.path.isfile(record):
        data = read(record)
        for item in data.get('instances', []):
            if item.get('id') == instance_id:
                item['id'] = name
        changes[record] = data
    backups = {path: open_bytes(path) if os.path.exists(path) else None for path in changes}
    moved_files = []
    written = []
    moved = False
    def relocated(path):
        if os.path.commonpath([source, path]) == source:
            relative = os.path.relpath(path, source)
            if relative == instance_id + '.json':
                relative = name + '.json'
            return os.path.join(target, relative)
        return path
    try:
        os.rename(source, target)
        moved = True
        for suffix in ('.json', '.jar'):
            old = os.path.join(target, instance_id + suffix)
            new = os.path.join(target, name + suffix)
            if os.path.isfile(old):
                if os.path.exists(new):
                    raise ValueError('实例内存在与新名称同名的文件，已取消改名')
                os.rename(old, new)
                moved_files.append((old, new))
        for path, data in changes.items():
            atomic_json(relocated(path), data)
            written.append(path)
    except Exception as error:
        try:
            for path in reversed(written):
                dest = relocated(path)
                if backups[path] is None:
                    os.unlink(dest)
                else:
                    with open(dest, 'wb') as file:
                        file.write(backups[path])
            for old, new in reversed(moved_files):
                os.rename(new, old)
            if moved:
                os.rename(target, source)
        except OSError as rollback_error:
            raise RuntimeError(f'改名失败，回滚也未完成，请保留目录 {target}：{rollback_error}') from error
        raise


def open_bytes(path):
    with open(path, 'rb') as file:
        return file.read()
