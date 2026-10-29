"""Drive real widgets with fake work; wait on conditions/signals, not sleeps."""
import threading

import pytest
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import QPushButton
from launcher_app.ui.ui_tokens import set_theme_mode, current_token
from launcher_app.ui.ui_style import refresh_theme

pytestmark = pytest.mark.ui


class FakeWorker(QObject):
    status = Signal(str)
    progress = Signal(object, object)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled_signal = Signal()


def choose(hub, index=0):
    button = hub.card.findChild(QPushButton, f'task_confirmation_choice_{index}')
    assert button is not None and button.isEnabled()
    button.click()


def test_two_tasks_keep_separate_progress_and_tabs(hub):
    first = hub.begin_task('下载资源')
    second = hub.begin_task('导出服务端')
    hub.update_task(first, done=1, total=4)
    hub.update_task(second, done=3, total=10)
    assert hub.tabs.count() == 2
    assert hub.tasks[first].view['progress'].value() == 250
    assert hub.tasks[second].view['progress'].value() == 300
    assert hub.ball._task_summary[:2] == (2, 0)


def test_only_answered_task_continues(hub):
    first = hub.begin_task('第一项')
    second = hub.begin_task('第二项')
    answers = []
    hub.request_confirmation(first, '问题一', '开始测试？', [('开始', True)],
                             lambda value: answers.append((first, value)))
    hub.request_confirmation(second, '问题二', '删除副本？', [('删除', True), ('保留', False)],
                             lambda value: answers.append((second, value)))
    assert hub.ball._task_summary[:2] == (0, 2)
    choose(hub)
    assert answers == [(first, True)]
    assert hub.question.text() == '删除副本？'
    choose(hub, 1)
    assert answers == [(first, True), (second, False)]
    assert not hub.card.isVisible()
    assert hub.ball.isVisible()


def test_collapse_and_reopen_does_not_answer(hub, qtbot):
    task = hub.begin_task('导出')
    answers = []
    hub.request_confirmation(task, '是否测试', '开始？', [('开始', True)], answers.append)
    qtbot.mouseClick(hub.ball, Qt.MouseButton.LeftButton)
    assert not hub.card.isVisible() and hub.ball.isVisible()
    assert answers == []
    qtbot.mouseClick(hub.ball, Qt.MouseButton.LeftButton)
    assert hub.card.isVisible() and answers == []
    assert hub.question.text() == '开始？'


def test_clicking_launcher_collapses_without_losing_question(hub, qtbot):
    task = hub.begin_task('任务')
    answers = []
    hub.request_confirmation(task, '确认', '继续？', [('继续', True)], answers.append)
    qtbot.mouseClick(hub.ball.parentWidget(), Qt.MouseButton.LeftButton)
    assert not hub.card.isVisible() and hub.ball.isVisible()
    hub.present()
    assert hub.card.isVisible() and answers == []


def test_enter_does_not_confirm(hub, qtbot):
    task = hub.begin_task('任务')
    answers = []
    hub.request_confirmation(task, '确认', '继续？', [('继续', True)], answers.append)
    qtbot.keyClick(hub.question, Qt.Key.Key_Return)
    assert answers == []


def test_cancel_waiting_calls_none_once(hub):
    task = hub.begin_task('任务')
    answers = []
    hub.request_confirmation(task, '确认', '继续？', [('继续', True)], answers.append)
    assert hub.cancel_confirmation(task)
    assert answers == [None]
    assert not hub.cancel_confirmation(task)
    assert answers == [None]


def test_closing_details_does_not_cancel_work(hub):
    cancelled = []
    task = hub.begin_task('任务', cancel=lambda: cancelled.append(True))
    hub.show_task(task)
    hub.details.close()
    assert not hub.details.isVisible()
    assert hub.tasks[task].state == 'running' and cancelled == []
    hub.cancel_task(task)
    assert cancelled == [True]


def test_worker_results_and_retry(hub):
    task = hub.begin_task('任务', task_id='fixed')
    worker = FakeWorker()
    hub.attach_background(worker, task)
    worker.status.emit('准备文件')
    worker.progress.emit(3 * 1024**3, 4 * 1024**3)
    assert hub.tasks[task].view['progress'].value() == 750
    worker.failed.emit('模拟失败')
    assert hub.tasks[task].state == 'failed' and hub.ball._failed
    assert hub.begin_task('重试', task_id=task) == task
    assert hub.tabs.count() == 1
    hub.attach_background(worker, task)
    assert hub.tasks[task].total == 0
    worker.succeeded.emit(None)
    assert hub.tasks[task].state == 'completed' and hub.ball._completed


def test_workflow_phase_success_is_not_overall_success(hub):
    task = hub.begin_task('导出')
    worker = FakeWorker()
    hub.attach_background(worker, task, finish=False)
    worker.succeeded.emit({'prepared': True})
    assert hub.tasks[task].state == 'running'
    hub.finish_task(task)
    assert hub.tasks[task].state == 'completed'


