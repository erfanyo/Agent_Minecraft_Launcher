# -*- coding: utf-8 -*-
"""「某个 mod 的专属目录」通用文件管理(纯逻辑,不碰 Qt)。

为什么要有这个模块:YSM 皮肤、TACZ 枪包、Create 投影原理图、车万女仆模型包、
Hotai 补丁数据……它们的用法都是同一件事——**往一个目录里丢文件**。这些页面
现在由插件注册(见 ``plugin_manager.register_instance_section``),但「列目录、
导入、删除」的逻辑只有一份,放在核心,免得每个插件各写一遍。

设计口径:
- **导入只做拷贝,不动源文件**;同名冲突默认**不覆盖**,原样报告给用户;
- 压缩包解压**全部内容**(不像单文件那样按扩展名过滤——包里的结构我们判断不了),
  但会挡掉绝对路径与 ``..`` 逃逸;
- 删除**真的删**,调用方必须自己先确认(和核心其它删除一致)。
"""
from __future__ import annotations

import os
import shutil
import zipfile

#: 解压时忽略的系统垃圾目录(压缩包里常见,不是用户内容)
IGNORED_ARCHIVE_DIRS = ('__MACOSX', '.DS_Store')


def human_size(num_bytes: int) -> str:
    """字节数 → 人看的字符串。"""
    try:
        value = float(num_bytes)
    except (TypeError, ValueError):
        return '未知'
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            return f'{value:.0f} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
        value /= 1024
    return f'{value:.1f} GB'


def dir_size(path: str) -> tuple:
    """目录的 (总字节, 文件数);读不到就是 (0, 0)。"""
    total = 0
    count = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            full = os.path.join(base, name)
            try:
                total += os.path.getsize(full)
                count += 1
            except OSError:
                continue
    return total, count


def matches(name: str, exts) -> bool:
    """文件名是否属于要列出的类型;``exts`` 为空表示不限类型。"""
    if not exts:
        return True
    return os.path.splitext(name)[1].lower() in tuple(e.lower() for e in exts)


def scan(root: str, *, exts=(), show_dirs: bool = True) -> list:
    """列出 ``root`` 下的内容包 → ``[{'name','path','is_dir','size','file_count'}]``。

    ``exts`` 只约束**文件**;子目录总是在(子目录就是一个包,比如一个枪包一个文件夹)。
    """
    if not root or not os.path.isdir(root):
        return []
    out = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    for name in names:
        if name in IGNORED_ARCHIVE_DIRS:
            continue
        full = os.path.join(root, name)
        if os.path.isdir(full):
            if not show_dirs:
                continue
            size, count = dir_size(full)
            out.append({'name': name, 'path': full, 'is_dir': True,
                        'size': size, 'file_count': count})
        elif matches(name, exts):
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            out.append({'name': name, 'path': full, 'is_dir': False,
                        'size': size, 'file_count': 1})
    return out


def scan_tree(root: str, *, exts=()) -> list:
    """递归列出 ``root`` 下的文件(相对路径),用于**只读**的目录(如 ``hotai/``)。

    ``hotai/`` 是 mod 自己生成的类路径树(``com/github/.../*.badiff``),不是
    「丢文件进去」的目录,所以只列不给导入/删除。
    """
    if not root or not os.path.isdir(root):
        return []
    out = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORED_ARCHIVE_DIRS]
        for name in sorted(files):
            if not matches(name, exts):
                continue
            full = os.path.join(base, name)
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            out.append({'name': os.path.relpath(full, root).replace('\\', '/'),
                        'path': full, 'is_dir': False, 'size': size,
                        'file_count': 1})
    return out


def summarize(entries, unit: str = '个') -> str:
    """一句话概括:``3 个包 · 共 128 个文件 · 24.5 MB``。"""
    entries = list(entries or [])
    if not entries:
        return '空'
    files = sum(int(e.get('file_count') or 0) for e in entries)
    size = sum(int(e.get('size') or 0) for e in entries)
    return f'{len(entries)} {unit} · 共 {files} 个文件 · {human_size(size)}'


def unique_dest(root: str, name: str) -> str:
    """``root/name`` 不冲突就直接用,冲突则加 `` (2)``、`` (3)``…"""
    candidate = os.path.join(root, name)
    if not os.path.exists(candidate):
        return candidate
    stem, ext = os.path.splitext(name)
    index = 2
    while True:
        candidate = os.path.join(root, f'{stem} ({index}){ext}')
        if not os.path.exists(candidate):
            return candidate
        index += 1


def is_archive(path: str) -> bool:
    return os.path.isfile(path) and os.path.splitext(path)[1].lower() == '.zip'


