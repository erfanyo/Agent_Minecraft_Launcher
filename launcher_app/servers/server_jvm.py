# -*- coding: utf-8 -*-
"""服务端 JVM 参数文件 ``user_jvm_args.txt`` 的结构化读写。

Forge / NeoForge 服务端启动器会把根目录的 ``user_jvm_args.txt`` 原样塞进 java 命令行,
因此它就是服务端的「运行配置」。这里提供纯函数式的解析/合并/校验,落盘交给
:mod:`server_jvm_io`。

**为什么要能保留未知行**:这个文件用户和整合包作者都会手工加东西(注释、额外的
``-XX:`` 参数、甚至写错的参数)。启动器只该改自己管的项,其它行必须原样留住,否则
「保存一次就把别人的调优吞了」。

**校验口径必须与启动侧一致**: :mod:`server_launch` 在构建启动计划时会拒绝它不认识
的参数(只放行内存与几个常用 GC 开关)。如果这里放行、那里拒绝,用户会遇到
「保存成功但服务端起不来」,所以两边共用 :func:`unsupported_args` 判断。
"""
from __future__ import annotations

import re

#: 与 server_launch.build_launch_plan 完全一致的放行规则
_ALLOWED = re.compile(
    r'-X(?:ms|mx|ss)\d+[kKmMgG]|'
    r'-XX:[+-](?:UseG1GC|UseZGC|UseParallelGC|UseSerialGC)')

#: 堆内存参数(单独处理,因为有「自动/手动」语义)。
#: 注意**不含** ``-Xss``:那是线程栈大小,不是堆内存,混进来会被误当成「初始内存」。
_MEMORY = re.compile(r'^-X(ms|mx)(\d+)([kKmMgG])$')

#: 可选 GC 开关(给 UI 做下拉,不强迫用户记拼写)
GC_CHOICES = [
    ('默认(G1)', '-XX:+UseG1GC'),
    ('低延迟 ZGC', '-XX:+UseZGC'),
    ('高吞吐 Parallel', '-XX:+UseParallelGC'),
    ('串行 Serial(小内存)', '-XX:+UseSerialGC'),
]


def tokenize(text: str) -> list:
    """按空白拆参数(与启动侧 ``_tokens`` 同样的宽松口径:不做 shell 解析)。"""
    return [token for token in str(text or '').split() if token]


def parse_records(text: str) -> list:
    """解析成记录列表,保住注释与空行。

    每项 ``{'kind','raw','arg'}``:``kind`` 为 ``'comment'``/``'blank'``/``'arg'``。
    注意:参数以「行」为单位保留,不做同行多参数的拆分——那样才能在原样写回时
    不改变用户文件的排版。
    """
    records = []
    for line in str(text or '').splitlines():
        stripped = line.strip()
        if not stripped:
            records.append({'kind': 'blank', 'raw': line, 'arg': ''})
        elif stripped.startswith('#'):
            records.append({'kind': 'comment', 'raw': line, 'arg': ''})
        else:
            records.append({'kind': 'arg', 'raw': line, 'arg': stripped})
    return records


def serialize_records(records: list) -> str:
    lines = []
    for record in records or []:
        if record.get('kind') == 'arg':
            lines.append(record.get('arg', ''))
        else:
            lines.append(record.get('raw', ''))
    return '\n'.join(lines) + ('\n' if lines else '')


def all_args(records: list) -> list:
    """所有参数(含一行里写了多个的情况),用于校验。"""
    args = []
    for record in records or []:
        if record.get('kind') == 'arg':
            args.extend(tokenize(record.get('arg', '')))
    return args


def unsupported_args(args: list) -> list:
    """返回启动侧会拒绝的参数(去重,保持出现顺序)。"""
    bad = []
    for arg in args or []:
        if not is_supported(arg) and arg not in bad:
            bad.append(arg)
    return bad


def is_supported(arg: str) -> bool:
    """该参数是否在启动侧放行范围内(内存 + 常用 GC 开关)。"""
    return _ALLOWED.fullmatch(str(arg)) is not None


