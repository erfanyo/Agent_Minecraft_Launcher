# -*- coding: utf-8 -*-
"""KubeJS 报错定位:把日志里的报错还原成「哪个文件、第几行、什么错」。

**为什么值得单独做**:KubeJS 脚本报错会让服务端启动失败或功能静默失效,而日志里
一行 `! business/counter.js#501: Error in ...` 对人来说几乎不可用——你要先知道
`business/` 是相对 `kubejs/server_scripts/` 的,再手工去数第 501 行。
这里把它变成「点一下跳到那一行」。

**纯函数**:解析、定位、取片段都不碰磁盘之外的 Qt,便于单测。真正读文件只在
:func:`read_excerpt` 里,并且明确返回错误而不是抛异常。

注意口径:报错位置是**相对 kubejs 根目录**的(如 `business/counter.js` →
`kubejs/server_scripts/business/counter.js`),也可能是 `client_scripts/` 或
`startup_scripts/` 下的,需要按存在性探测,不能假定目录。
"""
from __future__ import annotations

import os
import re

#: KubeJS 报错行。实测有**两种**形态,都要认:
#:   ① 精简日志(logs/kubejs/server.log):
#:      [18:18:15] [ERROR] ! business/counter.js#501: Error in 'X':
#:   ② Forge 服务端日志(logs/latest.log 等,更常见):
#:      [18:18:15] [Server thread/ERROR] [KubeJS Server/]: business/counter.js#501: Error in 'X': TypeError: ...
#: 差别在于中括号段、(可选)的 "KubeJS Server/]: " 前缀、以及 `!` 的有无。
_ERROR_LINE = re.compile(
    r'^\s*\[(?P<time>[\d:]+)\]\s*'
    r'\[[^\]]*(?:ERROR|WARN)[^\]]*\]\s*'
    r'(?:\[KubeJS[^\]]*\]:\s*)?'
    r'!?\s*'
    r'(?P<path>[^#:\s]+)#(?P<line>\d+):\s*'
    r'(?P<rest>.*)$')
#: 异常类型行:TypeError: xxx(可能出现在同一行,也可能在下一行)
_EXCEPTION = re.compile(
    r'(?P<kind>[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception))\s*:\s*(?P<msg>.*)')

#: 搜索脚本时按顺序尝试的子目录(实测口径:日志里的路径相对 kubejs 根)
SCRIPT_SUBDIRS = ('server_scripts', 'startup_scripts', 'client_scripts')

#: 片段默认取错误行前后各多少行
CONTEXT_BEFORE = 6
CONTEXT_AFTER = 8


def parse_errors(text: str) -> list:
    """从日志文本里提取 KubeJS 报错 → 记录列表。

    每条 ``{'time','relpath','line','title','kind','message'}``;``line`` 为 int。
    同一「文件 + 行」只保留**第一条**(同一处报错通常刷屏,去重后更好读)。
    """
    out = []
    seen = set()
    lines = str(text or '').splitlines()
    for index, raw in enumerate(lines):
        match = _ERROR_LINE.match(raw.strip())
        if not match:
            continue
        relpath = match.group('path')
        lineno = int(match.group('line'))
        key = (relpath, lineno)
        if key in seen:
            continue
        seen.add(key)
        rest = match.group('rest').strip()
        record = {
            'time': match.group('time'),
            'relpath': relpath,
            'line': lineno,
            # 「Error in 'X'」是出错时机,真正的异常类型/说明可能在同行后半段
            'title': rest,
            'kind': '',
            'message': '',
        }
        inline = _EXCEPTION.search(rest)
        if inline:
            record['kind'] = inline.group('kind')
            record['message'] = inline.group('msg').strip()
        else:
            # 异常类型在下一行(甚至下两行)
            for follow in lines[index + 1:index + 3]:
                found = _EXCEPTION.match(follow.strip())
                if found:
                    record['kind'] = found.group('kind')
                    record['message'] = found.group('msg').strip()
                    break
        if not record['message']:
            record['message'] = rest
        out.append(record)
    return out


