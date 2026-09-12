"""Read the configured OpenAI-compatible model catalog, without inference."""
from urllib.parse import urlsplit
import requests


def fetch_models(base_url, api_key=''):
    base = str(base_url).strip().rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('请填写有效的接口基础地址，不要带账号、查询参数或 /chat/completions。')
    if base.endswith('/chat/completions'):
        raise ValueError('接口地址请去掉末尾的 /chat/completions。')
    headers = {'Accept': 'application/json'}
    if api_key.strip():
        if parsed.scheme != 'https' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('携带密钥查询远程服务时请使用 HTTPS。')
        headers['Authorization'] = 'Bearer ' + api_key.strip()
    try:
        response = requests.get(base + '/models', headers=headers, timeout=(10, 20), allow_redirects=False)
    except requests.RequestException:
        raise ValueError('连接失败或超时，请检查网络和接口地址。') from None
    if response.status_code in (401, 403):
        raise ValueError('服务商拒绝访问，请检查当前服务商的密钥和账号权限。')
    if response.status_code in (404, 405):
        raise ValueError('这个接口不支持 /models，请继续手动填写模型名称。')
    if response.status_code == 429:
        raise ValueError('请求太频繁，请稍后再试。')
    if response.status_code != 200:
        raise ValueError(f'查询未成功（HTTP {response.status_code}），已保留当前模型。')
    try:
        rows = response.json()['data']
        if not isinstance(rows, list):
            raise ValueError()
        names = sorted({row['id'] for row in rows if isinstance(row, dict)
                        and isinstance(row.get('id'), str) and row['id'].strip()})
    except (ValueError, KeyError, TypeError):
        raise ValueError('返回内容不是兼容的模型列表，请手动填写。') from None
    if not names:
        raise ValueError('服务商返回的列表为空，已保留当前模型。')
    return names
