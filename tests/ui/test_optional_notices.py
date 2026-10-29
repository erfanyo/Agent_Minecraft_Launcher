import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from launcher_app.ui import optional_notices as notices
from launcher_app.ui.ui_switch import ToggleSwitch

pytestmark = pytest.mark.ui


def test_notice_can_be_suppressed_and_restored(monkeypatch):
    data = {'cloud_drive_defender_scan': False, 'third_party_plugins_enabled': False,
            'dismissed_notices': [], 'ignore_memory_launch_advice': True,
            'plugin_prompt_declined': ['example'], 'plugin_prompt_seen': ['example']}
    monkeypatch.setattr('settings.load_settings', lambda: dict(data))
    monkeypatch.setattr('settings.update_setting', lambda key, value: data.update({key: value}))
    monkeypatch.setattr('settings.save_settings', lambda value: data.update(value))
    def close():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        dialog.findChild(ToggleSwitch).setChecked(True)
        dialog.accept()
    QTimer.singleShot(0, close)
    notices.antivirus_notice(None, {'status': 'unavailable', 'message': '请手动扫描'})
    assert 'antivirus_unavailable' in data['dismissed_notices']
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: pytest.fail('suppressed notice opened'))
    notices.antivirus_notice(None, {'status': 'incomplete'})
    restored = notices.reset_optional_notices()
    assert restored['dismissed_notices'] == []
    assert restored['ignore_memory_launch_advice'] is False
    assert restored['plugin_prompt_declined'] == []
    assert restored['cloud_drive_defender_scan'] is False
    assert restored['third_party_plugins_enabled'] is False


def test_threat_alert_is_not_a_dismissible_notice(monkeypatch):
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: pytest.fail('alert became dismissible'))
    notices.antivirus_notice(None, {'status': 'attention_required'})
