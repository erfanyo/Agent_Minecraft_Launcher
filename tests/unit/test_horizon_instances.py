from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from launcher_app.instances import horizon
from launcher_app.instances.instance_install_service import InstanceInstallService
from launcher_app.instances.instance_metadata import rename_instance
from launcher_app.instances.instances import scan_instances
from launcher_app.instances.install_requests import InstanceCreateJob
from launcher_app.instances.launch_preparation import LaunchRequest


NIGHTLY = 'nightly-2026-11-19-f00125f'
RELEASE = 'v2026.10.19.11'


def test_horizon_builds_are_shared_and_pin_changes_preserve_worlds(tmp_path, monkeypatch):
    program = tmp_path / 'horizon-launcher.exe'
    program.touch()
    game_root = tmp_path / 'game'
    provider = horizon.HorizonLauncher(game_root, str(program))
    installed = []
    attempts = []
    fail_release = True

    def cli(*args, **_options):
        if args == ('versions', '--installed'):
            return {'installed': installed}
        if args == ('account', 'list'):
            return {'owner': True}
        operation, tag = args
        assert operation == 'install'
        attempts.append(tag)
        if tag == RELEASE and fail_release:
            raise RuntimeError('download failed')
        installed.append(tag)
        return {'installed': tag}

    monkeypatch.setattr(horizon.HorizonLauncher, '_json', lambda _self, *args, **kw: cli(*args, **kw))
    status, progress = Mock(), Mock()
    job = InstanceCreateJob({'edition': 'horizon', 'version': NIGHTLY, 'horizon_launcher_path': str(program)},
                            game_root, version_isolation=False)
    identity = job.run(status, progress)
    second = job.run(status, progress)
    assert identity != second
    assert attempts == [NIGHTLY]
    folder = game_root / 'versions' / identity
    (folder / 'saves').mkdir()
    (folder / 'saves' / 'world.dat').write_text('world', encoding='utf-8')
    with pytest.raises(RuntimeError, match='download failed'):
        provider.install(RELEASE, status, progress, identity)
    assert {row['base'] for row in scan_instances(game_root)} == {NIGHTLY}

    fail_release = False
    provider.install(RELEASE, status, progress, identity)
    rename_instance(game_root, identity, 'Rust World')
    by_id = {row['id']: row for row in scan_instances(game_root)}
    instance = by_id['Rust World']
    assert instance['edition'] == 'horizon' and instance['base'] == RELEASE
    assert by_id[second]['base'] == NIGHTLY
    folder = game_root / 'versions' / 'Rust World'
    assert (folder / 'saves' / 'world.dat').read_text(encoding='utf-8') == 'world'
    assert InstanceInstallService(lambda: game_root, lambda: False).game_dir_for('Rust World') == str(folder)
    request = LaunchRequest.capture(instance, {'horizon_launcher_path': str(program)}, game_root, 'unused')
    plan = request.prepare()
    assert plan.command == [str(program), 'play', '--instance', 'horizon', '--version', RELEASE]
    assert plan.java_exe is None and not plan.first_run
    assert plan.environment['HORIZON_HOME'] == str(folder)
    assert plan.environment['HORIZON_LAUNCHER_HOME'] == str(game_root / '_horizon' / 'launcher')


def test_catalog_uses_platform_availability_and_keeps_installed_builds_offline(tmp_path, monkeypatch):
    program = tmp_path / 'horizon-launcher'
    program.touch()
    provider = horizon.HorizonLauncher(tmp_path, str(program))
    responses = iter([
        SimpleNamespace(returncode=0, stdout=f'{{"installed":["{RELEASE}"]}}', stderr=''),
        SimpleNamespace(returncode=0, stdout=(f'[{{"tag":"{NIGHTLY}","available_here":true}},'
                                             '{"tag":"v0.0.1","available_here":false}]'), stderr=''),
        SimpleNamespace(returncode=0, stdout=f'{{"installed":["{RELEASE}"]}}', stderr=''),
        SimpleNamespace(returncode=1, stdout='', stderr='Network unavailable'),
    ])
    run = Mock(side_effect=lambda *_args, **_kw: next(responses))
    monkeypatch.setattr(horizon, 'run_process', run)
    assert provider.versions() == ([(NIGHTLY, False), (RELEASE, True)], '')
    rows, error = provider.versions()
    assert rows == [(RELEASE, True)]
    assert 'Network unavailable' in error
    assert run.call_args_list[0].args[0] == [str(program), '--json', 'versions', '--installed']
