import zipfile
import pytest
from PySide6.QtWidgets import QDialog
from launcher_app.ui.browser_downloads import BrowserDownloadInbox

pytestmark = pytest.mark.ui


def test_browser_assistance_dispatch_and_busy_fallback(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from launcher_app.ui.browser_downloads import request_download_assistance
    monkeypatch.setattr('PySide6.QtCore.QStandardPaths.writableLocation', lambda _: str(tmp_path))
    monkeypatch.setattr('settings.load_settings', lambda: {
        'browser_agent_enabled': True, 'browser_extension_token': 'local-test', 'ai_model': 'test'})
    prompts = []
    dock = SimpleNamespace(settings={'ai_model': 'test'}, _agent_running=False,
                           show=lambda: None, raise_=lambda: None)
    def ask(prompt):
        prompts.append(prompt)
        dock._agent_running = True
    dock.ask = ask
    host = SimpleNamespace(ai_dock=dock)
    dialog = BrowserDownloadInbox()
    qtbot.addWidget(dialog)
    assert request_download_assistance(host, 'https://pan.quark.cn/s/example', 'share', dialog)
    assert 'mcp__browser__' in prompts[0]
    assert 'ask_user' in prompts[0]
    assert '不自动绕过' in prompts[0]
    text = dialog.assistance.text()
    dialog.poll()
    assert dialog.assistance.text() == text  # polling cannot erase handoff instructions
    assert not request_download_assistance(host, 'https://pan.quark.cn/s/example', 'share', dialog)
    assert len(prompts) == 1
    dialog.reject()


def test_new_download_requires_selection_and_keeps_original(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr('PySide6.QtCore.QStandardPaths.writableLocation', lambda _: str(tmp_path))
    dialog = BrowserDownloadInbox()
    qtbot.addWidget(dialog)
    dialog.show()
    assert not dialog.install.isEnabled()
    original = tmp_path/'download.zip'
    with zipfile.ZipFile(original, 'w') as archive:
        archive.writestr('manifest.json', '{}')
    dialog.poll()
    qtbot.waitUntil(lambda: dialog.files.count() == 1)
    assert dialog.selected_path is None
    dialog.files.setCurrentRow(0)
    dialog.install.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.selected_path == str(original)
    assert original.exists()
    assert not dialog.timer.isActive()


def test_single_archive_is_received_automatically(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr('PySide6.QtCore.QStandardPaths.writableLocation', lambda _: str(tmp_path))
    dialog = BrowserDownloadInbox(automatic=True)
    qtbot.addWidget(dialog)
    dialog.show()
    original = tmp_path/'download.zip'
    with zipfile.ZipFile(original, 'w') as archive:
        archive.writestr('manifest.json', '{}')
    dialog.poll()
    qtbot.waitUntil(lambda: dialog.selected_path is not None)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert original.exists()


def test_cloud_link_starts_receiver_before_opening_browser(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from launcher_app.ui.browser_downloads import start_cloud_browser_import
    host = QWidget()
    qtbot.addWidget(host)
    imported, opened = [], []
    host.import_modpack = imported.append
    monkeypatch.setattr('PySide6.QtCore.QStandardPaths.writableLocation', lambda _: str(tmp_path))
    monkeypatch.setattr('PySide6.QtWidgets.QInputDialog.getText', lambda *a: (
        'https://pan.quark.cn/s/5f2b2a42c543?pwd=uYHL', True))
    def open_link(url):
        assert host._cloud_browser_inbox.timer.isActive()
        opened.append(url.toString())
        return True
    monkeypatch.setattr('PySide6.QtGui.QDesktopServices.openUrl', open_link)
    start_cloud_browser_import(host)
    original = tmp_path/'download.zip'
    with zipfile.ZipFile(original, 'w') as archive:
        archive.writestr('manifest.json', '{}')
    host._cloud_browser_inbox.poll()
    qtbot.waitUntil(lambda: bool(imported))
    assert opened and imported == [str(original)]
    assert original.exists()
