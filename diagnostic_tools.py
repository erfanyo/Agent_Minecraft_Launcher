"""Evidence-oriented instance tools. No game-success claims based on a PID."""
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote

import paths
from safe_paths import safe_child, safe_component
from instance_metadata import atomic_json
from instance_maintenance import target, assert_stopped, _lock

_runs = {}
_compatible_replacement_cache = {}


def list_instance_snapshots(instance: str):
    root = _store(instance)
    rows = []
    if os.path.isdir(root):
        for entry in os.scandir(root):
            manifest = os.path.join(entry.path, 'manifest.json')
            if entry.is_dir() and os.path.isfile(manifest):
                with open(manifest, encoding='utf-8') as file:
                    data = json.load(file)
                rows.append({'snapshot_id': entry.name, 'environment': data.get('environment'),
                             'files': len(data.get('files', {}))})
    return json.dumps(rows, ensure_ascii=False)


def _compatible_mod_versions(instance: str, project: str):
    import requests
    env = environment(instance)
    check_constraint(instance)
    response = requests.get('https://api.modrinth.com/v2/project/' + quote(project, safe='') + '/version',
                            params={'game_versions': json.dumps([env['minecraft']]),
                                    'loaders': json.dumps([env['loader']])}, timeout=20)
    response.raise_for_status()
    rows = [v for v in response.json() if env['minecraft'] in v.get('game_versions', [])
            and env['loader'] in v.get('loaders', [])]
    result = []
    for version in rows[:20]:
        files = version.get('files') or []
        artifact = next((item for item in files if item.get('primary')), files[0] if files else {})
        result.append({
            'version_id': version['id'],
            'version': version['version_number'],
            'version_type': version.get('version_type'),
            'file': {
                'filename': artifact.get('filename'),
                'size': artifact.get('size'),
                'sha1': (artifact.get('hashes') or {}).get('sha1'),
            },
            'dependencies': [{key: dependency.get(key) for key in
                              ('project_id', 'version_id', 'file_name', 'dependency_type')}
                             for dependency in version.get('dependencies') or []],
        })
    return result


def find_compatible_mod_versions(instance: str, project: str):
    return json.dumps(_compatible_mod_versions(instance, project), ensure_ascii=False)


def _mod_identity_terms(metadata_summary, filename):
    """Return short, ordered identity hints declared inside the JAR."""
    terms = []

    def add(value):
        if isinstance(value, str):
            value = value.strip()
            if value and value.lower() not in {'minecraft', 'forge', 'neoforge', 'fabricloader', 'javafml'}:
                if value.lower() not in {item.lower() for item in terms}:
                    terms.append(value)

    for item in metadata_summary.values():
        declarations = item.get('declarations', {}) if isinstance(item, dict) else {}
        if isinstance(declarations, dict):
            add(declarations.get('id'))
            add(declarations.get('name'))
            mods = declarations.get('mods')
            if isinstance(mods, list):
                for mod in mods:
                    if isinstance(mod, dict):
                        add(mod.get('modId'))
                        add(mod.get('displayName'))
                        add(mod.get('modid'))
                        add(mod.get('name'))
        elif isinstance(declarations, list):
            for mod in declarations:
                if isinstance(mod, dict):
                    add(mod.get('modid'))
                    add(mod.get('name'))
    # The filename is only a final search hint; it never establishes project identity.
    if not terms:
        add(Path(filename).stem)
    return terms[:4]


def _same_identity(candidate, terms):
    import re
    normalize = lambda value: re.sub(r'[^a-z0-9]+', '', str(value).lower())
    declared = {normalize(term) for term in terms if normalize(term)}
    return any(normalize(candidate.get(key)) in declared for key in ('slug', 'title'))


