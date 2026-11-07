"""Multi-launch routing with fake child processes; no real game is started."""
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QObject, Signal
from launcher_app.runtime.game_session_controller import GameSessionController

pytestmark = pytest.mark.ui


class FakeProcessController(QObject):
    line_received = Signal(str)
    exited = Signal(int)

    def __init__(self, parent):
        super().__init__(parent)
        self.process = None
        self.is_running = False
        self.detached = False
        self.fail = False

    def start(self, command, java, cwd, independent=False):
        if self.fail:
            raise RuntimeError('launch failed')
        self.process = SimpleNamespace(command=command, cwd=cwd, independent=independent)
        self.is_running = True
        return self.process

    def detach(self):
        self.detached = True


def test_second_game_routes_old_exit_separately(qapp):
    sessions = GameSessionController(controller_factory=FakeProcessController)
    lines, exits, background = [], [], []
    sessions.line_received.connect(lines.append)
    sessions.exited.connect(exits.append)
    sessions.background_exited.connect(lambda: background.append(True))
    first = sessions.start(['first'], 'java', 'one')
    old = sessions.controllers[0]
    second = sessions.start(['second'], 'java', 'two', independent=True)
    latest = sessions.controllers[1]
    old.line_received.emit('old log')
    latest.line_received.emit('current log')
    old.is_running = False
    old.exited.emit(1)
    assert lines == ['current log']
    assert exits == []
    assert background == [True]
    assert sessions.running_processes == (second,)
    assert second.independent
    latest.is_running = False
    latest.exited.emit(0)
    assert exits == [0]
    assert not sessions.running_processes


def test_failed_second_launch_keeps_original_log_routing(qapp):
    created = []
    def factory(parent):
        child = FakeProcessController(parent)
        child.fail = bool(created)
        created.append(child)
        return child
    sessions = GameSessionController(controller_factory=factory)
    lines = []
    sessions.line_received.connect(lines.append)
    first = sessions.start(['first'], 'java', 'one')
    with pytest.raises(RuntimeError):
        sessions.start(['second'], 'java', 'two')
    created[0].line_received.emit('original still running')
    assert lines == ['original still running']
    assert sessions.running_processes == (first,)
    assert len(sessions.controllers) == 1


def test_detach_all_games_without_terminating_them(qapp):
    sessions = GameSessionController(controller_factory=FakeProcessController)
    sessions.start(['one'], 'java', 'one')
    sessions.start(['two'], 'java', 'two')
    sessions.detach()
    assert len(sessions.running_processes) == 2
    assert all(child.detached for child in sessions.controllers)
