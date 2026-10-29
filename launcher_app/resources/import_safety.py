"""Read-only checks and bounded single-wrapper preparation before GUI import."""
from pathlib import Path
import tempfile
import zipfile

from launcher_app.resources.archive_inspection import inspect_archive, sha256
from launcher_app.resources.download_review import review_inspection


def prepare_import(path, *, scan_enabled=True, status_callback=None):
    status = status_callback or (lambda _: None)
    source = Path(path).resolve(strict=True)
    original = source
    layers = []
    # TAR and folders retain the existing strict smart-import scanner.
    if source.is_dir() or source.suffix.casefold() not in ('.zip', '.mrpack'):
        return {'path': str(source), 'original': str(original), 'layers': [],
                'antivirus': {'status': 'unavailable', 'message':
                    '此来源未接入自动杀毒检查，请使用本机杀软手动扫描。'}}
    from launcher_app.resources.modpack import detect_modpack_format
    for depth in range(3):
        inspection = inspect_archive(source, status_callback=status,
            allow_identical_case_duplicates=detect_modpack_format(str(source)) == 'multimc')
        layers.append({'path': str(source), 'sha256': inspection['sha256'],
                       'review': review_inspection(inspection)})
        if detect_modpack_format(str(source)) is not None:
            break
        files = inspection['files']
        if len(files) != 1:
            break
        member = next(iter(files))
        if Path(member).suffix.casefold() not in ('.zip', '.mrpack'):
            break
        if depth == 2:
            raise ValueError('压缩包嵌套层数过多，请手动确认真正的整合包。')
        # Never extract a supplied path: one validated member to a fixed filename,
        # exclusive new directory next to the original; both ZIPs remain available.
        folder = Path(tempfile.mkdtemp(prefix='AMCL-import-', dir=original.parent))
        prepared = folder / ('modpack' + Path(member).suffix.casefold())
        try:
            with zipfile.ZipFile(source) as archive, archive.open(member) as reader, prepared.open('xb') as writer:
                from launcher_app.core.task_context import checkpoint
                total = 0
                expected = archive.getinfo(member).file_size
                from launcher_app.resources.archive_inspection import MAX_ARCHIVE
                if expected > MAX_ARCHIVE:
                    raise ValueError('内层压缩包超过 8 GiB。')
                while chunk := reader.read(1024 * 1024):
                    checkpoint()
                    total += len(chunk)
                    if total > min(expected, MAX_ARCHIVE):
                        raise ValueError('内层压缩包大小不符。')
                    writer.write(chunk)
                if total != expected:
                    raise ValueError('内层压缩包不完整。')
            if sha256(prepared) != files[member]:
                raise ValueError('准备导入时原包内容发生变化，请重新检查。')
        except BaseException:
            prepared.unlink(missing_ok=True)
            folder.rmdir()
            raise
        source = prepared
    if scan_enabled:
        from launcher_app.resources.antivirus import scan_available_archive
        status('正在请求本机杀软检查原包…')
        attempts = [scan_available_archive(layer['path']) for layer in layers]
        priority = {'attention_required': 4, 'incomplete': 3, 'unavailable': 2,
                    'not_requested': 2, 'no_detection_reported': 1}
        antivirus = max(attempts, key=lambda r: priority.get(r['status'], 3))
    else:
        antivirus = {'status': 'not_requested', 'message':
                     '自动杀毒检查已关闭，尚未完成杀毒检查；可用火绒等本机杀软手动扫描。'}
    for layer in layers:
        if sha256(Path(layer['path'])) != layer['sha256']:
            raise ValueError('安全检查期间文件发生变化，已停止导入。')
    return {'path': str(source), 'original': str(original), 'layers': layers,
            'antivirus': antivirus}