def find_compatible_mod_replacement(instance: str, filename: str):
    """Identify a local JAR and find an exact current-environment replacement."""
    import requests
    safe_component(filename)
    env = environment(instance)
    check_constraint(instance)
    path = safe_child(os.path.join(_folder(instance), 'mods'), filename)
    stat = os.stat(path)
    cache_key = (os.path.realpath(path), stat.st_size, stat.st_mtime_ns,
                 env['minecraft'], env['loader'])
    cached = _compatible_replacement_cache.get(cache_key)
    if cached is not None:
        result = dict(cached)
        result['cached'] = True
        return json.dumps(result, ensure_ascii=False)

    inspected = json.loads(inspect_mod_jar(instance, filename, view='summary'))
    terms = _mod_identity_terms(inspected.get('metadata_summary', {}), filename)
    project = None
    identity_source = None
    response = requests.get('https://api.modrinth.com/v2/version_file/' + inspected['sha1'],
                            params={'algorithm': 'sha1'}, timeout=20)
    if response.status_code == 200:
        version = response.json()
        project_id = version.get('project_id')
        if project_id:
            project = {'slug': project_id, 'title': project_id}
            identity_source = 'file_hash'
    elif response.status_code != 404:
        response.raise_for_status()

    if project is None:
        for term in terms[:2]:
            response = requests.get('https://api.modrinth.com/v2/search', params={
                'query': term, 'facets': json.dumps([['project_type:mod']]),
                'limit': 3, 'index': 'relevance'}, timeout=20)
            response.raise_for_status()
            matches = [hit for hit in response.json().get('hits', [])
                       if _same_identity(hit, [term])]
            if len(matches) == 1:
                project = {'slug': matches[0].get('slug') or matches[0].get('project_id'),
                           'title': matches[0].get('title') or matches[0].get('slug')}
                identity_source = 'internal_mod_id'
                break

    versions = _compatible_mod_versions(instance, project['slug']) if project and project.get('slug') else []
    recommended = next((row for row in versions if row.get('version_type') == 'release'),
                       versions[0] if versions else None)
    action = 'replace' if recommended else ('no_compatible_release' if project else 'identity_ambiguous')
    result = {
        'action': action,
        'local': {'filename': filename, 'sha1': inspected['sha1'], 'declared_ids': terms},
        'environment': env,
        'project': project,
        'identity_source': identity_source,
        'recommended': recommended,
        'next_step': ('用 recommended.version_id 调用 replace_mod_version。' if recommended else
                      '没有可安全自动替换的精确候选；保留原文件并从本次启动中移出。'),
    }
    if len(_compatible_replacement_cache) >= 128:
        _compatible_replacement_cache.pop(next(iter(_compatible_replacement_cache)))
    _compatible_replacement_cache[cache_key] = result
    return json.dumps(result, ensure_ascii=False)


def replace_mod_version(instance: str, filename: str, version_id: str):
    import requests
    from urllib.parse import quote
    from downloader import download_with_mirror
    safe_component(filename)
    env = environment(instance)
    check_constraint(instance)
    response = requests.get('https://api.modrinth.com/v2/version/' + quote(version_id, safe=''), timeout=20)
    response.raise_for_status()
    version = response.json()
    if env['minecraft'] not in version.get('game_versions', []) or env['loader'] not in version.get('loaders', []):
        raise ValueError('候选文件与实例 MC/加载器不匹配，禁止放宽版本条件')
    files = version.get('files') or []
    artifact = next((f for f in files if f.get('primary')), files[0] if files else None)
    if not artifact or not artifact.get('hashes', {}).get('sha1'):
        raise ValueError('缺少可信文件校验信息')
    safe_component(artifact['filename'])
    if not artifact['filename'].endswith('.jar') or not filename.endswith('.jar'):
        raise ValueError('仅支持替换 JAR')
    if not artifact['url'].startswith('https://cdn.modrinth.com/'):
        raise ValueError('不是 Modrinth 的 HTTPS 文件地址')
    with _lock:
        folder = _folder(instance)
        assert_stopped(folder)
        old = safe_child(os.path.join(folder, 'mods'), filename)
        dest = safe_child(os.path.join(folder, 'mods'), artifact['filename'])
        if not os.path.isfile(old):
            raise ValueError('待替换文件不存在')
        if dest != old and os.path.exists(dest):
            raise ValueError('目标版本已存在，请检查重复 Mod；未覆盖')
        backup = safe_child(_store(instance), 'mod-'+uuid.uuid4().hex)
        os.makedirs(backup)
        staged = os.path.join(backup, 'download.jar')
        download_with_mirror(artifact['url'], staged, sha1=artifact['hashes']['sha1'])
        with zipfile.ZipFile(staged) as archive:
            if sum(i.file_size for i in archive.infolist()) > 1024**3:
                raise ValueError('候选文件解压规模过大')
            if archive.testzip():
                raise ValueError('候选 JAR 校验失败')
        check_constraint(instance)
        assert_stopped(folder)
        saved = os.path.join(backup, filename)
        os.rename(old, saved)
        try:
            os.rename(staged, dest)
        except Exception:
            os.rename(saved, old)
            raise
        return json.dumps({'replaced': filename, 'installed': artifact['filename'], 'old_file': saved,
                           'dependencies': version.get('dependencies'),
                           'note': '前置未自动安装；项目身份与功能取舍需依据元数据确认。可用完整快照回退。'}, ensure_ascii=False)