def resolve_path(kubejs_root: str, relpath: str) -> str | None:
    """把日志里的相对路径定位到真实文件 → 绝对路径;找不到返回 None。

    日志里的路径相对 ``kubejs`` 根,但**不带** ``server_scripts`` 前缀,所以逐个
    脚本子目录去试;也接受路径本身已含子目录的情况。
    """
    if not kubejs_root or not relpath:
        return None
    relative = relpath.replace('\\', '/').lstrip('/')
    candidates = [os.path.join(kubejs_root, *relative.split('/'))]
    for sub in SCRIPT_SUBDIRS:
        candidates.append(os.path.join(kubejs_root, sub, *relative.split('/')))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def read_excerpt(path: str, line: int, *, before: int = CONTEXT_BEFORE,
                 after: int = CONTEXT_AFTER):
    """读错误行附近的代码 → ``{'lines','start','error_index','text','error'}``。

    ``lines`` 是 ``[(行号, 内容), ...]``,``error_index`` 指出哪一条是出错行,
    便于 UI 高亮。读不到时返回 ``error`` 说明,不抛异常。
    """
    if not path or not os.path.isfile(path):
        return {'lines': [], 'start': 0, 'error_index': -1, 'text': '',
                'error': '脚本文件不存在(可能已被删除或改名)'}
    try:
        with open(path, encoding='utf-8', errors='replace') as stream:
            all_lines = stream.read().splitlines()
    except OSError as error:
        return {'lines': [], 'start': 0, 'error_index': -1, 'text': '',
                'error': f'读取失败:{error}'}
    total = len(all_lines)
    if total == 0:
        return {'lines': [], 'start': 0, 'error_index': -1, 'text': '',
                'error': '脚本是空文件'}
    start = max(1, int(line) - max(0, before))
    end = min(total, int(line) + max(0, after))
    picked = [(number, all_lines[number - 1]) for number in range(start, end + 1)]
    return {'lines': picked, 'start': start,
            'error_index': int(line) - start if start <= int(line) <= end else -1,
            'text': '\n'.join(f'{number:>5}  {content}' for number, content in picked),
            'error': ''}


def group_by_file(errors: list) -> list:
    """按文件归并 → ``[{'relpath','count','errors'}]``,方便按文件折叠查看。"""
    buckets = {}
    order = []
    for record in errors or []:
        key = record.get('relpath', '')
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(record)
    return [{'relpath': key, 'count': len(buckets[key]), 'errors': buckets[key]}
            for key in order]


def summarize(errors: list) -> str:
    """一句话摘要(给状态栏/标题用)。"""
    if not errors:
        return '没有发现 KubeJS 报错。'
    files = {record.get('relpath') for record in errors}
    return f'发现 {len(errors)} 处报错,分布在 {len(files)} 个脚本文件。'


#: 常见 KubeJS 报错的**成因提示**。只做「经验提示」,不当作结论——
#: 本项目的实际案例就是反例:`Cannot find function getIngredients` 看着像脚本写错,
#: 根因其实是缺热补丁数据(hotai)。
HINTS = [
    (r'Cannot find function (\w+)',
     '这个函数在服务端不存在。可能该 mod 的补丁数据没打上(例如缺少 hotai 之类的补丁目录),'
     '而不是脚本写错了。先确认对应 mod 的补丁/数据目录齐全。'),
    (r'Cannot find (?:method|field) (\w+)',
     '这个成员在服务端不存在。常见原因是该 mod 只有客户端实现了它,'
     '或者服务端版本与脚本预期不一致。'),
    (r'is not defined',
     '用了没有定义的名字。检查拼写,或该变量是否定义在另一个脚本/另一个加载阶段'
     '(startup 与 server 脚本不共享作用域)。'),
    (r'Unexpected token|SyntaxError',
     '语法错误。按提示的行号看那一行附近,通常是括号/逗号/引号不配对。'),
    (r'Cannot read (?:properties|property)',
     '读到了 null/undefined 的属性。多发生在配方或物品 ID 写错、目标不存在时。'),
    (r'no such (?:item|block|fluid|recipe)|Unknown item',
     '引用了不存在的 ID。多半是物品/流体 ID 拼错,或对应 mod 没装/没加载。'),
]


def hints_for(record: dict) -> list:
    """按报错内容给出成因提示(可能多条,也可能为空)。"""
    blob = f"{record.get('title', '')} {record.get('message', '')}"
    out = []
    for pattern, hint in HINTS:
        if re.search(pattern, blob, re.I):
            out.append(hint)
    return out
