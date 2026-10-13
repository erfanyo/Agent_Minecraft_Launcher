"""Stage repository-pinned BridgeMod JARs for source and release builds."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PREBUILT = ROOT / 'bridge-mod/prebuilt'
MANIFEST = json.loads((PREBUILT / 'manifest.json').read_text(encoding='utf-8'))
ARTIFACTS = MANIFEST['artifacts']


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(256 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_bundle(directory):
    directory = Path(directory)
    errors = []
    expected = set()
    for item in ARTIFACTS:
        name = item['file']
        if Path(name).name != name or not name.endswith('.jar'):
            raise ValueError('Invalid bridge artifact filename')
        expected.add(name)
        path = directory / name
        if not path.is_file():
            errors.append('缺少 bridge-mod：' + name)
        elif path.is_symlink() or _sha256(path) != item['sha256']:
            errors.append('bridge-mod SHA256 校验失败：' + name)
    for path in directory.glob('*.jar'):
        if path.name not in expected:
            errors.append('存在清单外 bridge-mod，打包前请移走：' + path.name)
    return errors


def stage_bundle(destination, force=False):
    errors = verify_bundle(PREBUILT)
    if errors:
        raise ValueError('\n'.join(errors))
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for item in ARTIFACTS:
        path = destination / item['file']
        if not force and path.is_file() and not path.is_symlink() and _sha256(path) == item['sha256']:
            continue
        if path.is_symlink():
            raise ValueError('Refusing symlink destination: ' + str(path))
        handle, temporary = tempfile.mkstemp(prefix='.bridge-', dir=destination)
        os.close(handle)
        try:
            shutil.copyfile(PREBUILT / item['file'], temporary)
            if _sha256(temporary) != item['sha256']:
                raise ValueError('Copied bridge artifact failed verification')
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    errors = verify_bundle(destination)
    if errors:
        raise ValueError('\n'.join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    try:
        stage_bundle(ROOT / 'bridge-mod/dist', force=args.force)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')
    print(f'BridgeMod {MANIFEST["version"]}: {len(ARTIFACTS)} pinned JARs verified and ready')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
