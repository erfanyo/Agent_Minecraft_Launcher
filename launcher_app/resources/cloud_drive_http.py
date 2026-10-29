"""Pinned public HTTPS transport for built-in cloud-drive adapters.

No caller-supplied headers, no environment proxy/auth, no automatic redirects.
"""
from launcher_app.resources.cloud_drive_errors import CloudDriveError
import http.client
import json
import socket
import ssl
import time
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit, urljoin, urlencode

from launcher_app.browser.public_web import resolve_public
from launcher_app.core.task_context import checkpoint


@contextmanager
def response(url, *, method='GET', payload=None, form=None, cookie='', bearer='', referer='', download_service=''):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in (None, 443) or len(url) > 16384
            or any(ord(c) < 33 for c in url)):
        raise CloudDriveError('网盘只接受公共 HTTPS 地址')
    ip = resolve_public(parsed.hostname, 443)
    connection = http.client.HTTPSConnection(parsed.hostname, timeout=15)
    sock = socket.create_connection((ip, 443), timeout=15)
    connection.sock = sock
    try:
        connection.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
        headers = {'User-Agent': 'pan.baidu.com' if download_service == 'baidu' else 'Mozilla/5.0 AMCL/1.0',
                   'Accept-Encoding': 'identity'}
        if parsed.hostname == 'yun.123pan.com':
            headers.update({'platform': 'web', 'app-version': '3'})
        for key, value in [('Cookie', cookie), ('Authorization', 'Bearer ' + bearer if bearer else ''),
                           ('Referer', referer)]:
            if '\r' in value or '\n' in value:
                raise CloudDriveError('网盘凭证格式无效')
            if value:
                headers[key] = value
        body = None
        if payload is not None:
            body = json.dumps(payload).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        if form is not None:
            if payload is not None:
                raise CloudDriveError('请求体类型冲突')
            body = urlencode(form).encode('utf-8')
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        checkpoint()
        connection.request(method, urlunsplit(('', '', parsed.path or '/', parsed.query, '')), body, headers)
        reply = connection.getresponse()
        yield reply
    finally:
        connection.close()


def api(url, *, payload=None, cookie='', bearer='', referer=''):
    with response(url, method='POST' if payload is not None else 'GET', payload=payload,
                  cookie=cookie, bearer=bearer, referer=referer) as reply:
        data = reply.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise CloudDriveError('网盘目录响应过大，请缩小范围')
        try:
            result = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            raise CloudDriveError(f'网盘接口 HTTP {reply.status} 未返回目录数据，可能需要登录、验证或接口已变化') from None
        if not isinstance(result, dict):
            raise CloudDriveError('网盘接口响应格式已变化')
        code = result.get('code')
        if str(code) in ('31001', '401', '40101'):
            raise CloudDriveError(f'需要网盘登录（业务码 {code}）；请在本机连接窗口完成登录接续', 'login_required')
        if str(code) == '23018':
            raise CloudDriveError('文件超过游客下载限制（业务码 23018），请先在本机连接窗口提供登录凭证', 'login_required')
        if str(code) == '5112':
            raise CloudDriveError('123 云盘未放行匿名下载（业务码 5112）；请先登录重试。该通用提示不能证明分享者设置了付费，不会自动付费', 'login_required')
        if code not in (0, '0'):
            # Never relay server messages/URLs that may embed credentials.
            safe_code = str(code) if str(code).lstrip('-').isdigit() and len(str(code)) <= 12 else '未知'
            raise CloudDriveError(f'网盘未放行（业务码 {safe_code}）；请在浏览器检查提取码、登录或验证码后重试')
        if reply.status != 200:
            raise CloudDriveError(f'网盘接口 HTTP {reply.status}；请检查登录、访问限制或稍后重试')
        return result.get('data')


def download(url, destination, *, expected_size=0, cookie='', cookie_host='', referer='', progress=None, service=''):
    """Download API-issued URL only. Strip credentials at every foreign redirect."""
    max_bytes = 8 * 1024**3
    total = 0
    deadline = time.monotonic() + 3600
    for hop in range(6):
        checkpoint()
        host = urlsplit(url).hostname
        with response(url, cookie=cookie if host == cookie_host else '', referer=referer, download_service=service) as reply:
            if reply.status in (301, 302, 303, 307, 308):
                location = reply.getheader('Location')
                if not location:
                    raise CloudDriveError('下载跳转缺少目标')
                url = urljoin(url, location)
                continue
            if reply.status != 200:
                raise CloudDriveError(f'下载 HTTP {reply.status}；可能需要重新登录或下载地址已过期')
            content_type = (reply.getheader('Content-Type') or '').split(';')[0].lower()
            if content_type == 'application/json':
                # Some 123 download dispatchers return a JSON redirect instead
                # of an HTTP redirect. It is not archive content.
                body = reply.read(65537)
                if len(body) > 65536:
                    raise CloudDriveError('下载中间响应过大，未作为文件接收')
                try:
                    message = json.loads(body)
                    target = message.get('data', {}).get('redirect_url')
                except (ValueError, AttributeError):
                    target = None
                if not isinstance(target, str) or not target.startswith('https://'):
                    raise CloudDriveError('网盘返回状态信息而非文件，请检查登录或下载权限')
                url = target
                continue
            if content_type in ('text/html', 'application/xhtml+xml'):
                raise CloudDriveError('网盘返回登录或验证页面，未作为整合包接收')
            length = reply.getheader('Content-Length')
            length = int(length) if length else 0
            if length > max_bytes or expected_size > max_bytes:
                raise CloudDriveError('整合包超过当前 8 GiB 接收上限')
            with open(destination, 'xb') as output:
                while True:
                    checkpoint()
                    if time.monotonic() > deadline:
                        raise TimeoutError('下载超时，原任务可重新获取链接后重试')
                    chunk = reply.read(256 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise CloudDriveError('整合包超过当前 8 GiB 接收上限')
                    output.write(chunk)
                    if progress:
                        progress(total, expected_size or length)
            if (length and total != length) or (expected_size and total != expected_size):
                raise CloudDriveError('下载长度不完整，未作为成功文件接收')
            return total
    raise CloudDriveError('网盘下载跳转次数过多')
