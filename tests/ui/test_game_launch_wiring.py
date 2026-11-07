"""Exercise the window launch adapter with isolated runtime ports, no real game."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PySide6.QtWidgets import QMainWindow
from launcher_app.runtime.game_runtime import GameRuntime
from main import MainWindow

pytestmark=pytest.mark.ui


def test_window_uses_runtime_context_and_preserves_process_after_failed_multilaunch(qtbot):
    owner=QMainWindow();qtbot.addWidget(owner)
    owner.settings={'ai_in_game':'off'}
    owner.log_view=Mock();owner.dl_indicator=Mock();owner.launch_btn=Mock();owner.ai_focus_sidebar=Mock()
    owner._start_launch_button_animation=Mock();owner._show_launch_button_success=Mock();owner._stop_launch_button_animation=Mock()
    owner._update_running_label=Mock();owner._running_instances=set();owner.ai_context=lambda:'snapshot'
    integrations=Mock();owner._game_integrations=lambda:integrations
    sessions=Mock();sessions.start.return_value=SimpleNamespace(pid=123)
    runtime=GameRuntime(sessions,Mock(),Mock(),track=Mock())
    owner._game_runtime=lambda:runtime
    plan=SimpleNamespace(command=['java','Main'],java_exe='java',game_dir='captured-dir',game_root='captured-root',
                         detail={'id':'runtime-id'},first_run=False)
    MainWindow._start_game_after_memory(owner,plan,{'id':'selected-id'})
    first=owner.game_process
    assert runtime.current.process is first
    integrations.started.assert_called_once_with(first,'selected-id',owner.settings,'captured-root','snapshot')
    sessions.start.side_effect=RuntimeError('second launch failed')
    MainWindow._start_game_after_memory(owner,plan,{'id':'second-id'})
    assert owner.game_process is first
    assert runtime.current.instance_id=='selected-id'
    assert integrations.started.call_count==1
    owner.dl_indicator.set_failed.assert_called_with(True)
