"""Exercise the real worker/event-loop boundary without Java, accounts or network."""
import threading
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QTimer, QThread
from launcher_app.runtime.launch_preparation_controller import LaunchPreparationController

pytestmark = pytest.mark.ui


def request(work):
    return SimpleNamespace(game_root='games', version={'id': 'one'}, prepare=work)


def test_preparation_reports_progress_on_gui_and_does_not_block(qapp, qtbot):
    release = threading.Event()
    threads, delivered, ticks, statuses, progress = [], [], [], [], []
    def work(status_cb, progress_cb):
        threads.append(QThread.currentThread())
        status_cb('preparing')
        progress_cb(2**33, 2**34)
        assert release.wait(3)
        return 'plan'
    controller = LaunchPreparationController(lambda: 'games')
    controller.prepared.connect(lambda *args: delivered.append((args, QThread.currentThread())))
    controller.status.connect(statuses.append)
    controller.progress.connect(lambda *args: progress.append(args))
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start(5)
    task = controller.create_task(request(work))
    task.start()
    try:
        qtbot.waitUntil(lambda: len(ticks) >= 3 and bool(progress))
    finally:
        release.set()
        timer.stop()
    qtbot.waitUntil(lambda: not controller.busy)
    assert threads[0] != qapp.thread()
    assert delivered == [(('plan', {'id': 'one'}), qapp.thread())]
    assert statuses == ['preparing']
    assert progress == [(2**33, 2**34)]


def test_directory_change_rejects_plan(qtbot):
    current = ['games']
    controller = LaunchPreparationController(lambda: current[0])
    plans, errors = [], []
    controller.prepared.connect(lambda *args: plans.append(args))
    controller.failed.connect(errors.append)
    task = controller.create_task(request(lambda **kwargs: 'stale-plan'))
    current[0] = 'other-games'
    task.start()
    qtbot.waitUntil(lambda: not controller.busy)
    assert not plans
    assert errors == ['游戏目录已经变了，请重新点击启动']


def test_cancelled_late_result_cannot_start_game(qtbot):
    controller = LaunchPreparationController(lambda: 'games')
    plans, cancellations = [], []
    controller.prepared.connect(lambda *args: plans.append(args))
    controller.cancelled.connect(lambda: cancellations.append(True))
    task = controller.create_task(request(lambda **kwargs: 'plan'))
    task.start()
    task._thread.join(2)  # Queue success, deliberately don't deliver GUI events yet.
    assert not task._thread.is_alive()
    controller.cancel()
    qtbot.waitUntil(lambda: not controller.busy)
    assert plans == []
    assert cancellations == [True]


def test_busy_failure_and_retry_lifecycle(qtbot):
    controller = LaunchPreparationController(lambda: 'games')
    errors, plans = [], []
    controller.failed.connect(errors.append)
    controller.prepared.connect(lambda *args: plans.append(args))
    def fail(**kwargs):
        raise RuntimeError('fixture failure')
    task = controller.create_task(request(fail))
    with pytest.raises(RuntimeError):
        controller.create_task(request(fail))
    task.start()
    qtbot.waitUntil(lambda: not controller.busy)
    assert errors == ['RuntimeError: fixture failure']
    controller.create_task(request(lambda **kwargs: 'retry-plan')).start()
    qtbot.waitUntil(lambda: not controller.busy)
    assert plans == [('retry-plan', {'id': 'one'})]