def test_download_controller_forwards_large_byte_counters(hub, qtbot):
    from launcher_app.core.task_controllers import DownloadTaskController
    controller = DownloadTaskController(hub)
    progress = []
    controller.progress.connect(lambda done, total: progress.append((done, total)))
    def worker(status, report):
        report(3 * 1024**3, 4 * 1024**3)
        return True
    with qtbot.waitSignal(controller.completed, timeout=3000):
        assert controller.start(worker)
    assert controller.state == 'success'
    assert progress == [(3 * 1024**3, 4 * 1024**3)]


def test_report_marshals_worker_thread_updates(hub, qtbot):
    task = hub.begin_task('任务')
    thread = threading.Thread(target=lambda: hub.report(task, message='后台进度', done=2, total=5))
    thread.start()
    thread.join(timeout=2)
    qtbot.waitUntil(lambda: hub.tasks[task].message == '后台进度')
    assert hub.tasks[task].view['progress'].value() == 400


@pytest.mark.parametrize('mode', ['dark', 'light'])
def test_theme_switch_updates_existing_windows_and_progress(hub, mode):
    task = hub.begin_task('主题测试')
    set_theme_mode('dark' if mode == 'light' else 'light')
    refresh_theme()
    set_theme_mode(mode)
    refresh_theme()
    assert current_token('bg0') in hub.card.styleSheet()
    assert current_token('bg1') in hub.tasks[task].view['progress'].styleSheet()


def test_shutdown_releases_all_pending_requests(hub):
    task = hub.begin_task('任务')
    answers = []
    hub.request_confirmation(task, '确认', '继续？', [('继续', True)], answers.append)
    hub.shutdown()
    hub.shutdown()
    assert answers == [None]


def test_confirmation_position_is_clamped_to_screen(hub):
    task = hub.begin_task('任务')
    hub.card._placed = True
    hub.card.move(-10000, -10000)
    hub.request_confirmation(task, '确认', '继续？', [('继续', True)], lambda _: None)
    area = hub.card.screen().availableGeometry()
    assert area.contains(hub.card.geometry())


def test_drag_confirmation_keeps_question_and_position(hub, qtbot, monkeypatch):
    from PySide6.QtCore import QPoint
    task = hub.begin_task('拖动测试')
    answers = []
    hub.request_confirmation(task, '确认', '继续？', [('继续', True)], answers.append)
    monkeypatch.setattr(hub.card.windowHandle(), 'startSystemMove', lambda: False)
    header = hub.card.header
    original = hub.card.pos()
    # The initial card is at the lower/right screen edge on small DPI-scaled
    # screens. Drag inward rather than testing a correctly clamped outward move.
    qtbot.mousePress(header, Qt.MouseButton.LeftButton, pos=QPoint(40, 10))
    qtbot.mouseMove(header, QPoint(10, 5))
    qtbot.mouseRelease(header, Qt.MouseButton.LeftButton, pos=QPoint(10, 5))
    assert hub.card.pos() != original
    position = hub.card.pos()
    hub.card.hide()
    hub.present()
    assert hub.card.pos() == position and answers == []


def test_confirmation_callback_can_queue_next_question(hub):
    task = hub.begin_task('连续流程')
    answers = []
    def first(value):
        answers.append(value)
        hub.request_confirmation(task, '第二步', '继续打包？', [('打包', True)], answers.append)
    hub.request_confirmation(task, '第一步', '开始测试？', [('测试', True)], first)
    choose(hub)
    assert hub.question.text() == '继续打包？' and hub.card.isVisible()
    choose(hub)
    assert answers == [True, True]


def test_long_confirmation_remains_scrollable_and_on_screen(hub, qtbot):
    from PySide6.QtWidgets import QScrollArea
    task = hub.begin_task('长提示')
    hub.request_confirmation(task, '确认', '较长的说明内容，请核对。\n' * 150,
                             [('确认', True)], lambda _: None)
    scroll = hub.card.findChild(QScrollArea)
    qtbot.waitUntil(lambda: scroll.verticalScrollBar().maximum() > 0)
    assert hub.card.screen().availableGeometry().contains(hub.card.geometry())


def test_details_fits_available_screen(hub):
    task = hub.begin_task('小屏幕')
    area = hub.details.screen().availableGeometry()
    hub.details.resize(area.width() + 300, area.height() + 300)
    hub.show_task(task)
    assert area.contains(hub.details.geometry())


def test_closing_active_tab_does_not_cancel_and_can_reopen(hub):
    cancelled = []
    task = hub.begin_task('工作中', cancel=lambda: cancelled.append(True))
    hub.show_task(task)
    hub.tabs.tabCloseRequested.emit(0)
    assert hub.tabs.count() == 0 and cancelled == []
    assert hub.tasks[task].state == 'running'
    hub.present()
    assert hub.tabs.count() == 1


