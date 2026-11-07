"""Running-game state independent of widgets and real desktop processes."""
from types import SimpleNamespace
import psutil
from launcher_app.runtime.running_games import RunningGames


def registry(visible, times=None):
    return RunningGames(windows=True, pid_exists=lambda pid: True,
                        visible_window=lambda pid: pid in visible,
                        create_time=lambda pid: (times or {}).get(pid, 1))


def test_loading_counts_until_window_has_been_seen_then_closed():
    visible = set()
    games = registry(visible)
    games.register(10, 'one')
    process = SimpleNamespace(pid=10)
    assert games.live([process]) == {10: 'one'}
    visible.add(10)
    assert games.live([process]) == {10: 'one'}
    visible.clear()
    assert games.live([process]) == {}


def test_detected_child_replaces_owned_windowless_wrapper():
    games = registry({20})
    games.register(10, 'one')
    games.set_detected([{'id': 'one', 'pid': 20, 'parent_pids': [10], 'window_visible': True}])
    assert games.live([SimpleNamespace(pid=10)]) == {20: 'one'}


def test_reused_external_pid_is_not_reported_as_old_game():
    games = registry({30}, {30: 2})
    games.set_detected([{'id': 'external', 'pid': 30, 'create_time': 1}])
    assert games.live([]) == {}


def test_external_identity_and_owned_duplicate_keep_single_entry():
    games = registry({10, 20})
    games.register(10, 'one')
    games.set_detected([{'id': 'one', 'pid': 10}, {'id': 'external', 'pid': 20}])
    assert games.live([SimpleNamespace(pid=10)]) == {10: 'one', 20: 'external'}


def test_process_disappears_during_detection():
    def disappeared(pid):
        raise psutil.NoSuchProcess(pid)
    games = RunningGames(windows=False, create_time=disappeared, pid_exists=lambda pid: False)
    games.register(10, 'one')
    games.set_detected([{'id': 'external', 'pid': 20}])
    assert games.live([SimpleNamespace(pid=10)]) == {}


def test_new_owned_launch_with_reused_pid_resets_window_history():
    visible = {10}
    games = registry(visible)
    games.register(10, 'old')
    games.live([SimpleNamespace(pid=10)])
    visible.clear()
    games.register(10, 'new')
    assert games.live([SimpleNamespace(pid=10)]) == {10: 'new'}
