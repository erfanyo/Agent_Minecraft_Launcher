"""A failed launch must never replace the previous run or last-played metadata."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from launcher_app.runtime.game_runtime import GameRuntime


def plan():
    return SimpleNamespace(command=['java','Main'],java_exe='java',game_dir='launched-dir',
                           game_root='captured-root',detail={'id':'runtime-id'})


def test_start_captures_evidence_and_records_only_after_success():
    sessions,registry,remember,track=Mock(),Mock(),Mock(),Mock()
    sessions.start.return_value=SimpleNamespace(pid=10)
    runtime=GameRuntime(sessions,registry,remember,track=track,clock=lambda:123)
    settings={}
    launched=runtime.start(plan(),{'id':'selected-id'},'changed-root',independent=True)
    assert launched.game_root=='captured-root'
    assert launched.evidence.game_dir=='launched-dir' and launched.evidence.started_at==123
    assert launched.history_dir.replace('\\','/')=='captured-root/versions/selected-id'
    assert settings=={}
    remember.assert_not_called()
    registry.register.assert_called_once_with(10,'runtime-id')
    runtime.record_started(settings)
    assert settings['last_played_instance']=='selected-id'
    remember.assert_called_once_with('selected-id')
    track.assert_called_once_with(launched.process,launched.history_dir)


def test_failed_launch_keeps_previous_context_and_does_not_remember():
    sessions,registry,remember,track=Mock(),Mock(),Mock(),Mock()
    sessions.start.return_value=SimpleNamespace(pid=10)
    runtime=GameRuntime(sessions,registry,remember,track=track)
    first=runtime.start(plan(),{'id':'first'},'root')
    sessions.start.side_effect=RuntimeError('fixture failure')
    with pytest.raises(RuntimeError):
        runtime.start(plan(),{'id':'second'},'root')
    assert runtime.current is first
    remember.assert_not_called()
    assert registry.register.call_count==1


def test_last_played_write_failure_does_not_erase_started_game():
    sessions=Mock();sessions.start.return_value=SimpleNamespace(pid=10)
    runtime=GameRuntime(sessions,Mock(),Mock(side_effect=OSError('read only')),track=Mock())
    launched=runtime.start(plan(),{'id':'one'},'root')
    runtime.record_started({})
    assert runtime.current is launched
