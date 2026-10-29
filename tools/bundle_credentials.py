"""Build-only obfuscation: raises extraction cost, does not encrypt a client secret."""
import hashlib
import os
from pathlib import Path
import secrets
import zlib

MODULE = 'launcher_app.runtime.bundled_credentials'


def credential_code(key):
    raw = key.strip().encode('utf-8')
    if not raw or len(raw) > 4096 or any(c < 33 or c > 126 for c in raw):
        raise ValueError('Invalid release credential (value omitted)')
    data = zlib.compress(raw)
    seed = secrets.token_bytes(32)
    pad = b''.join(hashlib.sha256(seed + i.to_bytes(4, 'big')).digest()
                   for i in range((len(data) + 31) // 32))
    encoded = bytes(a ^ b for a, b in zip(data, pad))
    order = list(range(len(encoded)))
    secrets.SystemRandom().shuffle(order)
    shuffled = bytes(encoded[i] for i in order)
    # No key string or generated source file is written to disk. Each build has
    # a different mask and byte permutation. All decoding material ships locally.
    source = f'''def curseforge_key():
 import hashlib, zlib
 s = {seed!r}
 p = {tuple(order)!r}
 b = {shuffled!r}
 d = bytearray(len(b))
 for i, j in enumerate(p): d[j] = b[i]
 k = b''.join(hashlib.sha256(s + i.to_bytes(4, 'big')).digest() for i in range((len(d)+31)//32))
 return zlib.decompress(bytes(a ^ c for a, c in zip(d, k))).decode('utf-8')
'''
    return compile(source, '<bundled-credentials>', 'exec', optimize=2)


def inject_credentials(analysis, root):
    from PyInstaller.config import CONF
    # CI can pass a secret as an environment variable; local release uses a
    # deliberately ignored file. Do not infer a release key from user settings.
    key = os.environ.get('AMCL_RELEASE_CURSEFORGE_KEY', '').strip()
    path = Path(root) / '.secrets' / 'curseforge-api-key.txt'
    if not key and path.is_file():
        key = path.read_text(encoding='utf-8-sig').strip()
    if not key:
        print('CurseForge: no release credential supplied; using source-build stub.')
        return
    if not any(row[0] == MODULE for row in analysis.pure):
        raise RuntimeError('Bundled credential module missing from analysis')
    cache = CONF['code_cache'].get(id(analysis.pure))
    if cache is None:
        raise RuntimeError('Unsupported PyInstaller code cache; credential injection aborted')
    cache[MODULE] = credential_code(key)
    print('CurseForge: obfuscated release credential injected (value omitted).')
