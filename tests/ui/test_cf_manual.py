from unittest.mock import patch
from tests.unit.test_cf_pack_import import records


def test_complete_files_resume_without_button_click(tmp_path):
    from launcher_app.resources.cf_manual import show_missing_dialog, write_missing_report, REPORT_NAME
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog
    app = QApplication.instance() or QApplication([])
    instance, downloads = tmp_path/'instance', tmp_path/'downloads'
    instance.mkdir(); downloads.mkdir()
    (downloads/'example.jar').write_bytes(b'ok')
    entry, file, project = records()
    write_missing_report(str(instance), [(entry, 'offline')], {20: file}, {10: project})
    parent = QDialog()
    retried = []
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(lambda: [dialog.reject() for dialog in parent.findChildren(QDialog)])
    deadline.start(2500)
    with patch('PySide6.QtCore.QStandardPaths.writableLocation', return_value=str(downloads)):
        show_missing_dialog(parent, f'[CF_MISSING_REPORT]{instance/REPORT_NAME}[/CF_MISSING_REPORT]',
                            lambda: retried.append(True))
    deadline.stop()
    app.processEvents()
    assert retried == [True]
    assert (downloads/'example.jar').exists()
    parent.deleteLater()


def test_missing_dialog_receives_download_and_retries(tmp_path):
    from launcher_app.resources.cf_manual import show_missing_dialog, write_missing_report, REPORT_NAME
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton
    app = QApplication.instance() or QApplication([])
    instance, downloads = tmp_path / 'instance', tmp_path / 'downloads'
    instance.mkdir()
    downloads.mkdir()
    (downloads / 'example.jar').write_bytes(b'ok')
    entry, file, project = records()
    write_missing_report(str(instance), [(entry, 'offline')], {20: file}, {10: project})
    parent = QDialog()
    retried = []
    poll = QTimer()
    def click():
        for dialog in parent.findChildren(QDialog):
            for button in dialog.findChildren(QPushButton):
                if button.text() in ('检查并接收下载文件', '已补齐，继续安装') and button.isEnabled():
                    button.click()
    poll.timeout.connect(click)
    poll.start(20)
    def timeout():
        for dialog in parent.findChildren(QDialog):
            dialog.reject()
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(timeout)
    deadline.start(2000)
    with patch('PySide6.QtCore.QStandardPaths.writableLocation', return_value=str(downloads)):
        show_missing_dialog(parent, f'[CF_MISSING_REPORT]{instance / REPORT_NAME}[/CF_MISSING_REPORT]',
                            lambda: retried.append(True))
    poll.stop()
    deadline.stop()
    app.processEvents()
    assert (instance / 'mods' / 'example.jar').read_bytes() == b'ok'
    assert retried == [True]
    parent.deleteLater()
