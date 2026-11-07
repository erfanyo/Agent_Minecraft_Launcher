"""A launch preparation uses captured configuration and scoped credential writes."""
from unittest.mock import patch
from launcher_app.instances.launch_preparation import LaunchRequest


def test_capture_freezes_nested_settings_and_version():
    version = {'id': 'one', 'nested': {'value': 'old'}}
    settings = {'version_isolation': True, 'java_paths': {'17': 'old-java'}}
    request = LaunchRequest.capture(version, settings, 'games', 'runtime')
    version['nested']['value'] = 'new'
    settings['java_paths']['17'] = 'new-java'
    settings['version_isolation'] = False
    assert request.version['nested']['value'] == 'old'
    assert request.settings['java_paths']['17'] == 'old-java'
    assert request.game_dir_for('one').replace('\\', '/') == 'games/versions/one'


def test_shared_directory_and_callback_contract():
    request = LaunchRequest.capture({'id': 'one'}, {}, 'games', 'runtime')
    statuses, progress = [], []
    with patch('launcher_app.instances.launch_preparation.GameLaunchService') as factory:
        factory.return_value.prepare.return_value = 'plan'
        assert request.prepare(statuses.append, progress.append) == 'plan'
        roots, runtime, settings, save, game_dir = factory.call_args.args
        assert roots() == 'games'
        assert runtime() == 'runtime'
        assert settings() == {}
        assert game_dir('one') == 'games'
        kwargs = factory.return_value.prepare.call_args.kwargs
        assert kwargs['status_cb'] == statuses.append
        assert kwargs['progress_cb'] == progress.append


def test_refresh_updates_only_the_preparing_identity():
    written = []
    request = LaunchRequest.capture({'id': 'one'}, {'ms_credentials': {'uuid': 'player-one'}}, 'games', 'runtime')
    with patch('launcher_app.instances.launch_preparation.GameLaunchService') as factory:
        request.prepare(credentials_writer=lambda identity, credentials: written.append((identity, credentials)))
        save = factory.call_args.args[3]
        save({'ms_credentials': {'uuid': 'player-one', 'access_token': 'test-token'}, 'unrelated': 'must-not-save'})
    assert written == [('player-one', {'uuid': 'player-one', 'access_token': 'test-token'})]
