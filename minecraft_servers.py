"""Add a Minecraft multiplayer address while preserving existing servers.dat entries."""

import os
import shutil
import struct
import tempfile


def _u16(data, pos):
    if pos + 2 > len(data):
        raise ValueError('servers.dat 数据不完整')
    return struct.unpack_from('>H', data, pos)[0], pos + 2


def _i32(data, pos):
    if pos + 4 > len(data):
        raise ValueError('servers.dat 数据不完整')
    return struct.unpack_from('>i', data, pos)[0], pos + 4


def _string(data, pos):
    size, pos = _u16(data, pos)
    end = pos + size
    if end > len(data):
        raise ValueError('servers.dat 字符串不完整')
    return data[pos:end].decode('utf-8'), end


def _payload_end(data, pos, tag, depth=0):
    if depth > 32:
        raise ValueError('servers.dat 嵌套过深')
    fixed = {1: 1, 2: 2, 3: 4, 4: 8, 5: 4, 6: 8}
    if tag in fixed:
        end = pos + fixed[tag]
    elif tag == 8:
        _, end = _string(data, pos)
    elif tag in (7, 11, 12):
        count, pos = _i32(data, pos)
        if count < 0:
            raise ValueError('servers.dat 数组长度无效')
        end = pos + count * {7: 1, 11: 4, 12: 8}[tag]
    elif tag == 9:
        if pos >= len(data):
            raise ValueError('servers.dat 列表不完整')
        element = data[pos]
        count, end = _i32(data, pos + 1)
        if count < 0 or count > 100000:
            raise ValueError('servers.dat 列表长度无效')
        for _ in range(count):
            end = _payload_end(data, end, element, depth + 1)
    elif tag == 10:
        end = pos
        while True:
            if end >= len(data):
                raise ValueError('servers.dat 复合标签不完整')
            child = data[end]
            end += 1
            if child == 0:
                break
            _, end = _string(data, end)
            end = _payload_end(data, end, child, depth + 1)
    else:
        raise ValueError(f'servers.dat 含未知标签类型：{tag}')
    if end > len(data):
        raise ValueError('servers.dat 数据不完整')
    return end


def _tag_string(name, value):
    name, value = name.encode('utf-8'), value.encode('utf-8')
    if len(name) > 65535 or len(value) > 65535:
        raise ValueError('服务器名称或地址过长')
    return b'\x08' + struct.pack('>H', len(name)) + name + struct.pack('>H', len(value)) + value


def _compound_ip(payload):
    pos = 0
    while pos < len(payload):
        tag = payload[pos]
        pos += 1
        if tag == 0:
            break
        name, pos = _string(payload, pos)
        if name == 'ip' and tag == 8:
            return _string(payload, pos)[0]
        pos = _payload_end(payload, pos, tag)
    return ''


def add_server(game_dir, name, address):
    """Return True when added, False when the same address already exists."""
    address = str(address or '').strip()
    if not address or len(address) > 255 or any(c.isspace() for c in address):
        raise ValueError('服务器地址无效')
    os.makedirs(game_dir, exist_ok=True)
    target = os.path.join(game_dir, 'servers.dat')
    if os.path.isfile(target):
        if os.path.getsize(target) > 8 * 1024 * 1024:
            raise ValueError('servers.dat 过大，未自动修改')
        with open(target, 'rb') as stream:
            data = stream.read()
    else:
        data = b'\x0a\x00\x00\x00'
    if not data or data[0] != 10:
        raise ValueError('servers.dat 格式无法识别，未自动修改')
    _, pos = _string(data, 1)
    header = data[:pos]
    children = []
    found = False
    while pos < len(data):
        tag = data[pos]
        if tag == 0:
            break
        start = pos
        name_key, pos = _string(data, pos + 1)
        payload_start = pos
        pos = _payload_end(data, pos, tag)
        raw = data[start:pos]
        if name_key == 'servers':
            if found or tag != 9 or payload_start >= len(data) or data[payload_start] != 10:
                raise ValueError('servers.dat 服务器列表格式无法识别，未自动修改')
            found = True
            count, item_pos = _i32(data, payload_start + 1)
            entries = []
            for _ in range(count):
                item_end = _payload_end(data, item_pos, 10)
                entry = data[item_pos:item_end]
                if _compound_ip(entry).casefold() == address.casefold():
                    return False
                entries.append(entry)
                item_pos = item_end
            new_entry = _tag_string('name', name) + _tag_string('ip', address) + b'\x00'
            raw = (raw[:payload_start - start + 1] +
                   struct.pack('>i', count + 1) + b''.join(entries) + new_entry)
        children.append(raw)
    if pos != len(data) - 1 or data[pos] != 0:
        raise ValueError('servers.dat 末尾格式无法识别，未自动修改')
    if not found:
        new_entry = _tag_string('name', name) + _tag_string('ip', address) + b'\x00'
        children.append(b'\x09\x00\x07servers\x0a' + struct.pack('>i', 1) + new_entry)
    updated = header + b''.join(children) + b'\x00'
    fd, temporary = tempfile.mkstemp(prefix='.amcl-servers-', dir=game_dir)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(updated)
        if os.path.isfile(target):
            shutil.copy2(target, target + '.amcl.bak')
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return True
