import json
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import pytest

from launcher_app.resources import cloud_drives as drive
from launcher_app.resources import cloud_drive_http as transport


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr('launcher_app.resources.antivirus.scan_available_archive', lambda path: {'status': 'not_run_in_test'})
    drive._sessions.clear()
    drive._credentials.clear()
    yield
    drive._sessions.clear()
    drive._credentials.clear()


@pytest.mark.parametrize('url,provider,key,code', [
    ('https://pan.quark.cn/s/abc?pwd=1234', 'quark', 'abc', '1234'),
    ('https://www.123pan.com/s/aaa-bbb.html', '123', 'aaa-bbb', ''),
    ('https://1848479766.share.123pan.cn/123pan/bvdAvd-PiNPh', '123', 'bvdAvd-PiNPh', '')])
def test_share_formats(url, provider, key, code):
    assert drive.parse_share(url) == (provider, key, code)


@pytest.mark.parametrize('url', ['https://127.0.0.1/s/a', 'https://pan.quark.cn.evil.com/s/a',
                                 'file:///s/a', 'https://u:p@pan.quark.cn/s/a',
                                 'https://pan.quark.cn:8888/s/a'])
def test_reject_foreign_or_local_urls(url):
    with pytest.raises(ValueError):
        drive.parse_share(url)


def quark_api(session, path, params=None, payload=None):
    if path.endswith('token'):
        return {'stoken': 'private-share-token'}
    if path.endswith('detail'):
        return {'list': [{'fid': 'folder', 'file_name': '客户端', 'dir': True},
                         {'fid': 'archive', 'file_name': 'pack.zip', 'size': 0,
                          'share_fid_token': 'private-file-token', 'file': True}]}
    if path == 'file/download':
        return [{'download_url': 'https://cdn.example.test/file?secret=signed-private'}]
    raise AssertionError(path)


def test_directory_scope_paging_and_no_tokens_returned(monkeypatch):
    monkeypatch.setattr(drive, '_api', quark_api)
    result = drive.browse('https://pan.quark.cn/s/a')
    assert result['items'][0]['directory']
    assert result['items'][1]['archive']
    assert 'private' not in json.dumps(result)
    assert drive.browse(session_id=result['session_id'], folder_id='folder')['status'] == 'listed'
    with pytest.raises(ValueError):
        drive.browse(session_id=result['session_id'], folder_id='foreign')
    with pytest.raises(ValueError):
        drive.browse(session_id=result['session_id'], page=0)


def test_123_directory_fields(monkeypatch):
    monkeypatch.setattr(drive, '_api', lambda *args, **kwargs: {'InfoList': [
        {'FileId': 1, 'FileName': 'server', 'Type': 1, 'Size': 0},
        {'FileId': 2, 'FileName': 'server.zip', 'Type': 0, 'Size': 123}]})
    result = drive.browse('https://www.123pan.com/s/a-b')
    assert result['items'][0]['directory']
    assert result['items'][1]['size'] == 123


def test_credentials_only_sent_to_provider_api(monkeypatch):
    drive.set_credential('quark', 'private-cookie')
    drive.set_credential('123', 'private-auth')
    call = Mock(return_value={})
    monkeypatch.setattr(transport, 'api', call)
    drive._api({'provider': 'quark'}, 'share/sharepage/token', payload={})
    assert call.call_args.kwargs['cookie'] == 'private-cookie'
    assert 'bearer' not in call.call_args.kwargs
    drive._api({'provider': '123'}, 'share/get')
    assert call.call_args.kwargs['bearer'] == 'private-auth'
    assert 'cookie' not in call.call_args.kwargs


@pytest.mark.parametrize('valid', [True, False])
def test_download_keeps_original_without_import_and_hides_link(tmp_path, monkeypatch, valid):
    monkeypatch.setattr(drive, '_api', quark_api)
    result = drive.browse('https://pan.quark.cn/s/a')
    def download(url, destination, **kwargs):
        if valid:
            with zipfile.ZipFile(destination, 'w') as archive:
                archive.writestr('mods/demo.txt', 'sample')
        else:
            with zipfile.ZipFile(destination, 'w') as archive:
                archive.writestr('../outside.txt', 'unsafe')
        return Path(destination).stat().st_size
    monkeypatch.setattr(transport, 'download', download)
    saved = drive.receive(result['session_id'], 'archive', str(tmp_path))
    assert saved['status'] == ('downloaded' if valid else 'scan_rejected')
    assert Path(saved['path']).is_file()
    assert 'signed-private' not in json.dumps(saved)
    assert not list(tmp_path.rglob('*.part'))
    assert not (tmp_path / 'versions').exists()


