"""Import exported MultiMC instances with explicit component patch profiles."""
import copy
import json
import os
import shlex
import zipfile
import re

from launcher_app.instances.game_files import _maven_path, install_version_files
from launcher_app.instances.instance_metadata import atomic_json
from launcher_app.core.safe_paths import safe_child, safe_component
from launcher_app.core.task_context import checkpoint


def pack_prefix(names):
    candidates = [name[:-len('mmc-pack.json')] for name in names if name.endswith('mmc-pack.json')]
    return candidates[0] if len(candidates) == 1 else None


def read_profile(archive):
    prefix = pack_prefix(archive.namelist())
    if prefix is None:
        raise ValueError('MultiMC 包必须包含唯一的 mmc-pack.json')
    manifest = json.loads(archive.read(prefix + 'mmc-pack.json'))
    patches = []
    for component in manifest.get('components') or []:
        uid = safe_component(component['uid'])
        patch_path = prefix + 'patches/' + uid + '.json'
        if patch_path not in archive.namelist():
            raise ValueError(f'MultiMC 组件缺少导出的补丁文件：{uid}，暂不能自动转换')
        patch = json.loads(archive.read(patch_path))
        if patch.get('uid') != uid:
            raise ValueError('MultiMC 补丁 UID 与组件清单不一致')
        patches.append(patch)
    patches.sort(key=lambda patch: patch.get('order', 0))
    minecraft = next((patch for patch in patches if patch['uid'] == 'net.minecraft'), None)
    if minecraft is None or not minecraft.get('mainJar'):
        raise ValueError('MultiMC 包缺少完整的 Minecraft 客户端补丁')
    profile = {'libraries': [], 'arguments': {'jvm': [], 'game': []},
               'type': 'release', 'javaVersion': {'majorVersion': 8}}
    from launcher_app.instances.launcher import _merge_libraries
    local_libraries = []
    for patch in patches:
        checkpoint()
        for key in ('mainClass', 'assetIndex', 'assets', 'releaseTime'):
            if key in patch:
                profile[key] = copy.deepcopy(patch[key])
        if 'minecraftArguments' in patch:
            profile['arguments']['game'] = shlex.split(patch['minecraftArguments'])
        profile['arguments']['jvm'].extend(patch.get('+jvmArgs') or [])
        for tweaker in patch.get('+tweakers') or []:
            profile['arguments']['game'].extend(['--tweakClass', tweaker])
        libraries = copy.deepcopy(patch.get('libraries') or [])
        for library in libraries:
            path = _maven_path(library['name'])
            safe_child('libraries', path)
            downloads = library.setdefault('downloads', {})
            if library.get('MMC-hint') == 'local':
                source = prefix + 'libraries/' + os.path.basename(path)
                if source not in archive.namelist():
                    raise ValueError(f'MultiMC 包缺少本地库：{source}')
                local_libraries.append((source, path))
                downloads['artifact'] = {'path': path, 'size': archive.getinfo(source).file_size}
            elif 'artifact' in downloads:
                downloads['artifact'].setdefault('path', path)
                # Prism's exported native artifacts sometimes use a broad OS
                # rule plus an extra architecture label, which Mojang's rule
                # evaluator would otherwise interpret as matching all CPUs.
                match = re.search(r'-natives-(windows|linux|macos)(?:-(arm64|x86))?$', library['name'].split(':')[1])
                if match:
                    system, cpu = match.groups()
                    system = {'macos': 'osx'}.get(system, system)
                    arch = {'arm64': 'aarch64', 'x86': 'x86', None: 'x86_64'}[cpu]
                    library['rules'] = [{'action': 'allow', 'os': {'name': system, 'arch': arch}}]
            elif not downloads:
                base = library.get('url')
                library.pop('downloads')
                if base:
                    library['downloads'] = {'artifact': {'path': path, 'url': base.rstrip('/') + '/' + path}}
            for classifier, data in downloads.get('classifiers', {}).items():
                parts = library['name'].split(':')
                data.setdefault('path', _maven_path(':'.join(parts[:3] + [classifier])))
        profile['libraries'] = _merge_libraries(profile['libraries'], libraries)
    majors = minecraft.get('compatibleJavaMajors') or [8]
    profile['javaVersion'] = {'majorVersion': min(majors)}
    profile['compatibleJavaMajors'] = majors
    profile['downloads'] = {'client': copy.deepcopy(minecraft['mainJar']['downloads']['artifact'])}
    name = prefix.strip('/').split('/')[-1] if prefix else 'MultiMC'
    if prefix + 'instance.cfg' in archive.namelist():
        for line in archive.read(prefix + 'instance.cfg').decode('utf-8-sig').splitlines():
            if line.startswith('name='):
                name = line[5:].strip() or name
    return prefix, name, minecraft['version'], profile, local_libraries


def import_multimc(path, game_dir, instance_id=None, status_callback=None, progress_callback=None):
    from launcher_app.resources.downloader import download_with_mirror, sha1_of_file
    from launcher_app.resources.modpack import _extract_zip_to, _safe_name
    with zipfile.ZipFile(path) as archive:
        prefix, name, mc, profile, local_libraries = read_profile(archive)
        instance_id = safe_component(instance_id or _safe_name(name))
        folder = safe_child(os.path.join(game_dir, 'versions'), instance_id)
        signature = sha1_of_file(path)
        state = safe_child(os.path.join(game_dir, 'versions', '_imports'), instance_id + '.json')
        previous = None
        if os.path.isfile(state):
            with open(state, encoding='utf-8') as file:
                previous = json.load(file)
        if os.path.exists(folder) and previous != {'archive': signature}:
            raise ValueError(f'已存在同名实例：{instance_id}')
        os.makedirs(folder, exist_ok=True)
        atomic_json(state, {'archive': signature})
        if status_callback:
            status_callback(f'导入 MultiMC 实例 {name}，Minecraft {mc}，Java {profile["javaVersion"]["majorVersion"]}+…')
        for source, relative in local_libraries:
            checkpoint()
            target = safe_child(os.path.join(game_dir, 'libraries'), relative)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(source) as src, open(target, 'wb') as dst:
                while chunk := src.read(256 * 1024):
                    checkpoint()
                    dst.write(chunk)
    _extract_zip_to(path, folder, prefix + '.minecraft/', status_callback, progress_callback,
                    allow_identical_case_duplicates=True)
    profile['id'] = instance_id
    client = profile['downloads']['client']
    download_with_mirror(client['url'], os.path.join(folder, instance_id + '.jar'),
                         sha1=client.get('sha1'), progress_callback=progress_callback)
    _, failures = install_version_files(profile, game_dir, status_callback=status_callback,
                                        progress_callback=progress_callback)
    if failures:
        raise RuntimeError('MultiMC 依赖下载未完成：' + str(failures[:5]))
    checkpoint()
    atomic_json(os.path.join(folder, instance_id + '.json'), profile)
    atomic_json(os.path.join(folder, 'amcl_instance.json'),
                {'minecraft_version': mc, 'source_type': 'multimc', 'name': name})
    os.unlink(state)
    return instance_id
