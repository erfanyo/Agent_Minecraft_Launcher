"""GUI-independent client-instance to candidate-server builder.

Only official, checksum-verified loader installers are run. Package scripts are
never executed and Minecraft itself is not started here, so EULA acceptance
remains an explicit action in the existing server launch flow.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from archive_inspection import required_java
from safe_paths import safe_child
from server_launch import build_launch_plan
from server_pack_report import report_json, report_text
from server_pack_rules import inspect_client_instance, sha256_file
from task_context import checkpoint


def supported_conversion(loader, minecraft):
    if loader not in ('forge', 'neoforge'):
        return False, '第一版自动安装服务端运行库仅支持 Forge / NeoForge。'
    try:
        minor = int(str(minecraft).split('.')[1])
    except (IndexError, ValueError):
        return False, '无法确认 Minecraft 正式版本。'
    if minor < 17:
        return False, '第一版自动转换支持 Minecraft 1.17 及以上；旧 Forge 后续单独适配。'
    return True, ''


def _safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', str(value or '')).strip(' .')
    return value[:80] or 'AMCL 候选服务端'


def _copy_verified(source_root, stage, entries, status, progress):
    done = 0
    total = sum(int(item['bytes']) for item in entries) or 1
    for item in entries:
        checkpoint()
        source = Path(safe_child(source_root, item['source']))
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"来源文件已消失或变成链接：{item['source']}")
        if source.stat().st_size != item['bytes'] or sha256_file(source) != item['sha256']:
            raise ValueError(f"来源文件在扫描后发生变化：{item['source']}")
        target = Path(safe_child(stage, item['target']))
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with source.open('rb') as src, target.open('xb') as dst:
            while chunk := src.read(1024 * 1024):
                checkpoint()
                digest.update(chunk)
                dst.write(chunk)
                done += len(chunk)
                progress(done, total)
        if digest.hexdigest() != item['sha256']:
            raise ValueError(f"复制校验失败：{item['source']}")
    status('客户端内容复制并复核完成。')


def _archive(stage, destination, manifest, report, status, progress):
    files = []
    for disk in sorted(stage.rglob('*')):
        if disk.is_file():
            relative = disk.relative_to(stage).as_posix()
            files.append((disk, 'server/' + relative))
    manifest_files = []
    total = sum(path.stat().st_size for path, _ in files) or 1
    done = 0
    with zipfile.ZipFile(destination, 'x', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for disk, relative in files:
            checkpoint()
            digest = hashlib.sha256()
            size = 0
            with disk.open('rb') as src, archive.open(relative, 'w', force_zip64=True) as dst:
                while chunk := src.read(1024 * 1024):
                    checkpoint()
                    digest.update(chunk)
                    dst.write(chunk)
                    size += len(chunk)
                    done += len(chunk)
                    progress(done, total)
            manifest_files.append({'path': relative, 'bytes': size,
                                   'sha256': digest.hexdigest()})
        manifest['files'] = manifest_files
        archive.writestr('amcl-server-pack.json',
                         json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr('amcl-build-report.json', report_json(report))
        archive.writestr('AMCL-候选服务端审核报告.txt', report_text(report))
    status('候选服务端包已生成。')


def build_candidate_server_pack(instance_dir, destination, *, name, minecraft,
                                loader, loader_version, java, selected_world=None,
                                status_callback=None, progress_callback=None,
                                runtime_installer=None):
    """Build a complete candidate ZIP without changing the client instance."""
    status = status_callback or (lambda _message: None)
    progress = progress_callback or (lambda _done, _total: None)
    ok, reason = supported_conversion(loader, minecraft)
    if not ok:
        raise ValueError(reason)
    if not re.fullmatch(r'[\w.+\-]+', str(loader_version or '')):
        raise ValueError('无法确认加载器版本，请先检查实例信息。')
    destination = Path(destination).absolute()
    if destination.exists():
        raise ValueError('目标文件已经存在，未覆盖。')
    destination.parent.mkdir(parents=True, exist_ok=True)
    status('正在只读扫描客户端实例并分类 Mod…')
    source_report = inspect_client_instance(instance_dir, selected_world=selected_world)
    from server_install import install_server_runtime
    installer = runtime_installer or install_server_runtime
    created = False
    with tempfile.TemporaryDirectory(prefix='.amcl-server-build-',
                                     dir=destination.parent) as temporary:
        stage = Path(temporary, 'server')
        stage.mkdir()
        status('正在安装对应的服务端运行库；不会启动服务器…')
        installer(stage, loader, minecraft, loader_version, java, status=status)
        plan = build_launch_plan(stage)
        if plan.get('loader') != loader or plan.get('minecraftVersion') != minecraft:
            raise ValueError('安装出的服务端运行库与客户端版本不一致。')
        status('正在复制服务端共用内容并逐文件复核…')
        _copy_verified(source_report['sourceRoot'], stage, source_report['files'],
                       status, progress)
        # The builder never carries acceptance from a client or prior server.
        (stage / 'eula.txt').unlink(missing_ok=True)
        report = {
            'schemaVersion': 1,
            'name': _safe_name(name),
            'minecraftVersion': minecraft,
            'loader': loader,
            'loaderVersion': loader_version,
            'requiredJava': required_java(minecraft),
            'source': {'instanceName': Path(instance_dir).name,
                       'sourcePathStored': False, 'readOnly': True},
            'selectedWorld': selected_world,
            'mods': source_report['mods'],
            'secretPaths': source_report['secretPaths'],
            'warnings': source_report['warnings'],
            'verification': {
                'level': 'static-launch-plan',
                'label': '运行库与启动入口已静态验证；等待用户确认 EULA 后首次隔离启动',
                'entry': plan['entry'],
                'minecraftStarted': False,
            },
        }
        manifest = {'schemaVersion': 1, 'name': report['name'],
                    'minecraftVersion': minecraft, 'loader': loader,
                    'loaderVersion': loader_version, 'requiredJava': required_java(minecraft),
                    'serverRoot': 'server', 'contentProfile': 'runtime-and-mods',
                    'generatedBy': 'AMCL client-to-server candidate builder',
                    'eulaAccepted': False, 'files': []}
        status('正在压缩候选服务端并生成审核报告…')
        try:
            _archive(stage, destination, manifest, report, status, progress)
            created = True
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    if not created:
        raise RuntimeError('候选服务端包没有生成。')
    return {'path': str(destination), 'report': report}