def _hash(path, algorithm='sha256'):
    with open(path, 'rb') as file:
        return hashlib.file_digest(file, algorithm).hexdigest()


def _folder(instance):
    from settings import load_settings
    if not load_settings().get('version_isolation', True):
        raise ValueError('诊断测试要求开启版本隔离，避免改动共享存档。')
    return target(paths.GAME_DIR, instance)


def _store(instance):
    safe_component(instance)
    return safe_child(os.path.join(paths.GAME_DIR, 'diagnostic_snapshots'), instance)


def _inventory(folder):
    result = {}
    for root, dirs, files in os.walk(folder, followlinks=False):
        for name in dirs + files:
            path = os.path.join(root, name)
            if os.path.islink(path) or (hasattr(os.path, 'isjunction') and os.path.isjunction(path)):
                raise ValueError('实例包含链接或目录联接，请先使用独立副本。')
        for name in files:
            path = os.path.join(root, name)
            result[os.path.relpath(path, folder)] = _hash(path)
    return result


def environment(instance):
    from instances import scan_instances
    item = next((v for v in scan_instances(paths.GAME_DIR) if v['id'] == instance), None)
    if not item:
        raise ValueError('不能识别实例环境，请先检查版本描述文件。')
    return {'minecraft': item['base'], 'loader': item['loader']}


def inspect_instance_core(instance: str):
    """Verify local launch metadata, client JAR and declared libraries without downloading."""
    safe_component(instance)
    folder = _folder(instance)
    from launcher import resolve_inherited_json
    from instance_maintenance import current_core
    detail = resolve_inherited_json(instance, paths.GAME_DIR)
    minecraft, loader, loader_version = current_core(paths.GAME_DIR, instance)

    issues = []
    checked = 0
    unverifiable = 0

    def verify(path, expected_sha1=None, expected_size=None):
        nonlocal checked, unverifiable
        if not os.path.isfile(path):
            return 'missing', None
        actual_size = os.path.getsize(path)
        if expected_size is not None and actual_size != expected_size:
            return 'size_mismatch', actual_size
        if expected_sha1:
            checked += 1
            actual_sha1 = _hash(path, 'sha1')
            return ('ok' if actual_sha1.lower() == str(expected_sha1).lower()
                    else 'sha1_mismatch'), actual_size
        unverifiable += 1
        return 'present_no_hash', actual_size

    client = detail.get('downloads', {}).get('client') or {}
    client_path = os.path.join(folder, instance + '.jar')
    client_status, client_size = verify(client_path, client.get('sha1'), client.get('size'))
    library_checked_start = checked
    library_unverifiable_start = unverifiable
    if client_status not in ('ok', 'present_no_hash'):
        issues.append({'kind': 'client', 'status': client_status,
                       'path': os.path.relpath(client_path, paths.GAME_DIR)})

    from game_files import library_entries
    libraries_root = os.path.join(paths.GAME_DIR, 'libraries')
    declared = 0
    library_issues = []
    seen = set()
    for relative, _url, expected_sha1, expected_size in library_entries(detail):
        if not relative or relative in seen:
            continue
        seen.add(relative)
        declared += 1
        path = safe_child(libraries_root, relative)
        status, actual_size = verify(path, expected_sha1, expected_size or None)
        if status not in ('ok', 'present_no_hash'):
            entry = {'status': status, 'path': relative,
                     'actual_size': actual_size}
            library_issues.append(entry)
            issues.append({'kind': 'library', **entry})

    own_json = os.path.join(folder, instance + '.json')
    own_id = None
    try:
        with open(own_json, encoding='utf-8') as file:
            own_id = json.load(file).get('id')
    except Exception as exc:
        issues.append({'kind': 'version_json', 'status': 'invalid',
                       'error': type(exc).__name__})
    if own_id is not None and own_id != instance:
        issues.append({'kind': 'version_json', 'status': 'id_mismatch',
                       'declared_id': own_id, 'folder_id': instance})

    status = 'issues_found' if issues else ('verified' if checked else 'present_but_unverifiable')
    result = {
        'instance': instance,
        'environment': {'minecraft': minecraft, 'loader': loader,
                        'loader_version': loader_version},
        'version_json': {'path': os.path.relpath(own_json, paths.GAME_DIR),
                         'declared_id': own_id, 'main_class': detail.get('mainClass')},
        'client': {'path': os.path.relpath(client_path, paths.GAME_DIR),
                   'status': client_status, 'actual_size': client_size,
                   'expected_size': client.get('size'), 'expected_sha1': client.get('sha1')},
        'libraries': {'declared_artifacts': declared,
                      'hashes_checked': checked - library_checked_start,
                      'unverifiable_files': unverifiable - library_unverifiable_start,
                      'issues': library_issues[:50],
                      'issue_count': len(library_issues)},
        'status': status,
        'repair_recommended': bool(issues),
        'note': ('只读本地校验；未联网也未修改文件。只有 issues_found 才支持核心修补判断；'
                 'present_but_unverifiable 表示缺少可信哈希，不能据此断言核心损坏。'),
    }
    return json.dumps(result, ensure_ascii=False)


