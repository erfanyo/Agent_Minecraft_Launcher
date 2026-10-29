"""Minecraft server EULA retrieval and explicit, per-server acceptance."""
from datetime import datetime, timezone
from html.parser import HTMLParser
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse

import requests


EULA_URL = 'https://www.minecraft.net/eula'
_BLOCKS = {
    'address', 'article', 'aside', 'blockquote', 'br', 'div', 'footer',
    'h1', 'h2', 'h3', 'h4', 'header', 'li', 'main', 'nav', 'ol', 'p',
    'section', 'table', 'td', 'th', 'tr', 'ul',
}


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._hidden = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ('script', 'style', 'svg', 'template'):
            self._hidden += 1
        elif not self._hidden and tag in _BLOCKS:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ('script', 'style', 'svg', 'template'):
            self._hidden = max(0, self._hidden - 1)
        elif not self._hidden and tag in _BLOCKS:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self._hidden:
            self.parts.append(data)


def _plain_eula(html):
    parser = _VisibleText()
    parser.feed(html)
    lines = []
    for raw in ''.join(parser.parts).replace('\r', '').split('\n'):
        line = ' '.join(raw.split())
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    text = '\n\n'.join(lines)
    marker = 'Minecraft End(er)-User License Agreement'
    start = text.find(marker)
    if start < 0:
        raise ValueError('官方页面中没有识别到 Minecraft EULA 正文')
    text = text[start:]
    if len(text) < 3000 or 'Mojang AB' not in text:
        raise ValueError('官方 EULA 正文不完整，请稍后重试')
    return text


def fetch_minecraft_eula(timeout=(10, 25)):
    """Fetch the current official text. Do not silently accept cached terms."""
    response = requests.get(
        EULA_URL,
        headers={'User-Agent': 'AMCL/0.6 (Minecraft server EULA viewer)'},
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()
    final_url = response.url
    host = (urlparse(final_url).hostname or '').lower()
    if host != 'minecraft.net' and not host.endswith('.minecraft.net'):
        raise ValueError('EULA 页面跳转到了非 Minecraft 官方网站，已停止加载')
    if len(response.content) > 4 * 1024 * 1024:
        raise ValueError('官方 EULA 页面异常过大，已停止加载')
    try:
        html = response.content.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('官方 EULA 页面不是预期的 UTF-8 文本') from exc
    return {'text': _plain_eula(html), 'url': final_url}


def accept_minecraft_eula(root):
    """Atomically set eula=true while preserving unrelated comments/settings."""
    root = Path(root).resolve(strict=True)
    path = root / 'eula.txt'
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError('eula.txt 不是普通文件，无法安全修改')
    if path.exists() and path.stat().st_size > 256 * 1024:
        raise ValueError('eula.txt 异常过大，无法安全修改')
    lines = path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []
    kept = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith(('#', '!')) and '=' in line:
            key, _value = line.split('=', 1)
            if key.strip() == 'eula':
                continue
        kept.append(line)
    accepted = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if kept and kept[-1]:
        kept.append('')
    kept.extend([
        f'# Accepted explicitly through AMCL at {accepted}',
        f'# {EULA_URL}',
        'eula=true',
    ])
    handle = tempfile.NamedTemporaryFile(
        mode='w', encoding='utf-8', newline='\n',
        prefix='.amcl-eula-', suffix='.pending', dir=root, delete=False)
    pending = Path(handle.name)
    try:
        with handle:
            handle.write('\n'.join(kept) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pending, path)
    finally:
        try:
            pending.unlink(missing_ok=True)
        except OSError:
            pass
    return path
