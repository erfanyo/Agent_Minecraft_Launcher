"""Baidu visitor share verification/listing, no borrowed application identity.

Only site-issued visitor cookies are retained in the in-memory share session.
Account authentication, CAPTCHA and download signatures remain user/browser work.
"""
from launcher_app.resources.cloud_drive_errors import CloudDriveError
import json
import re
from http.cookies import SimpleCookie
from urllib.parse import urlencode, urljoin, urlsplit, quote, unquote

from launcher_app.resources.cloud_drive_http import response

ORIGIN = 'https://pan.baidu.com'


def _request(session, path, form=None):
    url = ORIGIN + path
    jar = session.setdefault('visitor_cookies', {})
    from launcher_app.resources.cloud_drives import _credential
    supplied = SimpleCookie()
    supplied.load(_credential('baidu'))
    for hop in range(4):
        cookies = {k: m.value for k, m in supplied.items()}
        cookies.update(jar)
        with response(url, method='POST' if form is not None else 'GET', form=form,
                      cookie='; '.join(f'{k}={v}' for k, v in cookies.items()),
                      referer=ORIGIN + '/s/' + session['share']) as reply:
            for key, value in reply.getheaders():
                if key.lower() == 'set-cookie':
                    cookies = SimpleCookie()
                    cookies.load(value)
                    # Explicit visitor names; no login cookies harvested.
                    for name in ('PANPSC', 'BAIDUID', 'csrfToken', 'BDCLND'):
                        if name in cookies:
                            jar[name] = cookies[name].value
            if reply.status in (301, 302, 303, 307, 308):
                target = urljoin(url, reply.getheader('Location') or '')
                parsed = urlsplit(target)
                if parsed.scheme != 'https' or parsed.hostname != 'pan.baidu.com' or parsed.port not in (None, 443):
                    raise CloudDriveError('百度分享跳转到登录或外部页面，请在浏览器接续')
                url, form = target, None
                continue
            if reply.status != 200:
                raise CloudDriveError(f'百度分享 HTTP {reply.status}，请在浏览器检查访问限制')
            content = reply.read(2 * 1024 * 1024 + 1)
            if len(content) > 2 * 1024 * 1024:
                raise CloudDriveError('百度分享响应过大')
            return content
    raise CloudDriveError('百度分享跳转过多，请在浏览器接续')


def _json(session, path, form=None):
    try:
        result = json.loads(_request(session, path, form))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise CloudDriveError('百度未返回目录数据，可能需要浏览器完成验证') from None
    if not isinstance(result, dict):
        raise CloudDriveError('百度分享响应结构变化')
    code = result.get('errno')
    if code not in (0, '0'):
        safe = str(code) if str(code).lstrip('-').isdigit() and len(str(code)) <= 12 else '未知'
        state = 'captcha_required' if str(code) in ('-20', '-62') else 'needs_user'
        raise CloudDriveError(f'百度分享未放行（errno {safe}），请检查提取码、失效状态或在浏览器完成登录/验证码', state)
    return result


def list_files(session, folder_id, page):
    short = session['share'][1:] if session['share'].startswith('1') else session['share']
    if not session.get('baidu_verified'):
        _request(session, '/s/' + session['share'])
        if session['password']:
            result = _json(session, '/share/verify?' + urlencode({'surl': short, 'web': 1, 'clienttype': 0}),
                           {'pwd': session['password'], 'vcode': '', 'vcode_str': ''})
            if result.get('randsk'):
                # Normalize percent escaping once; never print or return it.
                session['visitor_cookies']['BDCLND'] = quote(unquote(result['randsk']), safe='')
        session['baidu_verified'] = True
    paths = session.setdefault('baidu_paths', {'0': '/'})
    if folder_id not in paths:
        raise CloudDriveError('百度目录必须来自当前分享的已读取结果')
    query = {'shorturl': short, 'page': page, 'num': 50, 'order': 'name', 'desc': 0,
             'web': 1, 'clienttype': 0, 'root': 1 if folder_id == '0' else 0}
    if folder_id != '0':
        query['dir'] = paths[folder_id]
    result = _json(session, '/share/list?' + urlencode(query))
    rows = result.get('list')
    if not isinstance(rows, list):
        raise CloudDriveError('百度未返回文件列表，不能判断为空目录')
    if result.get('share_id'):
        session['baidu_share_id'] = result['share_id']
    if result.get('uk'):
        session['baidu_owner_id'] = result['uk']
    normalized = []
    for row in rows[:50]:
        if not isinstance(row, dict):
            continue
        fid = str(row.get('fs_id'))
        directory = str(row.get('isdir')) == '1'
        if directory and isinstance(row.get('path'), str):
            paths[fid] = row['path']
        normalized.append({'fid': fid, 'file_name': row.get('server_filename'),
                           'dir': directory, 'size': row.get('size'),
                           'updated_at': row.get('server_mtime'), 'baidu': row})
    return normalized


def download_link(session, file_id):
    if not session.get('baidu_verified'):
        list_files(session, '0', 1)
    # Share-scoped sign and timestamp from the current site's response only.
    # No scripts evaluated, borrowed OAuth client, generated sign or transfer.
    info = _json(session, '/share/tplconfig?' + urlencode({
        'fields': 'sign,timestamp', 'surl': session['share'], 'web': 1, 'clienttype': 0,
        'channel': 'chunlei', 'view_mode': 1}))
    info = info.get('data') if isinstance(info.get('data'), dict) else info
    sign, timestamp = info.get('sign'), info.get('timestamp')
    owner, share = session.get('baidu_owner_id'), session.get('baidu_share_id')
    if not (isinstance(sign, str) and re.fullmatch('[A-Za-z0-9_-]{8,256}', sign)
            and str(timestamp).isdigit() and str(owner).isdigit() and str(share).isdigit()):
        raise CloudDriveError('百度未提供当前分享下载所需的签名信息，请在分享网页完成登录或验证后接续', 'login_required')
    result = _json(session, '/api/sharedownload?' + urlencode({
        'sign': sign, 'timestamp': timestamp, 'web': 1, 'clienttype': 0, 'channel': 'chunlei'}), {
        'encrypt': 0, 'product': 'share', 'uk': owner, 'primaryid': share,
        'fid_list': json.dumps([int(file_id)]),
        'extra': json.dumps({'sekey': unquote(session['visitor_cookies'].get('BDCLND', ''))})})
    files = result.get('list')
    url = files[0].get('dlink') if isinstance(files, list) and files and isinstance(files[0], dict) else None
    if not isinstance(url, str) or not url.startswith('https://'):
        raise CloudDriveError('百度没有返回可用的 HTTPS 下载地址，请在浏览器处理验证或下载后选择本地原包接续')
    return url