def check_constraint(instance, version=None, loader=None):
    path = os.path.join(_store(instance), 'constraint.json')
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as file:
            constraint = json.load(file)
        actual = environment(instance) if version is None else {'minecraft': version, 'loader': loader or None}
        if actual != constraint:
            raise ValueError('测试环境已锁定：' + json.dumps(constraint, ensure_ascii=False) + '；不能更换 MC 或加载器。')


def snapshot_instance(instance: str, lock_environment: bool = True):
    """Full isolated instance, excluding shared libraries/assets; immutable id."""
    with _lock:
        folder = _folder(instance)
        assert_stopped(folder)
        check_constraint(instance)
        token = uuid.uuid4().hex
        dest = safe_child(_store(instance), token)
        before = _inventory(folder)
        os.makedirs(dest)
        shutil.copytree(folder, os.path.join(dest, 'files'))
        if before != _inventory(os.path.join(dest, 'files')) or before != _inventory(folder):
            raise RuntimeError('复制期间实例发生变化，快照未完成，请退出其他编辑程序重试。')
        env = environment(instance)
        atomic_json(os.path.join(dest, 'manifest.json'), {'instance': instance, 'files': before, 'environment': env})
        if lock_environment:
            atomic_json(os.path.join(_store(instance), 'constraint.json'), env)
        return json.dumps({'snapshot_id': token, 'directory': dest, 'files': len(before),
                           'locked_environment': env if lock_environment else None}, ensure_ascii=False)


def restore_instance_snapshot(instance: str, snapshot_id: str):
    safe_component(snapshot_id)
    with _lock:
        folder = _folder(instance)
        assert_stopped(folder)
        source = safe_child(_store(instance), snapshot_id)
        with open(os.path.join(source, 'manifest.json'), encoding='utf-8') as file:
            manifest = json.load(file)
        if manifest['instance'] != instance:
            raise ValueError('快照不属于这个实例')
        env = manifest['environment']
        check_constraint(instance, env['minecraft'], env['loader'])
        if _inventory(os.path.join(source, 'files')) != manifest['files']:
            raise ValueError('快照校验失败，未恢复')
        stage = safe_child(_store(instance), 'restore-'+uuid.uuid4().hex)
        shutil.copytree(os.path.join(source, 'files'), stage)
        rollback = safe_child(_store(instance), 'before-restore-'+uuid.uuid4().hex)
        os.rename(folder, rollback)
        try:
            os.rename(stage, folder)
        except Exception:
            os.rename(rollback, folder)
            raise
        return '已恢复测试现场；恢复前实例完整保留在：' + rollback


