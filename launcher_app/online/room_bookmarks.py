"""Private local room invitations; names are labels, never room identities."""
from dataclasses import dataclass, field
from pathlib import Path
import base64
import json
import os
import tempfile
import uuid


@dataclass(frozen=True)
class RoomBookmark:
    identity: str
    name: str
    role: str
    code: str = field(repr=False)


def validate_room(code):
    code = str(code or '').strip()
    if not code or len(code) > 256 or any(c.isspace() or ord(c) < 32 for c in code):
        raise ValueError('请输入有效的 Terracotta 大厅编号')
    return code


def _dpapi(data, *, decrypt=False):
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    result = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise OSError('无法访问本机保存的房间凭证')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)


class RoomBookmarks:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return []
        if self.path.stat().st_size > 1024 * 1024:
            raise ValueError('房间收藏文件过大')
        envelope = json.loads(self.path.read_text(encoding='utf-8'))
        if envelope.get('format') == 'dpapi':
            if os.name != 'nt':
                raise ValueError('房间凭证属于另一台 Windows 设备，请重新添加')
            data = json.loads(_dpapi(base64.b64decode(envelope['data']), decrypt=True))
        elif envelope.get('format') == 'local-private':
            data = envelope['data']
        else:
            raise ValueError('无法识别房间收藏文件')
        if not isinstance(data, list) or len(data) > 100:
            raise ValueError('房间收藏文件无效')
        result = []
        for row in data:
            if row.get('role') not in ('host', 'guest'):
                raise ValueError('房间收藏身份无效')
            result.append(RoomBookmark(str(row['identity']), str(row['name'])[:80], row['role'], validate_room(row['code'])))
        return result

    def _save(self, rows):
        if len(rows) > 100:
            raise ValueError('最多保存 100 个房间')
        data = [dict(identity=r.identity, name=r.name, role=r.role, code=r.code) for r in rows]
        if os.name == 'nt':
            payload = {'format': 'dpapi', 'data': base64.b64encode(_dpapi(json.dumps(data, ensure_ascii=False).encode('utf-8'))).decode('ascii')}
        else:
            payload = {'format': 'local-private', 'data': data}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.rooms-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(payload, stream, ensure_ascii=False)
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def add(self, name, role, code):
        code = validate_room(code)
        if role not in ('host', 'guest'):
            raise ValueError('房间收藏身份无效')
        name = str(name or '').strip()[:80]
        if not name:
            raise ValueError('请填写本地备注名称')
        rows = self.load()
        existing = next((r for r in rows if r.code == code and r.role == role), None)
        bookmark = RoomBookmark(existing.identity if existing else uuid.uuid4().hex, name, role, code)
        rows = [r for r in rows if r.identity != bookmark.identity] + [bookmark]
        self._save(rows)
        return bookmark

    def rename(self, identity, name):
        rows = self.load()
        item = next(r for r in rows if r.identity == identity)
        return self.add(name, item.role, item.code)

    def remove(self, identity):
        self._save([r for r in self.load() if r.identity != identity])


def connection_difficulty(state):
    """Only report upstream difficulty; it does not identify the actual route."""
    levels = {'UNKNOWN': '检测中', 'EASIEST': '容易', 'SIMPLE': '较容易', 'MEDIUM': '一般', 'TOUGH': '困难'}
    return levels.get(state.get('difficulty'))