def _safe_member(target_root: str, member: str):
    """压缩包成员的安全落地路径;越界(绝对路径 / ``..``)返回 None。

    注意**先按 '/' 切分再判断**,不要用 ``os.path.normpath``:在 Windows 上
    normpath 会把 '/' 换成 '\\',切分就切不动了,``__MACOSX/._a`` 这种会漏进来。
    """
    if not member or member.endswith('/'):
        return None
    raw = member.replace('\\', '/')
    if raw.startswith('/') or os.path.isabs(member):
        return None
    parts = [p for p in raw.split('/') if p not in ('', '.')]
    if not parts:
        return None
    if any(p == '..' or ':' in p for p in parts):
        return None                      # 上跳 或 盘符(C:\…)
    if parts[0] in IGNORED_ARCHIVE_DIRS:
        return None
    dest = os.path.join(target_root, *parts)
    # 双保险:算出来的绝对路径必须还在目标目录里
    if os.path.commonpath([os.path.abspath(target_root),
                           os.path.abspath(dest)]) != os.path.abspath(target_root):
        return None
    return dest


def extract_archive(target_root: str, archive: str) -> dict:
    """把 zip 解开到 ``target_root``;返回 ``{'added','skipped','errors'}``。

    同名文件**不覆盖**(记进 ``skipped``),因为覆盖别人的包比多留一个更糟。
    """
    result = {'added': [], 'skipped': [], 'errors': []}
    os.makedirs(target_root, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                if info.is_dir():
                    continue
                dest = _safe_member(target_root, info.filename)
                if dest is None:
                    result['skipped'].append(info.filename)
                    continue
                if os.path.exists(dest):
                    result['skipped'].append(info.filename)
                    continue
                try:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with bundle.open(info) as src, open(dest, 'wb') as out:
                        shutil.copyfileobj(src, out)
                    result['added'].append(info.filename)
                except OSError as exc:
                    result['errors'].append((info.filename, str(exc)))
    except (zipfile.BadZipFile, OSError) as exc:
        result['errors'].append((os.path.basename(archive), f'不是有效的 zip:{exc}'))
    return result


def import_sources(root: str, sources, *, exts=()) -> dict:
    """把用户选的文件/文件夹/压缩包导入 ``root``。

    返回 ``{'added','skipped','errors'}``:
    - ``added``  = 真的写进去的名字;
    - ``skipped``= 因为同名(或类型不符、路径越界)没动的;
    - ``errors`` = ``[(名字, 原因)]``。

    单文件会按 ``exts`` 过滤(免得把一张截图丢进 schematics);压缩包解压不按
    扩展名过滤——包内的结构我们判断不了,少解一个文件比多解一个更糟。
    """
    result = {'added': [], 'skipped': [], 'errors': []}
    if not root:
        result['errors'].append(('', '目标目录未知'))
        return result
    try:
        os.makedirs(root, exist_ok=True)
    except OSError as exc:
        result['errors'].append((root, f'无法创建目录:{exc}'))
        return result
    for source in sources or ():
        name = os.path.basename(str(source).rstrip('\\/'))
        if not name:
            continue
        if not os.path.exists(source):
            result['errors'].append((name, '文件不存在'))
            continue
        if os.path.isdir(source):
            dest = unique_dest(root, name)
            try:
                shutil.copytree(source, dest)
                result['added'].append(os.path.basename(dest))
            except OSError as exc:
                result['errors'].append((name, str(exc)))
            continue
        if is_archive(source):
            outcome = extract_archive(root, source)
            result['added'].extend(outcome['added'])
            result['skipped'].extend(outcome['skipped'])
            result['errors'].extend(outcome['errors'])
            continue
        if not matches(name, exts):
            result['skipped'].append(name)
            continue
        try:
            dest = unique_dest(root, name)
            shutil.copy2(source, dest)
            # 报**实际落地**的名字(冲突时会被改成 "a (2).nbt"),否则用户按
            # 报告去找文件会找不到
            result['added'].append(os.path.basename(dest))
        except OSError as exc:
            result['errors'].append((name, str(exc)))
    return result


def remove_paths(paths) -> dict:
    """删除给定的文件/目录(调用方负责先确认)。返回 ``{'removed','errors'}``。"""
    result = {'removed': [], 'errors': []}
    for path in paths or ():
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            result['removed'].append(os.path.basename(str(path)))
        except OSError as exc:
            result['errors'].append((os.path.basename(str(path)), str(exc)))
    return result


def import_summary(outcome: dict) -> str:
    """把 :func:`import_sources` 的结果说成人话(状态栏/提示用)。"""
    added = len((outcome or {}).get('added') or [])
    skipped = len((outcome or {}).get('skipped') or [])
    errors = (outcome or {}).get('errors') or []
    text = f'已导入 {added} 项'
    if skipped:
        text += f',跳过 {skipped} 项(同名或类型不符)'
    if errors:
        text += f',{len(errors)} 项失败'
    return text