def _metadata_summary(metadata):
    """Extract declarations mechanically, without inferring compatibility/origin."""
    import tomllib
    result = {}
    for name, text in metadata.items():
        try:
            if name.endswith('.toml'):
                data = tomllib.loads(text)
                fields = ('modLoader', 'loaderVersion', 'mods', 'dependencies', 'features',
                          'mixins', 'accessTransformers')
            elif name == 'fabric.mod.json':
                data = json.loads(text)
                fields = ('id', 'name', 'version', 'environment', 'provides', 'depends',
                          'recommends', 'suggests', 'conflicts', 'breaks', 'jars',
                          'mixins', 'accessWidener', 'entrypoints')
            elif name == 'quilt.mod.json':
                data = json.loads(text)
                fields = ('quilt_loader', 'minecraft')
            elif name == 'mcmod.info':
                result[name] = {'status': 'parsed', 'declarations': json.loads(text)}
                continue
            else:
                continue  # MANIFEST is available in the full view, not a mod dependency table.
            if not isinstance(data, dict):
                raise ValueError('Expected metadata object')
            declarations = {key: data[key] for key in fields if key in data}
            # Human descriptions can dwarf the actual mod IDs and dependency declarations.
            if isinstance(declarations.get('mods'), list):
                declarations['mods'] = [{k: v for k, v in item.items()
                                        if k not in ('description', 'credits')}
                                       if isinstance(item, dict) else item for item in declarations['mods']]
            result[name] = {'status': 'parsed', 'declarations': declarations}
        except (ValueError, TypeError) as exc:
            result[name] = {'status': 'parse_error', 'error': str(exc),
                            'note': '未能解析；不能按无依赖处理，请用 full 视图核对原文。'}
    return result


def inspect_mod_jar(instance: str, filename: str, expected_sha1: str = '', view: str = 'full'):
    if view not in ('full', 'summary'):
        raise ValueError('view 必须为 full 或 summary')
    safe_component(filename)
    path = safe_child(os.path.join(_folder(instance), 'mods'), filename)
    if os.path.getsize(path) > 512 * 1024 * 1024:
        raise ValueError('文件超过 512 MiB，暂不进行自动解包检查')
    report = {'filename': filename, 'sha256': _hash(path), 'sha1': _hash(path, 'sha1'), 'metadata': {},
              'warning': '元数据也是文件提供的声明。ZIP 完整不代表未缺类；需与可信原文件哈希比较。'}
    if expected_sha1:
        import re
        if not re.fullmatch('[a-fA-F0-9]{40}', expected_sha1):
            raise ValueError('预期 SHA1 格式无效，请使用可信版本 API 的文件哈希')
        report['matches_expected_sha1'] = report['sha1'] == expected_sha1.lower()
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if sum(i.file_size for i in members) > 1024**3 or len(members) > 100000:
                raise ValueError('解压规模过大，停止检查')
            report['bad_crc_member'] = archive.testzip()
            for name in ('fabric.mod.json', 'quilt.mod.json', 'META-INF/neoforge.mods.toml',
                         'META-INF/mods.toml', 'mcmod.info', 'META-INF/MANIFEST.MF'):
                if name in archive.namelist():
                    if archive.getinfo(name).file_size > 256000:
                        raise ValueError('元数据过大')
                    report['metadata'][name] = archive.read(name).decode('utf-8', errors='replace')
            report['entries'] = len(members)
    except zipfile.BadZipFile as exc:
        report['zip_error'] = str(exc)
    report['metadata_summary'] = _metadata_summary(report['metadata'])
    if view == 'summary':
        report.pop('metadata')
        report['metadata_view'] = 'summary; full 视图可读取原始元数据；声明不是来源认证。'
    return json.dumps(report, ensure_ascii=False)


def set_mod_enabled(instance: str, filename: str, enabled: bool, reason: str = ''):
    safe_component(filename)
    with _lock:
        folder = _folder(instance)
        assert_stopped(folder)
        if enabled and not filename.endswith('.jar.disabled') or not enabled and not filename.endswith('.jar'):
            raise ValueError('禁用请指定 .jar；启用请指定 .jar.disabled')
        source = safe_child(os.path.join(folder, 'mods'), filename)
        destination = source[:-9] if enabled else source + '.disabled'
        if os.path.exists(destination):
            raise ValueError('目标文件已经存在，未覆盖')
        os.rename(source, destination)
        return json.dumps({'enabled': enabled, 'filename': os.path.basename(destination),
                           'reason': reason or None,
                           'user_effect': ('这个 Mod 已从本次启动中移出，原文件仍保留。'
                                           if not enabled else '这个 Mod 已恢复到本次启动。'),
                           'undo': {'tool': 'set_mod_enabled', 'arguments': {
                               'instance': instance, 'filename': os.path.basename(destination),
                               'enabled': not enabled}}}, ensure_ascii=False)


