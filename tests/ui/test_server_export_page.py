import pytest
from PySide6.QtWidgets import QPushButton
from server_pack_builder_ui import ServerPackBuilderDialog

pytestmark = pytest.mark.ui


def page(hub, tmp_path, qtbot):
    source = tmp_path / 'instance'
    source.mkdir()
    dialog = ServerPackBuilderDialog(instance_id='模拟 Fabric 实例', instance_dir=str(source),
        game_dir=str(tmp_path / 'game'), minecraft='1.21.1', loader='fabric', loader_version='0.19.5')
    qtbot.addWidget(dialog)
    task = hub.begin_task('导出服务端', page=dialog, cancel=dialog._cancel_or_close)
    hub.update_task(task, state='idle')
    hub.show_task(task)
    return dialog, task


def test_prepared_export_waits_and_continues_same_page(hub, tmp_path, qtbot, monkeypatch):
    dialog, task = page(hub, tmp_path, qtbot)
    calls = []
    monkeypatch.setattr(dialog, '_import_for_test', calls.append)
    prepared = {'report': {'mods': []}, 'folder': str(tmp_path / 'prepared')}
    dialog._finished(prepared)
    assert hub.tabs.count() == 1
    assert calls == []
    assert hub.card.isVisible()
    hub.card.findChild(QPushButton, 'task_confirmation_choice_0').click()
    assert calls == [prepared] and hub.tasks[task].page is dialog


def test_cancel_prepared_confirmation_does_not_start_or_package(hub, tmp_path, qtbot, monkeypatch):
    dialog, task = page(hub, tmp_path, qtbot)
    calls = []
    monkeypatch.setattr(dialog, '_import_for_test', lambda _: calls.append('test'))
    monkeypatch.setattr(dialog, '_package_prepared', lambda *a, **k: calls.append('package'))
    dialog._finished({'report': {'mods': []}, 'folder': str(tmp_path / 'prepared')})
    dialog._cancel_or_close()
    assert calls == []
    assert hub.tasks[task].state == 'cancelled'


def test_hide_export_page_keeps_task_alive(hub, tmp_path, qtbot):
    dialog, task = page(hub, tmp_path, qtbot)
    hub.update_task(task, state='running')
    dialog.reject()
    assert hub.tasks[task].state == 'running'
    assert not hub.details.isVisible()
    hub.show_task(task)
    assert dialog.isVisible()
