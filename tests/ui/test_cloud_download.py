from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QWidget

from launcher_app.resources.cloud_drive_errors import CloudDriveError
from launcher_app.ui.cloud_download import CloudDownloadDialog, extract_url

pytestmark = pytest.mark.ui


def listing(provider='quark', directory=False):
    return {'status': 'listed', 'provider': provider, 'session_id': 'session', 'page': 1,
            'folder_id': '0', 'has_more': False, 'items': [
                {'id': 'file1', 'name': 'client.zip', 'directory': directory, 'archive': not directory, 'size': 100}]}


@pytest.fixture
def dialog(qtbot, monkeypatch):
    monkeypatch.setattr('launcher_app.ui.optional_notices.antivirus_notice', lambda *args: None)
    host = QWidget()
    qtbot.addWidget(host)
    dialog = CloudDownloadDialog(host)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def open_listing(dialog, qtbot, monkeypatch):
    monkeypatch.setattr('launcher_app.resources.cloud_drives.browse', lambda *args, **kwargs: listing())
    dialog.url.setText('https://pan.quark.cn/s/demo')
    dialog.open_share()
    qtbot.waitUntil(lambda: dialog.listing_valid and not dialog.busy())
    dialog.files.setCurrentItem(dialog.files.topLevelItem(0))


def test_logged_out_download_retains_selection_then_can_retry(dialog, qtbot, monkeypatch, tmp_path):
    open_listing(dialog, qtbot, monkeypatch)
    def needs_login(*args):
        raise CloudDriveError('请先登录，原选择保留', 'login_required')
    monkeypatch.setattr('launcher_app.resources.cloud_drives.receive', needs_login)
    dialog.download_selected()
    qtbot.waitUntil(lambda: '请先登录' in dialog.status.text() and not dialog.busy())
    assert dialog.selected()['id'] == 'file1'
    assert dialog.download.isEnabled()
    assert dialog.connect.isEnabled()
    assert dialog.original is None
    assert not dialog.install.isEnabled()
    original = tmp_path / 'client.zip'
    original.write_bytes(b'kept')
    monkeypatch.setattr('launcher_app.resources.cloud_drives.receive', lambda *args: {
        'status': 'downloaded', 'path': str(original), 'notice': '原包已保存',
        'review': {'kind': 'modpack-candidate', 'warnings': [], 'antivirus': {'status': 'not_requested'}}})
    dialog.download_selected()
    qtbot.waitUntil(lambda: dialog.original is not None and not dialog.busy())
    assert dialog.install.isEnabled()
    assert original.read_bytes() == b'kept'


def test_failed_new_share_cannot_download_old_listing(dialog, qtbot, monkeypatch):
    open_listing(dialog, qtbot, monkeypatch)
    def fail(*args, **kwargs):
        raise CloudDriveError('需要验证', 'captcha_required')
    monkeypatch.setattr('launcher_app.resources.cloud_drives.browse', fail)
    dialog.url.setText('https://pan.baidu.com/s/1new?pwd=demo')
    dialog.open_share()
    qtbot.waitUntil(lambda: '需要验证' in dialog.status.text() and not dialog.busy())
    assert not dialog.download.isEnabled()
    assert not dialog.files.isEnabled()
    assert dialog.provider == 'baidu'
    assert dialog.connect.isEnabled()
    assert dialog.browser.isEnabled()


@pytest.mark.parametrize('status,kind,antivirus,enabled', [
    ('scan_rejected', 'modpack-candidate', '', False),
    ('downloaded', 'unknown-archive', '', False),
    ('downloaded', 'modpack-candidate', 'attention_required', False),
    ('downloaded', 'server-candidate', 'not_requested', True)])
def test_import_handoff_requires_recognized_checked_archive(dialog, status, kind, antivirus, enabled):
    dialog.show_received({'status': status, 'path': 'C:/kept/archive.zip',
        'review': {'kind': kind, 'warnings': [], 'antivirus': {'status': antivirus}}})
    assert dialog.install.isEnabled() == enabled
    assert dialog.folder.isEnabled()


def test_pasted_share_text_does_not_require_clean_url():
    assert extract_url('分享链接：https://pan.baidu.com/s/1abc?pwd=nova 提取码nova') == 'https://pan.baidu.com/s/1abc?pwd=nova'


def test_login_handoff_uses_current_provider(dialog, monkeypatch):
    dialog.provider = 'baidu'
    connect = Mock()
    monkeypatch.setattr('launcher_app.ui.cloud_drive_settings.credentials_dialog', connect)
    dialog.login()
    connect.assert_called_once_with(dialog, 'baidu')
    assert '不会自动授权' in dialog.status.text()
