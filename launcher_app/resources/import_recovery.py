"""Persistent per-instance unfinished imports; ignoring never marks complete."""
import json
from pathlib import Path
import shutil

from launcher_app.instances.instance_metadata import atomic_json

RECORD = '.amcl-import-attention.json'
_active = set()


def remember(instance, source, digest):
    _active.add(str(Path(instance).resolve()))
    atomic_json(str(Path(instance, RECORD)), {'source': str(Path(source).resolve()),
        'sha256': digest, 'ignored': False})


def preserve_failed_source(instance, source, digest):
    """Smart-import slices may be temporary. Keep exact bytes for restart/retry."""
    from launcher_app.resources.archive_inspection import sha256
    instance, source = Path(instance), Path(source)
    _active.discard(str(instance.resolve()))
    destination = instance.parent / '_imports' / (instance.name + '.source.zip')
    if source.resolve() == destination.resolve():
        return
    try:
        if destination.exists() and sha256(destination) == digest:
            remember(instance, destination, digest)
            _active.discard(str(instance.resolve()))
            return
        temporary = destination.with_suffix('.part')
        shutil.copyfile(source, temporary)
        if sha256(temporary) != digest:
            temporary.unlink(missing_ok=True)
            return
        temporary.replace(destination)
        remember(instance, destination, digest)
        _active.discard(str(instance.resolve()))
    except (OSError, ValueError):
        # Existing unfinished marker/record still survives; don't mask failure.
        pass


def complete(instance):
    _active.discard(str(Path(instance).resolve()))
    Path(instance, RECORD).unlink(missing_ok=True)


def ignore(instance):
    path = Path(instance, RECORD)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data['ignored'] = True
    atomic_json(str(path), data)


def pending(game_dir):
    versions = Path(game_dir, 'versions')
    if not versions.is_dir():
        return []
    result = []
    for number, instance in enumerate(versions.iterdir()):
        if number >= 5000:
            break
        if (not instance.is_dir() or instance.is_symlink()
                or getattr(instance, 'is_junction', lambda: False)()
                or instance.name.startswith('_')):
            continue
        if str(instance.resolve()) in _active:
            continue
        path = instance / RECORD
        legacy = versions / '_imports' / (instance.name + '.json')
        if not path.is_file():
            # Older installs still have the persistent unfinished marker.
            if not legacy.is_file():
                continue
            data = {'source': '', 'sha256': '', 'ignored': False}
        else:
            try:
                if path.stat().st_size > 65536:
                    raise ValueError('Oversized recovery record')
                data = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(data, dict):
                    raise ValueError('Invalid recovery record')
            except (OSError, ValueError):
                # A broken record must not silently turn an unfinished install green.
                data = {'source': '', 'sha256': '', 'ignored': False}
        if data.get('ignored') is True:
            continue
        result.append({**data, 'instance': str(instance), 'name': instance.name,
                       'game_dir': str(versions.parent)})
    return result


def verify_source(record):
    from launcher_app.resources.archive_inspection import sha256
    source = Path(record.get('source') or '')
    return source.is_file() and bool(record.get('sha256')) and sha256(source) == record['sha256']
