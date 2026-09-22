"""Install official server runtime into staging, then add missing files only."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import requests

from downloader import download_with_mirror
from java_manager import java_version_probe, minecraft_java_range
from safe_paths import safe_child
from server_launch import build_launch_plan
from task_context import run_process, checkpoint


def inferred_runtime_identity(report):
    """Return trustworthy prefilled runtime fields from an archive scan report."""
    report = dict(report or {})
    merged = {**(report.get('declaredRuntime') or {}),
              **{key: value for key, value in report.items()
                 if value not in (None, '', 'unknown')}}
    loader = str(merged.get('loader') or '').lower()
    if loader not in ('forge', 'neoforge'):
        loader = ''
    return {'loader': loader,
            'minecraftVersion': str(merged.get('minecraftVersion') or '').strip(),
            'loaderVersion': str(merged.get('loaderVersion') or '').strip(),
            'requiredJava': merged.get('requiredJava')}


def installer_source(loader, mc, version):
    if not re.fullmatch(r'1\.\d+(?:\.\d+)?', mc):
        raise ValueError('请输入完整的 Minecraft 正式版本号。')
    if not re.fullmatch(r'\d+(?:\.\d+)+(?:-beta)?', version):
        raise ValueError('请输入加载器版本号，不要填网址或文件路径。')
    if tuple(int(p) for p in mc.split('.')[1:]) < (17,):
        raise ValueError('本轮自动补全仅支持 Minecraft 1.17 及以上。')
    if loader == 'forge':
        coordinate = f'{mc}-{version}'
        return f'https://maven.minecraftforge.net/net/minecraftforge/forge/{coordinate}/forge-{coordinate}-installer.jar'
    if loader == 'neoforge':
        parts = version.split('.')
        if mc != f'1.{parts[0]}.{parts[1]}':
            raise ValueError('NeoForge 版本号与 Minecraft 版本不匹配。')
        return f'https://maven.neoforged.net/releases/net/neoforged/neoforge/{version}/neoforge-{version}-installer.jar'
    raise ValueError('自动补全目前支持 Forge / NeoForge。')


def _digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        while data := stream.read(1024 * 1024):
            h.update(data)
    return h.hexdigest()


def install_server_runtime(root, loader, mc, version, java, status=lambda _: None):
    source = installer_source(loader, mc, version)
    root = Path(root).resolve(strict=True)
    major, error = java_version_probe(java)
    if error:
        raise ValueError(error)
    minimum, maximum = minecraft_java_range(mc)
    if major < minimum or (maximum and major > maximum):
        raise ValueError(f'Java {major} 与 MC {mc} 不兼容，请重新选择 Java。')
    status('正在从官方 Maven 获取安装器校验值…')
    response = requests.get(source + '.sha1', timeout=(10, 30), allow_redirects=False)
    response.raise_for_status()
    checksum = response.text.strip()
    if not re.fullmatch(r'[a-fA-F0-9]{40}', checksum):
        raise ValueError('官方未返回有效 SHA-1，已停止，不运行未校验安装器。')
    with tempfile.TemporaryDirectory(prefix='.amcl-runtime-', dir=root.parent) as temporary:
        staging = Path(temporary)
        installer = staging / 'installer.jar'
        status('正在下载安装器并校验…')
        download_with_mirror(source, str(installer), sha1=checksum, strategy='official_only')
        runtime = staging / 'runtime'
        runtime.mkdir()
        environment = dict(os.environ)
        for key in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS', 'CLASSPATH'):
            environment.pop(key, None)
        status('正在安装服务端运行库；可能需要几分钟，不会修改世界和配置…')
        result = run_process([java, '-jar', str(installer), '--installServer'], cwd=str(runtime),
                             timeout=1800, env=environment,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode:
            from log_privacy import redact_text
            detail = (result.stderr or result.stdout or b'').decode('utf-8', errors='replace')[-3000:]
            raise RuntimeError(f'安装器退出码 {result.returncode}：\n{redact_text(detail)}')
        plan = build_launch_plan(runtime)
        if plan['loader'] != loader or plan.get('minecraftVersion') != mc:
            raise ValueError('安装结果与所选版本不一致，未合入实例。')
        pending = []
        for file in runtime.rglob('*'):
            if file.is_symlink() or getattr(file, 'is_junction', lambda: False)():
                raise ValueError('安装结果包含链接，已停止。')
            if not file.is_file():
                continue
            relative = file.relative_to(runtime).as_posix()
            # Never merge scripts, EULA, worlds, properties, or installer logs.
            if not (relative.startswith('libraries/') or relative.endswith('.jar') and '/' not in relative):
                continue
            target = Path(safe_child(root, relative))
            digest = _digest(file)
            if target.exists():
                if not target.is_file() or _digest(target) != digest:
                    raise ValueError(f'已有文件与官方运行库不同，未覆盖：{relative}')
            else:
                pending.append((file, target, digest))
        checkpoint()
        status(f'正在补入 {len(pending)} 个缺失文件…')
        created = []
        try:
            for file, target, digest in pending:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as dst:
                    created.append(target)
                    with file.open('rb') as src:
                        shutil.copyfileobj(src, dst)
            final = build_launch_plan(root)
            if final['loader'] != loader or final.get('minecraftVersion') != mc:
                raise ValueError('目标目录存在其他加载器入口，请先整理版本。')
        except BaseException:
            for target in reversed(created):
                target.unlink(missing_ok=True)
            raise
        return final