def read_memory(records: list):
    """读**堆内存**设置 → ``{'max': '4G' 或 None, 'min': ...}``(原样返回数值+单位)。

    只看 ``-Xmx``/``-Xms``;``-Xss``(线程栈)不算,避免被误显示成初始内存。
    """
    out = {'max': None, 'min': None}
    for record in records or []:
        if record.get('kind') != 'arg':
            continue
        for token in tokenize(record.get('arg', '')):
            match = _MEMORY.match(token)
            if match:
                kind = 'max' if match.group(1) == 'mx' else 'min'
                out[kind] = match.group(2) + match.group(3).upper()
    return out


def memory_flags(max_gb=None, min_gb=None) -> list:
    """按 GB 生成内存参数;传 None 表示不设置该项。"""
    flags = []
    if min_gb:
        flags.append(f'-Xms{int(min_gb)}G')
    if max_gb:
        flags.append(f'-Xmx{int(max_gb)}G')
    return flags


def merge(records: list, *, max_gb=None, min_gb=None, extras: list | None = None,
          replace_extras: bool = False) -> list:
    """生成新的记录列表。

    - **内存**:``None`` 表示「不要这一项」——已有的对应 ``-Xmx``/``-Xms`` 会被删除,
      传入数值则替换掉旧值(不会叠加出两个 ``-Xmx``)。
    - **额外参数**:``replace_extras=True`` 时以 ``extras`` 覆盖原有「可管理参数」行;
      否则把 ``extras`` 里还没有的追加到末尾。不认识的行(如 ``-javaagent``)在两种
      情况下都原样保留——那是用户的文件,不该被顺手清掉。
    - 注释/空行一律原样保留。
    """
    wanted = memory_flags(max_gb, min_gb)

    kept = []
    for record in records or []:
        if record.get('kind') != 'arg':
            kept.append(dict(record))
            continue
        tokens = tokenize(record.get('arg', ''))
        # 整行只有堆内存参数 → 丢弃,统一由下面的 wanted 重写(避免叠加出两个 -Xmx)。
        # 混合行(如 "-Xmx4G -XX:+UseG1GC")不在此列,按原样保留,以免顺手删掉 GC 开关。
        if tokens and all(_MEMORY.match(t) for t in tokens):
            continue
        if replace_extras and tokens and all(
                _MEMORY.match(t) is None and _ALLOWED.fullmatch(t) for t in tokens):
            continue      # 只清「全是可管理参数」的行,不动混合行/未知参数行
        kept.append(dict(record))

    for flag in wanted:
        kept.append({'kind': 'arg', 'arg': flag, 'raw': flag})

    existing = set(all_args(kept))
    for flag in (extras or []):
        if flag and flag not in existing:
            kept.append({'kind': 'arg', 'arg': flag, 'raw': flag})
            existing.add(flag)
    return kept


def validate(*, max_gb=None, min_gb=None, extras: list | None = None):
    """校验一组设置 → ``(ok, problems)``;problems 为中文说明列表。

    与启动侧同口径:只接受内存参数与常用 GC 开关,其余参数会被启动器拒绝,
    所以在**写入前**就挡住,避免「保存成功但服务端起不来」。
    """
    problems = []
    for label, value in (('最大内存', max_gb), ('初始内存', min_gb)):
        if value is None:
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            problems.append(f'{label}必须是整数 GB。')
            continue
        if number < 1 or number > 256:
            problems.append(f'{label}需在 1~256 GB 之间。')
    if max_gb is not None and min_gb is not None:
        try:
            if int(min_gb) > int(max_gb):
                problems.append('初始内存不能大于最大内存。')
        except (TypeError, ValueError):
            pass
    bad = unsupported_args(extras or [])
    if bad:
        problems.append('这些参数启动器不会接受(只放行内存与常用 GC 开关):'
                        + '、'.join(bad))
    return (not problems), problems
