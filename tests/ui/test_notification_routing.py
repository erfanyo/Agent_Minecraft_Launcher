import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLineEdit, QPushButton, QMessageBox
from launcher_app.ui.ui_notifications import task_notice, task_warning, inline_notice, action_question

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def enable_policy(monkeypatch):
    monkeypatch.setattr('launcher_app.ui.ui_notifications.notifications_enabled', lambda: True)


def test_task_result_is_nonblocking_and_goes_to_hub(hub):
    task_notice(hub.parent(), '备份完成', '已保存世界备份。')
    assert hub.tabs.count() == 1
    record = next(iter(hub.tasks.values()))
    assert record.state == 'completed'
    assert '备份' in record.message
    assert not hub.card.isVisible()


def test_repeated_task_notice_reuses_tab(hub):
    task_notice(hub.parent(), '备份完成', '第一次')
    task_notice(hub.parent(), '备份完成', '第二次')
    assert hub.tabs.count() == 1
    assert '第二次' in next(iter(hub.tasks.values())).message


def test_task_warning_marks_failure(hub):
    task_warning(hub.parent(), '导出失败', '模拟错误')
    assert next(iter(hub.tasks.values())).state == 'failed'
    assert hub.ball._failed


def test_validation_stays_next_to_input(hub, qtbot):
    edit = QLineEdit(hub.parent())
    edit.setGeometry(100, 100, 250, 30)
    edit.show()
    prompt = inline_notice(hub.parent(), '名称不可用', '请输入另一个名称。', anchor=edit)
    assert prompt.parentWidget() is hub.parent()
    assert prompt.isVisible()
    assert hub.tasks == {} and hub.tabs.count() == 0
    assert hub.parent().rect().contains(prompt.geometry())


def test_immediate_confirmation_does_not_enter_task_queue(hub):
    def answer():
        prompt = hub.parent().findChild(type(hub.parent()), 'local_action_confirmation')
        assert prompt is not None
        prompt.findChild(QPushButton, 'local_action_choice_0').click()
    QTimer.singleShot(0, answer)
    result = action_question(hub.parent(), '确认删除', '删除这个模拟实例？')
    assert result == QMessageBox.StandardButton.Yes
    assert hub.tasks == {} and not hub._requests


def test_classic_policy_uses_native_popup(hub, monkeypatch):
    monkeypatch.setattr('launcher_app.ui.ui_notifications.notifications_enabled', lambda: False)
    calls = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: calls.append(args))
    task_notice(hub.parent(), '完成', '消息')
    assert len(calls) == 1 and hub.tasks == {}
