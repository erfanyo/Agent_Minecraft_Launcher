"""Portable validation of untrusted pack paths, including Windows path syntax."""
import ntpath
import os

def _resolved(path):
    value = os.path.realpath(path)
    # Windows may return extended-length syntax when a directory is created
    # concurrently. Compare equivalent path spellings consistently.
    if value.startswith('\\\\?\\UNC\\'):
        value = '\\\\' + value[8:]
    elif value.startswith('\\\\?\\'):
        value = value[4:]
    return value

def safe_child(root, relative):
    if not isinstance(relative, str) or not relative:
        raise ValueError("整合包里有空文件路径，已停止导入")
    normalized = relative.replace('\\', '/')
    parts = normalized.split('/')
    if (ntpath.splitdrive(normalized)[0] or normalized.startswith('/')
            or any(p in {'', '.', '..'} or p.endswith((' ', '.'))
                   or any(c in '<>:"|?*' or ord(c) < 32 for c in p)
                   or p.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                       *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
                   for p in parts)):
        raise ValueError("整合包包含不安全的文件路径，已停止导入")
    base = _resolved(root)
    target = _resolved(os.path.join(base, *parts))
    base_key, target_key = os.path.normcase(base), os.path.normcase(target)
    if os.path.commonpath([base_key, target_key]) != base_key or target_key == base_key:
        raise ValueError("整合包文件指向实例目录之外，已停止导入")
    return target

def safe_component(value):
    if not isinstance(value, str) or '/' in value or '\\' in value:
        raise ValueError("实例或版本名称包含路径分隔符")
    safe_child(os.getcwd(), value)
    return value
