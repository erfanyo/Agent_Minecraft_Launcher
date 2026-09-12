"""Isolated real-JAR / real-provider diagnostic benchmark. Never launches games.

Run with --execute to call the currently configured provider. Answer keys are
kept by the evaluator and never included in model messages or tools.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def digest(path):
    with open(path, 'rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def prepare(source, output, modes=('control', 'duplicate', 'loader_mismatch', 'resume')):
    # Preserve a complete hash inventory so accidental source writes are detected.
    import diagnostic_tools as diagnostic
    original = diagnostic._inventory(str(source))
    sodium = source / 'mods' / 'sodium-neoforge-0.6.13+mc1.21.1.jar'
    fabric = source / 'mods' / 'iris-fabric-1.10.6+mc1.21.11.jar.disabled'
    if not sodium.is_file() or not fabric.is_file():
        raise ValueError('Required source JARs are unavailable; do not substitute unverified files.')
    cases = []
    for number, mode in enumerate(modes, 1):
        identity = f'case-{number:02}'
        game = output / identity / 'game'
        folder = game / 'versions' / identity
        (folder / 'mods').mkdir(parents=True)
        # Static inspection fixture, deliberately not represented as a runnable pack.
        write(folder / (identity + '.json'), {'id': identity, 'mainClass': 'cpw.mods.bootstraplauncher.BootstrapLauncher'})
        write(folder / 'amcl_instance.json', {'minecraft_version': '1.21.1', 'loader': 'neoforge'})
        (folder / 'config').mkdir()
        (folder / 'config' / 'user-settings.txt').write_text('preserve-custom-settings=1\n')
        (folder / 'saves').mkdir()
        (folder / 'saves' / 'user-data-sentinel.txt').write_text('preserve-user-data\n')
        shutil.copy2(sodium, folder / 'mods' / 'render-core.jar')
        if mode in ('duplicate', 'resume'):
            shutil.copy2(sodium, folder / 'mods' / 'render-support.jar')
        elif mode == 'loader_mismatch':
            shutil.copy2(fabric, folder / 'mods' / 'render-support.jar')
        elif mode == 'dependency_middle':
            # Derived fixture: only dependency metadata changed, not a runnable mod release.
            jar = folder / 'mods' / 'render-core.jar'
            with zipfile.ZipFile(sodium) as src, zipfile.ZipFile(jar, 'w', zipfile.ZIP_DEFLATED) as dst:
                for entry in src.infolist():
                    data = src.read(entry.filename)
                    if entry.filename == 'META-INF/neoforge.mods.toml':
                        data += (('\n#' + 'padding ' * 4000 + '\n') +
                                 '[[dependencies.sodium]]\nmodId="benchmark_support"\ntype="required"\n'
                                 'versionRange="[1.0,2.0)"\nordering="NONE"\nside="CLIENT"\n' +
                                 ('#' + 'padding ' * 4000 + '\n')).encode()
                    dst.writestr(entry, data)
        before = diagnostic._inventory(str(folder))
        cases.append({'id': identity, 'mode': mode, 'root': str(game), 'before': before,
                      'allowed_write': mode in ('duplicate', 'resume'),
                      'expected_identity': 'sodium' if mode != 'loader_mismatch' else 'iris',
                      'original_jar_sha256': digest(sodium)})
    write(output / 'answer-key.json', {'source': str(source), 'source_inventory': original, 'cases': cases})
    return cases, original


def execute_case(case, config, output):
    import paths
    import agent_tools
    import diagnostic_tools as diagnostic
    from assistant import TOOLS
    from ai_run import run
    from skill_manager import SkillManager
    identity = case['id']
    paths.set_game_dir(case['root'])  # This subprocess only; never saves global settings.
    config = dict(config, ai_run_timeout_seconds=180, ai_run_context_chars=24000,
                  ai_cloud_tool_log=True)
    journal = []
    allowed = {'list_instances', 'list_mods', 'read_instance_log', 'read_crash_report',
               'inspect_mod_jar', 'snapshot_instance', 'list_instance_snapshots',
               'compare_instance_snapshot', 'set_mod_enabled', 'observe_game'}
    schemas = [tool for tool in TOOLS if tool['function']['name'] in allowed]
    snapshotted = False

    def executor(name, arguments):
        nonlocal snapshotted
        if name not in allowed or (name != 'list_instances' and arguments.get('instance') != identity):
            raise ValueError('Tool or instance outside this isolated test scope')
        if name == 'set_mod_enabled' and (not case['allowed_write'] or not snapshotted):
            raise ValueError('Writes require repair authorization and a completed snapshot')
        module = agent_tools if name in {'list_instances', 'list_mods', 'read_instance_log', 'read_crash_report'} else diagnostic
        result = getattr(module, name)(**arguments)
        if name == 'snapshot_instance':
            snapshotted = True
        journal.append({'name': name, 'arguments': arguments, 'result': result})
        print(identity, len(journal), name, flush=True)
        return result

    hints = '\n'.join(SkillManager(None, config).ai_hints())
    system = ('你是启动器助手。以下是独立静态检查副本，未提供可启动核心和共享资源。'
              '只使用提供的工具，不读取其他实例，不发起下载或启动。没有实际运行证据时明确未验证启动。\n' + hints)
    user = (f'请检查实例 {identity} 中现有 Mod 的静态问题，保持 Minecraft 1.21.1 / NeoForge、'
            '现有功能及用户配置不变。没有证据不要臆造故障。')
    if case['allowed_write']:
        user += ('授权你先创建快照，再做有证据且不损失功能的可逆修复；无法安全修的列出证据。'
                 '重复副本可以禁用多余的一份，其他 Mod 不得为消除报错而禁用。不要再要求我确认已授权步骤。')
    else:
        user += '本轮只诊断，不修改文件。'
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
    if case['mode'] == 'resume':
        # Genuine old read-only observation; no fabricated game success/log evidence.
        old = agent_tools.list_mods(identity)
        messages += [
            {'role': 'assistant', 'content': '之前只列了文件，还没有检查或修改。',
             'tool_calls': [{'id': 'old_read', 'type': 'function', 'function': {'name': 'list_mods',
                             'arguments': json.dumps({'instance': identity})}}]},
            {'role': 'tool', 'tool_call_id': 'old_read', 'content': (old + '\n') * 1600},
            {'role': 'user', 'content': '继续完成刚才的检查与已授权修复。'}]
    started = time.monotonic()
    reply = ''
    error = None
    try:
        reply = run(messages, config, schemas, executor, max_tokens=4096)
    except Exception as exc:
        # Exclude URLs/credentials from report exceptions.
        error = type(exc).__name__
    folder = Path(case['root']) / 'versions' / identity
    after = diagnostic._inventory(str(folder))
    active = sorted((folder / 'mods').glob('*.jar'))
    preserved = all(after.get(key) == value for key, value in case['before'].items() if not key.startswith('mods' + os.sep))
    inspected = {call['arguments']['filename']: json.loads(call['result']) for call in journal if call['name'] == 'inspect_mod_jar'}
    checked_all = {'render-core.jar'} <= inspected.keys()
    if case['mode'] not in ('control', 'dependency_middle'):
        checked_all = checked_all and 'render-support.jar' in inspected
    if case['allowed_write']:
        resolved = (len(active) == 1 and digest(active[0]) == case['original_jar_sha256'] and
                    len(list((folder / 'mods').glob('*.jar.disabled'))) == 1 and snapshotted)
    else:
        resolved = after == case['before']
    result = {'id': identity, 'case': case['mode'], 'elapsed_seconds': round(time.monotonic()-started, 2),
              'tool_calls': len(journal), 'error': error, 'inspected_all_jars': checked_all,
              'protected_files_preserved': preserved, 'expected_disk_state': resolved,
              'mechanical_checks_pass': bool(not error and checked_all and preserved and resolved),
              'launch_verification': 'not_run_static_fixture', 'reply': reply, 'calls': journal}
    if case['mode'] == 'dependency_middle':
        result['mentions_injected_dependency'] = 'benchmark_support' in reply
        result['mechanical_checks_pass'] = result['mechanical_checks_pass'] and result['mentions_injected_dependency']
    write(output / identity / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--cases', nargs='+', choices=['control', 'duplicate', 'loader_mismatch', 'resume', 'dependency_middle'],
                        default=['control', 'duplicate', 'loader_mismatch', 'resume'])
    args = parser.parse_args()
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError('Output must be new; previous test runs are immutable')
    output.mkdir(parents=True)
    from settings import load_settings
    config = load_settings()
    if not config.get('version_isolation', True):
        raise ValueError('Enable instance isolation before executing this benchmark')
    cases, original = prepare(source, output, args.cases)
    results = []
    if args.execute:
        # Read only the configured API credentials; do not copy them to fixture configs.
        import paths
        from urllib.parse import urlsplit
        if config.get('ai_provider') in ('local_builtin', 'ollama', 'lmstudio'):
            raise ValueError('This runner requires the configured cloud tool provider')
        paths.data_dir = lambda sub='': str(output / 'run-records' / sub)
        import ai_run
        ai_run.data_dir = paths.data_dir
        for case in cases:
            results.append(execute_case(case, config, output))
        import diagnostic_tools
        unchanged = diagnostic_tools._inventory(str(source)) == original
        write(output / 'summary.json', {'model': config.get('ai_model'),
              'provider_host': urlsplit(config.get('ai_base_url', '')).hostname,
              'source_unchanged': unchanged, 'results': [{k: v for k, v in row.items() if k != 'calls'} for row in results]})
        print(json.dumps({'source_unchanged': unchanged, 'checks': [r['mechanical_checks_pass'] for r in results]}), flush=True)
        if not unchanged:
            raise RuntimeError('Source changed during testing; inspect for external writes')
    print('Output:', output, flush=True)


if __name__ == '__main__':
    main()
