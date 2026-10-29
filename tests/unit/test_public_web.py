from email.message import Message
import json
import time
from unittest.mock import Mock, patch

import pytest
from launcher_app.browser import public_web as web


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://127.0.0.1/', 'http://[::1]/',
    'https://user:pass@www.bilibili.com/', 'https://www.bilibili.com:8080/',
    'https://bilibili.com.evil.example/', 'https://evil.example/',
    'https://www.bilibili.com/?token=secret', 'https://www.bilibili.com/\r\nX:bad'])
def test_rejects_unauthorized_url_before_network(url):
    with patch.object(web.socket, 'getaddrinfo') as dns:
        result = web.read_public_webpage(url, {})
    assert '未读取' in result
    dns.assert_not_called()


@pytest.mark.parametrize('ip', ['127.0.0.1', '10.0.0.1', '192.168.1.1', '169.254.169.254',
    '100.64.0.1', '::1', 'fc00::1', '::ffff:127.0.0.1', '2002:7f00:1::', '64:ff9b::7f00:1'])
def test_dns_rebinding_and_private_resolution_are_rejected(ip):
    with patch.object(web.socket, 'getaddrinfo', return_value=[(0, 0, 0, '', (ip, 443))]), \
         patch.object(web.socket, 'create_connection') as connect:
        with pytest.raises(ValueError):
            web.request_once('https://www.bilibili.com/', ['bilibili.com'], time.monotonic() + 10)
    connect.assert_not_called()


def test_mixed_public_and_private_dns_is_rejected():
    rows = [(0, 0, 0, '', (ip, 443)) for ip in ('8.8.8.8', '127.0.0.1')]
    with patch.object(web.socket, 'getaddrinfo', return_value=rows):
        with pytest.raises(ValueError):
            web.resolve_public('www.bilibili.com', 443)


def test_redirect_destination_is_checked_before_request():
    headers = Message()
    headers['Location'] = 'http://127.0.0.1/admin'
    with patch.object(web, 'request_once', return_value=(302, headers, b'')) as request:
        with pytest.raises(ValueError):
            web.fetch('http://b23.tv/example', ['b23.tv', 'bilibili.com'])
    assert request.call_count == 1


def test_tls_pins_checked_address_but_verifies_original_hostname():
    headers = Message()
    headers['Content-Type'] = 'text/plain; charset=utf-8'
    connection = Mock()
    connection.getresponse.return_value.headers = headers
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.side_effect = [b'hello', b'']
    context = Mock()
    transport = Mock()
    context.wrap_socket.return_value = transport
    with patch.object(web, 'resolve_public', return_value='8.8.8.8'), \
         patch.object(web.socket, 'create_connection') as connect, \
         patch.object(web.ssl, 'create_default_context', return_value=context), \
         patch.object(web.http.client, 'HTTPSConnection', return_value=connection):
        _, _, body = web.request_once('https://www.bilibili.com/test', ['bilibili.com'], time.monotonic() + 10)
    assert body == b'hello'
    assert connect.call_args.args[0] == ('8.8.8.8', 443)
    assert context.wrap_socket.call_args.kwargs['server_hostname'] == 'www.bilibili.com'
    sent = connection.request.call_args
    assert sent.args[:2] == ('GET', '/test')
    assert 'Cookie' not in sent.kwargs['headers'] and 'Authorization' not in sent.kwargs['headers']
    connection.close.assert_called_once()


@pytest.mark.parametrize('field,value', [('Content-Length', '1048577'),
    ('Content-Encoding', 'gzip'), ('Content-Type', 'application/octet-stream')])
def test_response_limits_fail_closed(field, value):
    headers = Message()
    headers['Content-Type'] = 'text/plain'
    if field in headers:
        del headers[field]
    headers[field] = value
    conn = Mock()
    conn.getresponse.return_value.headers = headers
    conn.getresponse.return_value.status = 200
    with patch.object(web, 'resolve_public', return_value='8.8.8.8'), \
         patch.object(web.socket, 'create_connection'), \
         patch.object(web.http.client, 'HTTPConnection', return_value=conn):
        with pytest.raises(ValueError):
            web.request_once('http://b23.tv/a', ['b23.tv'], time.monotonic() + 10)
    conn.getresponse.return_value.read.assert_not_called()


def test_bilibili_metadata_is_available_without_browser():
    data = json.dumps({'code': 0, 'data': {'title': '地下酒吧', 'desc': '作者公开下载说明',
                      'owner': {'name': '作者', 'mid': 123}, 'pubdate': 1}})
    with patch.object(web, 'fetch', return_value=('https://api.bilibili.com/example', 200, 'application/json', data)):
        result = json.loads(web.read_public_webpage('https://www.bilibili.com/video/BV17auR6GEWR/', {}))
    assert result['description'] == '作者公开下载说明'
    assert result['author']['uid'] == 123 and result['trust']


def test_metadata_failure_falls_back_to_html_and_excludes_scripts():
    html = '<title>视频</title><meta name="description" content="简介"><script>stealSecrets()</script><p>正文</p>'
    with patch.object(web, 'fetch', side_effect=[OSError(), ('https://www.bilibili.com/video/BV1/', 200, 'text/html', html)]):
        result = json.loads(web.read_public_webpage('https://www.bilibili.com/video/BV1/', {}))
    assert result['description'] == '简介' and 'stealSecrets' not in result['text']


def test_tool_mount_and_domain_permissions_cannot_be_changed_by_model():
    from launcher_app.ai.assistant import mount_tools_for
    from launcher_app.ai.agent_tools import set_setting
    tools = mount_tools_for('帮我看 https://www.bilibili.com/video/BV1/ 的简介和下载链接', {})
    assert any(t['function']['name'] == 'read_public_webpage' for t in tools)
    assert '只能由用户' in set_setting('ai_web_allowed_domains', 'evil.example')
