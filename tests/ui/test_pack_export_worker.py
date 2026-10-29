import zipfile
import pytest
from launcher_app.resources.export_modpack import PackExportDialog

pytestmark = pytest.mark.ui


@pytest.mark.parametrize('format', ['zip', 'curseforge', 'mrpack'])
def test_export_runs_in_worker_and_reports_to_status_ball(hub, qtbot, tmp_path, monkeypatch, format):
    monkeypatch.setattr('launcher_app.ui.ui_notifications.notifications_enabled', lambda: True)
    source = tmp_path / 'instance'
    (source / 'config').mkdir(parents=True)
    file = source / 'config/example.txt'
    file.write_text('sample config')
    dialog = PackExportDialog('测试实例', str(source), base='1.21.1', loader='fabric', loader_version='0.19.5')
    qtbot.addWidget(dialog)
    output = tmp_path / ('output.mrpack' if format == 'mrpack' else 'output.zip')
    dialog.out_edit.setText(str(output))
    dialog.fmt_combo.setCurrentIndex(dialog.fmt_combo.findData(format))
    monkeypatch.setattr(dialog, '_selected_files', lambda: [(str(file), 'config/example.txt')])
    dialog._do_export()
    task_id = dialog._status_task_id
    qtbot.waitUntil(lambda: hub.tasks[task_id].state in ('completed', 'failed'), timeout=5000)
    assert hub.tasks[task_id].state == 'completed', hub.tasks[task_id].message
    with zipfile.ZipFile(output) as archive:
        assert any(name.endswith('config/example.txt') for name in archive.namelist())
    assert file.read_text() == 'sample config'


def test_existing_export_is_not_overwritten(hub, qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr('launcher_app.ui.ui_notifications.notifications_enabled', lambda: True)
    source = tmp_path / 'source'
    source.mkdir()
    dialog = PackExportDialog('实例', str(source))
    qtbot.addWidget(dialog)
    output = tmp_path / 'existing.zip'
    output.write_bytes(b'original')
    dialog.out_edit.setText(str(output))
    dialog.fmt_combo.setCurrentIndex(dialog.fmt_combo.findData('zip'))
    monkeypatch.setattr(dialog, '_selected_files', lambda: [('unused', 'config/file.txt')])
    dialog._do_export()
    assert output.read_bytes() == b'original'
    assert hub.tasks == {}