def observe_game(instance: str, wait_seconds: int = 3):
    key = (os.path.realpath(paths.GAME_DIR), instance)
    run = _runs.get(key)
    if not run:
        return '没有本次工具启动的运行记录；不能根据历史日志判断本轮成功。'
    process, logfile, started = run
    try:
        process.wait(timeout=max(0, min(10, int(wait_seconds))))
    except subprocess.TimeoutExpired:
        pass
    from log_privacy import redact
    from settings import load_settings
    with open(logfile, 'rb') as file:
        file.seek(0, 2)
        file.seek(max(0, file.tell() - 65536))
        window = file.read().decode('utf-8', errors='replace')
    signal_terms = ('error', 'fatal', 'exception', 'caused by', 'missing', 'unsupported',
                    'requires', 'crashed', ' joined the game', 'stopping server')
    signals = []
    for line in window.splitlines():
        if any(term in line.lower() for term in signal_terms):
            clipped = line[-360:]
            if clipped not in signals:
                signals.append(clipped)
    signals = signals[-20:]
    tail = window[-5000:]
    lowered = window.lower()
    return json.dumps(redact({'pid': process.pid, 'exit_code': process.poll(),
                              'running': process.poll() is None, 'seconds': time.monotonic()-started,
                              'verification': 'not_verified',
                              'signals': {
                                  'joined_world': ' joined the game' in lowered,
                                  'dependency_error': ('missing or unsupported mandatory dependencies' in lowered
                                                       or 'requires mod' in lowered),
                                  'mixin_error': any(term in lowered for term in
                                                     ('invalidmixinexception', 'mixinapplyerror')),
                                  'crash_detected': any(term in lowered for term in
                                                        ('game crashed', 'fatal', 'crash report saved')),
                              },
                              'high_signal_lines': signals,
                              'current_run_log_tail': tail,
                              'note': '进程仍在运行不等于进入世界。日志仅对应本轮；请继续观察或让用户确认画面。'}, load_settings()), ensure_ascii=False)


def diagnostic_launch(instance, game_dir=None):
    from game_launch_service import GameLaunchService
    from settings import load_settings, save_settings
    from instances import scan_instances
    from memory_policy import track_process
    if game_dir and os.path.realpath(game_dir) != os.path.realpath(paths.GAME_DIR):
        raise ValueError('请先在设置中切换到该游戏目录')
    folder = _folder(instance)
    assert_stopped(folder)
    check_constraint(instance)
    settings = load_settings()
    service = GameLaunchService(lambda: paths.GAME_DIR, lambda: paths.RUNTIME_DIR,
                               lambda: settings, save_settings, lambda i: target(paths.GAME_DIR, i))
    item = next(v for v in scan_instances(paths.GAME_DIR) if v['id'] == instance)
    plan = service.prepare(dict(item, local=True))
    with _lock:
        assert_stopped(folder)
        check_constraint(instance)
        logfile = os.path.join(paths.data_dir('diagnostic_runs'), uuid.uuid4().hex + '.log')
        with open(logfile, 'wb') as output:
            process = subprocess.Popen(plan.command, cwd=plan.game_dir, stdout=output, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        _runs[(os.path.realpath(paths.GAME_DIR), instance)] = (process, logfile, time.monotonic())
        track_process(process, folder)
    return '已创建游戏进程，尚未确认成功；请调用 observe_game 读取本轮输出。PID：' + str(process.pid)


def compare_instance_snapshot(instance: str, snapshot_id: str):
    safe_component(snapshot_id)
    folder = _folder(instance)
    source = safe_child(_store(instance), snapshot_id)
    with open(os.path.join(source, 'manifest.json'), encoding='utf-8') as file:
        manifest = json.load(file)
    if manifest['instance'] != instance:
        raise ValueError('快照不属于该实例')
    baseline = manifest['files']
    current = _inventory(folder)
    added = sorted(current.keys() - baseline.keys())
    removed = sorted(baseline.keys() - current.keys())
    changed = sorted(k for k in current.keys() & baseline.keys() if current[k] != baseline[k])
    result = {'snapshot_id': snapshot_id, 'added': added[:500], 'removed': removed[:500],
              'changed': changed[:500], 'counts': {'added': len(added), 'removed': len(removed), 'changed': len(changed)},
              'note': '每类最多显示 500 项。包含游戏自身写入的日志/配置变化，不全部归因于 AI；不是成功判定。'}
    return json.dumps(result, ensure_ascii=False)