def test_incomplete_download_does_not_publish_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(drive, '_api', quark_api)
    result = drive.browse('https://pan.quark.cn/s/a')
    def download(url, destination, **kwargs):
        Path(destination).write_bytes(b'partial')
        raise OSError('signed URL and private data')
    monkeypatch.setattr(transport, 'download', download)
    output = drive.tool_result(lambda: drive.receive(result['session_id'], 'archive', str(tmp_path)))
    assert 'signed URL' not in output
    assert not list(tmp_path.rglob('*.zip'))
    assert not list(tmp_path.rglob('*.part'))


def test_expired_session_requires_reopen(monkeypatch, tmp_path):
    monkeypatch.setattr(drive, '_api', quark_api)
    result = drive.browse('https://pan.quark.cn/s/a')
    drive._sessions[result['session_id']]['created'] = time.monotonic() - drive.TTL - 1
    with pytest.raises(ValueError):
        drive.receive(result['session_id'], 'archive', str(tmp_path))


def test_tools_remain_available_after_user_login_followup(monkeypatch):
    from launcher_app.ai.assistant import mount_tools_for
    monkeypatch.setattr(drive, '_api', quark_api)
    drive.browse('https://pan.quark.cn/s/a')
    names = {t['function']['name'] for t in mount_tools_for('已登录，继续')}
    assert not {'browse_cloud_share', 'download_cloud_archive'} & names


def test_download_redirect_drops_credentials_and_checks_length(tmp_path, monkeypatch):
    calls = []
    class Reply:
        status = 302
        def getheader(self, name): return 'https://other.example.test/data' if name == 'Location' else None
    class FileReply:
        status = 200
        def __init__(self): self.data = [b'zip-bytes', b'']
        def getheader(self, name): return '9' if name == 'Content-Length' else None
        def read(self, size): return self.data.pop(0)
    @contextmanager
    def response(url, **kwargs):
        calls.append(kwargs)
        yield Reply() if len(calls) == 1 else FileReply()
    monkeypatch.setattr(transport, 'response', response)
    assert transport.download('https://drive-pc.quark.cn/start', str(tmp_path / 'a.part'),
                              cookie='secret', cookie_host='drive-pc.quark.cn', expected_size=9) == 9
    assert calls[0]['cookie'] == 'secret'
    assert calls[1]['cookie'] == ''


def test_model_tools_mounted_and_write_requires_confirmation():
    from launcher_app.ai.assistant import mount_tools_for, WRITE_TOOLS, CONFIRM_TOOLS
    from launcher_app.ai.ai_actions import ALWAYS_CONFIRM_ACTIONS
    names = {t['function']['name'] for t in mount_tools_for('从夸克网盘下载整合包并安装到实例')}
    assert not {'browse_cloud_share', 'download_cloud_archive'} & names
    assert 'ask_user' in names
    assert 'download_cloud_archive' in WRITE_TOOLS & CONFIRM_TOOLS & ALWAYS_CONFIRM_ACTIONS


def test_json_download_dispatch_is_followed_without_publishing_json(tmp_path, monkeypatch):
    class Reply:
        status = 200
        def getheader(self, name):
            return 'application/json' if name == 'Content-Type' else None
        def read(self, size):
            return b'{"data":{"redirect_url":"https://cdn.example.test/file"}}'
    class FileReply:
        status = 200
        def getheader(self, name): return 'application/zip' if name == 'Content-Type' else None
        def __init__(self): self.chunks = [b'zip-content', b'']
        def read(self, size): return self.chunks.pop(0)
    calls = []
    @contextmanager
    def response(url, **kwargs):
        calls.append(url)
        yield Reply() if len(calls) == 1 else FileReply()
    monkeypatch.setattr(transport, 'response', response)
    destination = tmp_path / 'file.part'
    transport.download('https://www.123pan.com/dispatch', str(destination))
    assert destination.read_bytes() == b'zip-content'
    assert calls[-1] == 'https://cdn.example.test/file'


def test_html_cannot_be_published_as_original_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(drive, '_api', quark_api)
    result = drive.browse('https://pan.quark.cn/s/a')
    def download(url, destination, **kwargs):
        Path(destination).write_text('<html>login</html>')
        return 18
    monkeypatch.setattr(transport, 'download', download)
    with pytest.raises(ValueError, match='ZIP/MRPACK'):
        drive.receive(result['session_id'], 'archive', str(tmp_path))
    assert not list(tmp_path.rglob('*.zip'))
    receipt = json.loads(next(tmp_path.rglob('download.json')).read_text(encoding='utf-8'))
    assert receipt['status'] == 'incomplete'
    assert 'signed-private' not in json.dumps(receipt)
