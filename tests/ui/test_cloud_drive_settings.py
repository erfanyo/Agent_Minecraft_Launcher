import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLineEdit

from launcher_app.resources import cloud_drives as drive
from launcher_app.ui.cloud_drive_settings import connection_section, credentials_dialog

pytestmark = pytest.mark.ui


def test_credential_handoff_is_native_and_memory_only(qtbot, monkeypatch):
    drive._credentials.clear()
    section = connection_section()
    qtbot.addWidget(section)
    def enter():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QDialog)
        edit = dialog.findChild(QLineEdit)
        assert edit.echoMode() == QLineEdit.EchoMode.Password
        edit.setText('test-private-cookie')
        dialog.findChild(QDialogButtonBox).accepted.emit()
    QTimer.singleShot(0, enter)
    credentials_dialog(section)
    assert drive._credential('quark') == 'test-private-cookie'
    drive._credentials.clear()


def test_cancel_does_not_store_pasted_credential(qtbot):
    drive._credentials.clear()
    section = connection_section()
    qtbot.addWidget(section)
    def cancel():
        dialog = QApplication.activeModalWidget()
        dialog.findChild(QLineEdit).setText('never-store-this')
        dialog.reject()
    QTimer.singleShot(0, cancel)
    credentials_dialog(section)
    assert not drive._credential('quark')
