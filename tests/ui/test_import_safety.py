import pytest
from PySide6.QtWidgets import QWidget, QMessageBox

from launcher_app.ui.import_safety import check_before_import

pytestmark = pytest.mark.ui


@pytest.mark.parametrize('state,answer,expected', [
    ('attention_required', QMessageBox.StandardButton.Yes, False),
    ('unavailable', QMessageBox.StandardButton.No, False),
    ('unavailable', QMessageBox.StandardButton.Yes, True),
])
def test_preflight_gates_import(qtbot, monkeypatch, state, answer, expected):
    window = QWidget()
    qtbot.addWidget(window)
    calls, warnings, notices = [], [], []
    monkeypatch.setattr('launcher_app.resources.import_safety.prepare_import', lambda *a, **k: {
        'path': 'prepared.zip', 'original': 'original.zip', 'layers': [],
        'antivirus': {'status': state, 'message': 'scan result'}})
    monkeypatch.setattr('settings.load_settings', lambda: {'cloud_drive_defender_scan': False})
    monkeypatch.setattr('launcher_app.ui.optional_notices.antivirus_notice',
                        lambda *a: notices.append(True))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: answer)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: warnings.append(True))
    check_before_import(window, 'original.zip', calls.append)
    qtbot.waitUntil(lambda: not window._import_safety_task.is_running)
    qtbot.wait(30)
    assert bool(calls) == expected
    assert bool(warnings) == (state == 'attention_required')
    assert bool(notices) == (state != 'attention_required')