def test_closed_completed_tab_does_not_reappear_automatically(hub):
    task = hub.begin_task('完成的任务')
    hub.finish_task(task)
    hub.tabs.tabCloseRequested.emit(0)
    hub.present()
    assert hub.tabs.count() == 0


@pytest.mark.parametrize('x,y', [(0, 0), (400, 0), (800, 0), (0, 320),
                                   (400, 320), (800, 320), (0, 620), (400, 620), (800, 620)])
def test_expansion_positions_avoid_ball_and_stay_in_main_window(hub, x, y):
    from PySide6.QtCore import QPoint, QRect
    owner = hub.parent()
    hub.ball.move(x, y)
    task = hub.begin_task('位置测试')
    hub.show_task(task)
    main = QRect(owner.mapToGlobal(QPoint(0, 0)), owner.size())
    sphere = QRect(hub.ball.mapToGlobal(QPoint(0, 0)), hub.ball.size())
    assert main.contains(hub.details.geometry())
    assert not sphere.intersects(hub.details.geometry())


def test_collapse_fades_after_half_and_restores_opacity(hub, qtbot):
    from launcher_app.ui.ui_anim import set_animations_enabled
    from PySide6.QtCore import QAbstractAnimation
    set_animations_enabled(True)
    task = hub.begin_task('动画测试')
    hub.show_task(task)
    qtbot.waitUntil(lambda: hub.details._animation.state() == QAbstractAnimation.State.Stopped)
    frames = []
    hub.details._animation.valueChanged.connect(lambda _: frames.append(
        (hub.details._animation.currentTime(), hub.details.windowOpacity())))
    with qtbot.waitSignal(hub.details._animation.finished, timeout=2000):
        hub.present()
    assert any(time > 90 and 0 < opacity < 1 for time, opacity in frames)
    assert not hub.details.isVisible() and hub.details.windowOpacity() == 1
    hub.show_task(task)
    qtbot.waitUntil(lambda: hub.details._animation.state() == QAbstractAnimation.State.Stopped)
    assert hub.details.isVisible() and hub.details.windowOpacity() == 1


@pytest.mark.parametrize('window_name', ['details', 'card'])
def test_minimizing_owner_hides_tools_and_preserves_pending_work(hub, qtbot, window_name):
    answers, cancelled = [], []
    task = hub.begin_task('最小化测试', cancel=lambda: cancelled.append(True))
    if window_name == 'card':
        hub.request_confirmation(task, '确认', '继续？', [('继续', True)], answers.append)
    else:
        hub.show_task(task)
    tool = getattr(hub, window_name)
    assert tool.parentWidget() is hub.owner
    assert tool.isVisible()
    hub.owner.showMinimized()
    qtbot.waitUntil(lambda: not tool.isVisible())
    assert answers == [] and cancelled == []
    assert hub.tasks[task].state == 'running'
    hub.owner.showNormal()
    qtbot.waitUntil(lambda: hub.owner.isVisible() and not hub.owner.isMinimized())
    hub.present()
    assert tool.isVisible()
    assert answers == [] and cancelled == []


def test_new_confirmation_stays_queued_while_owner_minimized(hub, qtbot):
    hub.owner.showMinimized()
    answers = []
    task = hub.begin_task('后台确认')
    hub.request_confirmation(task, '确认', '继续？', [('继续', True)], answers.append)
    assert not hub.card.isVisible()
    assert len(hub._requests) == 1 and answers == []
    hub.owner.showNormal()
    hub.present()
    assert hub.card.isVisible()
    choose(hub)
    assert answers == [True]


@pytest.mark.parametrize('window_name', ['details', 'card'])
def test_ball_hides_tool_without_cancelling(hub, qtbot, window_name):
    answers, cancelled = [], []
    task = hub.begin_task('收起测试', cancel=lambda: cancelled.append(True))
    if window_name == 'card':
        hub.request_confirmation(task, '确认', '继续？', [('继续', True)], answers.append)
    else:
        hub.show_task(task)
    tool = getattr(hub, window_name)
    qtbot.mouseClick(hub.ball, Qt.MouseButton.LeftButton)
    assert not tool.isVisible()
    assert cancelled == [] and answers == []
    hub.present()
    assert tool.isVisible()


def test_owner_hide_interrupts_animation_and_restores_geometry(hub, qtbot):
    from launcher_app.ui.ui_anim import set_animations_enabled
    from PySide6.QtCore import QVariantAnimation
    set_animations_enabled(True)
    task = hub.begin_task('动画测试')
    hub.show_task(task)
    target = hub.details._expanded_geometry
    assert hub.details._animation.state() == QVariantAnimation.State.Running
    hub.owner.hide()
    assert not hub.details.isVisible()
    assert hub.details._animation.state() == QVariantAnimation.State.Stopped
    assert hub.details.geometry() == target
    assert hub.details.windowOpacity() == 1.0
