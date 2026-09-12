"""Prepare and launch an isolated real Minecraft baseline; never alter the source pack."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def prepare(root, source):
    if root.exists():
        raise ValueError('Use a new test directory; existing baselines are not overwritten')
    root.mkdir(parents=True)
    game = root / 'game'
    game.mkdir()
    print('Copying shared libraries into independent test storage', flush=True)
    shutil.copytree(source / 'libraries', game / 'libraries')
    # Reuse only 1.21.1 assets, no user worlds/configs or account files.
    index = json.loads((source / 'assets' / 'indexes' / '17.json').read_text(encoding='utf-8'))
    write(game / 'assets' / 'indexes' / '17.json', index)
    print('Copying assets', len(index['objects']), flush=True)
    for entry in index['objects'].values():
        relative = Path('assets', 'objects', entry['hash'][:2], entry['hash'])
        src, dst = source / relative, game / relative
        if src.is_file() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    base = game / 'versions' / '_versions' / '1.21.1'
    base.mkdir(parents=True)
    for extension in ('json', 'jar'):
        shutil.copy2(source / 'versions' / '1.21.1' / ('1.21.1.' + extension), base)
    os.environ['FORGE_PROCESSOR_JAVA'] = r'D:\programs\Java\jdk-21.0.12\bin\java.exe'
    from loaders import install_loader
    identity = install_loader('neoforge', '1.21.1', str(game), loader_version='21.1.250',
                              status_callback=lambda status: print(status, flush=True))
    folder = game / 'versions' / identity
    write(folder / 'amcl_instance.json', {'minecraft_version': '1.21.1', 'loader': 'neoforge',
                                        'loader_version': '21.1.250'})
    write(folder / 'launch_options.json', {'java_path': os.environ['FORGE_PROCESSOR_JAVA'], 'memory_gb': 4})
    (folder / 'options.txt').write_text('lang:en_us\nrenderDistance:6\nsimulationDistance:5\nmaxFps:60\n'
                                      'enableVsync:false\nfullscreen:false\n', encoding='utf-8')
    write(root / 'baseline.json', {'instance': identity, 'game_root': str(game),
                                 'minecraft': '1.21.1', 'neoforge': '21.1.250', 'java': 21,
                                 'verification': 'installed_not_launched'})
    print('Installed baseline:', identity, flush=True)


def launch(root, world=None, instance=None):
    import paths
    from settings import load_settings
    from game_launch_service import GameLaunchService
    from instances import scan_instances
    meta = json.loads((root / 'baseline.json').read_text(encoding='utf-8'))
    game = Path(meta['game_root'])
    identity = instance or meta['instance']
    from safe_paths import safe_component
    safe_component(identity)
    folder = game / 'versions' / identity
    paths.set_game_dir(str(game))  # Local to this runner process.
    config = copy.deepcopy(load_settings())
    # Use the cached signed-in session; do not rotate or persist account credentials in a benchmark.
    config.setdefault('ms_credentials', {}).pop('refresh_token', None)
    config['sync_minecraft_language'] = False
    config['jvm_args'] = ''
    service = GameLaunchService(lambda: str(game), lambda: str(game / 'runtime'), lambda: config,
                                lambda _: None, lambda _: str(folder))
    item = next(row for row in scan_instances(str(game)) if row['id'] == identity)
    plan = service.prepare(dict(item, local=True), status_cb=lambda text: print(text, flush=True))
    command = plan.command + ['--width', '960', '--height', '600']
    if world:
        if not (folder / 'saves' / world / 'level.dat').is_file():
            raise ValueError('Quick-play world does not exist in this test instance')
        command += ['--quickPlaySingleplayer', world]
    token = str(time.time_ns())
    logfile = root / ('launch-' + token + '.log')
    with open(logfile, 'wb') as output:
        process = subprocess.Popen(command, cwd=folder, stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    write(root / 'process.json', {'pid': process.pid, 'log': str(logfile), 'instance': identity,
                                 'started': time.time(), 'verification': 'not_verified'})
    print('Started test game PID', process.pid, flush=True)
    for _ in range(18):
        try:
            code = process.wait(timeout=5)
            print('Game exited:', code, flush=True)
            write(root / ('exit-' + token + '.json'), {'exit_code': code, 'log': str(logfile)})
            return
        except subprocess.TimeoutExpired:
            pass
    print('Test game still running after 90 seconds; verify its window/world before claiming success.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'launch'])
    parser.add_argument('--root', required=True)
    parser.add_argument('--source', default='.minecraft')
    parser.add_argument('--world')
    parser.add_argument('--instance')
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.action == 'prepare':
        prepare(root, Path(args.source).resolve())
    else:
        launch(root, args.world, args.instance)
