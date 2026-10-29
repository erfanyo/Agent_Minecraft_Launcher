import json
from contextlib import contextmanager

import pytest

from launcher_app.resources import baidu_share, cloud_drives


def test_baidu_link_parses_passcode_and_ignores_ui_fragment():
    assert cloud_drives.parse_share('https://pan.baidu.com/s/1abc?pwd=nova#list/path=%2F') == ('baidu', '1abc', 'nova')


def test_baidu_visitor_verify_list_and_subfolder_mapping(monkeypatch):
    calls = []
    def request(session, path, form=None):
        calls.append((path, form))
        session.setdefault('visitor_cookies', {})
        if path.startswith('/s/'):
            return b'<html/>'
        if path.startswith('/share/verify'):
            return b'{"errno":0,"randsk":"secret%3D"}'
        return json.dumps({'errno': 0, 'list': [{'fs_id': '123', 'server_filename': 'Client',
                           'isdir': '1', 'size': '0', 'path': '/share/Client'}]}).encode()
    monkeypatch.setattr(baidu_share, '_request', request)
    session = {'share': '1abc', 'password': 'nova'}
    rows = baidu_share.list_files(session, '0', 1)
    assert rows[0]['dir'] is True
    assert session['visitor_cookies']['BDCLND'] == 'secret%3D'
    assert calls[1][1]['pwd'] == 'nova'
    assert 'surl=abc' in calls[1][0]
    assert all('app_id' not in p for p, _ in calls)
    baidu_share.list_files(session, '123', 2)
    assert 'dir=%2Fshare%2FClient' in calls[-1][0]
    assert 'page=2' in calls[-1][0]


def test_baidu_redirect_never_sends_guest_cookie_to_foreign_host(monkeypatch):
    class Reply:
        status = 302
        def getheaders(self): return []
        def getheader(self, name): return 'https://foreign.example/steal'
    @contextmanager
    def response(*args, **kwargs): yield Reply()
    monkeypatch.setattr(baidu_share, 'response', response)
    with pytest.raises(ValueError, match='外部'):
        baidu_share._request({'share': '1abc'}, '/s/1abc')


def test_raw_value_errors_are_not_sent_to_model():
    def fail(): raise ValueError('private-cookie-or-signed-download-url')
    assert 'private-cookie' not in cloud_drives.tool_result(fail)


def test_baidu_guest_failure_is_a_handoff_not_a_fake_download(monkeypatch):
    monkeypatch.setattr(cloud_drives, '_credential', lambda provider: '')
    def unavailable(*args, **kwargs):
        raise cloud_drives.CloudDriveError('请先登录', 'login_required')
    monkeypatch.setattr(baidu_share, '_json', unavailable)
    with pytest.raises(cloud_drives.CloudDriveError) as error:
        baidu_share.download_link({'share': '1abc', 'baidu_verified': True}, '12')
    assert error.value.state == 'login_required'


def test_baidu_download_uses_only_site_issued_signature_and_scoped_file(monkeypatch):
    monkeypatch.setattr(cloud_drives, '_credential', lambda provider: 'BDUSS=user-session')
    calls = []
    def request(session, path, form=None):
        calls.append((path, form))
        if path.startswith('/share/tplconfig'):
            return {'errno': 0, 'data': {'sign': 'site-sign-1234', 'timestamp': 12345678}}
        return {'errno': 0, 'list': [{'dlink': 'https://cdn.example.test/file?private=signature'}]}
    monkeypatch.setattr(baidu_share, '_json', request)
    session = {'share': '1abc', 'baidu_verified': True, 'baidu_share_id': '10',
               'baidu_owner_id': '20', 'visitor_cookies': {'BDCLND': 'share-secret%3D'}}
    assert baidu_share.download_link(session, '12').startswith('https://cdn.example.test/')
    assert len(calls) == 2
    assert all('app_id' not in path for path, _ in calls)
    assert 'surl=1abc' in calls[0][0]
    assert calls[1][1]['fid_list'] == '[12]'
    assert json.loads(calls[1][1]['extra'])['sekey'] == 'share-secret='


def test_baidu_bad_signature_does_not_send_download_request(monkeypatch):
    monkeypatch.setattr(cloud_drives, '_credential', lambda provider: 'BDUSS=user-session')
    calls = []
    def request(*args):
        calls.append(args)
        return {'data': {'sign': '<script>', 'timestamp': 123}}
    monkeypatch.setattr(baidu_share, '_json', request)
    with pytest.raises(cloud_drives.CloudDriveError):
        baidu_share.download_link({'share': '1abc', 'baidu_verified': True}, '12')
    assert len(calls) == 1
