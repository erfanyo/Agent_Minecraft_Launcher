# -*- coding: utf-8 -*-
"""服务端日志诊断:哪些 Mod 建议停用,以及它们都是干什么的。

设计要点(与 AMCL 既有约定一致):

1. **只读、不自动改**。本模块只产出「建议清单」;真正停用仍走
   ``agent_tools.set_server_mod_enabled``(可回退重命名)并需用户确认。
   自动删/停 Mod 一旦误判代价很大,所以这里刻意不做决定,只给证据。
2. **证据分级,不靠后缀猜**。按可信度分三级,日志里点名报错才是高级别证据:
   - ``high``  :日志里出现 ``-- MOD xxx --`` 且伴随类加载失败 → 基本可确定
   - ``medium``:元数据声明仅客户端,或已被实例禁用
   - ``low``   :仅「加载失败」字样,可能是前置/版本问题而非该 Mod 本身
3. **解析是纯函数**。``parse_log_evidence`` 只吃字符串,便于单测;读磁盘的部分
   单独放在 ``collect_server_mods``。
4. 输出用 Markdown 表格(``| a | b |``):**模型**读到规整文本,**用户**由
   ``chat_view`` 渲染成真表,无需给工具单做一套 UI。
"""
from __future__ import annotations

import os
import re


# 日志里点名的 Mod 行,如 ``-- MOD lootbeams --``。
# 注意排除 ``-- MOD Loading ... --`` 这类框架自身的段落标题。
_MOD_LINE = re.compile(r'^\s*--\s*MOD\s+([A-Za-z0-9_.\-]+)\s*--\s*$', re.M)
_MOD_LINE_SKIP = {'loading', 'mod', 'none', 'unknown'}
# 明确的类加载失败(几乎必然是「这个 Mod 在服务端跑不起来」)。
_CLASS_ERROR = re.compile(
    r'(NoClassDefFoundError|ClassNotFoundException|NoSuchMethodError|'
    r'NoSuchFieldError)')
# 加载器报「某 Mod 加载失败」。形如:
#   Failure message: LootBeams (lootbeams) has failed to load correctly
# 优先取括号里的 modId,没有括号才退回显示名。
_LOAD_FAIL = re.compile(
    r'Failure message:\s*(.+?)\s*has failed to load correctly|'
    r'(?:Mod|模组)\s+([A-Za-z0-9_.\-]+)\s+(?:has failed|failed to load)', re.I)
_FAIL_BRACKET = re.compile(r'\(([A-Za-z0-9_.\-]+)\)')
# 明确的客户端专属痕迹:错误里提到客户端类包。
_CLIENT_TRACE = re.compile(
    r'net[/.]minecraft[/.]client(?:[/.]|$)|'
    r'net[/.]minecraftforge[/.]client|'
    r'onlyClient|client-only|client only', re.I)


def parse_log_evidence(text: str) -> dict:
    """从日志文本里提取「点名 Mod」的证据。

    返回 ``{'mods': {modId: {'errors': [...], 'reasons': [...]}},
             'clientOnly': bool}``。

    注意:这里只认**上下文**——一个 ``-- MOD x --`` 只有在附近出现类加载错误时
    才算高级别证据,避免把无害的堆栈片段当成结论。
    """
    lines = (text or '').split('\n')
    mods: dict[str, dict] = {}
    current = None
    for line in lines:
        match = _MOD_LINE.match(line)
        if match:
            name = match.group(1)
            if name.casefold() in _MOD_LINE_SKIP:
                current = None      # 框架段落标题,不是某个 Mod
                continue
            current = name
            mods.setdefault(current, {'errors': [], 'reasons': []})
            continue
        failure = _LOAD_FAIL.search(line)
        if failure:
            clause = failure.group(1)
            if clause:
                inside = _FAIL_BRACKET.search(clause)
                named = inside.group(1) if inside else clause.strip()
            else:
                named = failure.group(2)
            if named and named.casefold() not in _MOD_LINE_SKIP:
                mods.setdefault(named, {'errors': [], 'reasons': []})
                mods[named]['reasons'].append('加载器报告该 Mod 加载失败')
            continue
        if current and _CLASS_ERROR.search(line):
            message = line.strip()[:200]
            if message not in mods[current]['errors']:
                mods[current]['errors'].append(message)
    return {'mods': mods,
            'clientOnly': bool(_CLIENT_TRACE.search(text or ''))}


def strip_mod_id(mod_id: str) -> str:
    """去掉中文显示前缀:``[FTB任务] ftb-quests-2001.jar`` → ``ftb-quests-2001.jar``。

    前缀在**中间**(后面还有文件名),所以用 ``]`` 的位置切分,不能要求串以 ``]`` 结尾。
    """
    value = str(mod_id or '').strip()
    if '[' in value and ']' in value and value.index(']') > value.index('['):
        value = value[value.index(']') + 1:]
    return value.strip()


def match_evidence_to_files(evidence: dict, mods: list) -> dict:
    """把日志里的 modId 证据对应到实际 Mod 文件。

    ``mods`` 为 ``[{'file','modId','name','disabled','environment','description'}]``。
    先按 modId 精确匹配;再按文件名(去掉中文前缀)模糊兜底,因为崩溃报告里
    也可能是文件显示名而非 modId。
    """
    by_id = {}
    by_loose = {}
    for item in mods:
        if item.get('modId'):
            by_id.setdefault(item['modId'].casefold(), item)
        loose = strip_mod_id(item['file']).casefold()
        by_loose.setdefault(loose, item)
        for token in re.split(r'[-_. ]+', loose):
            if len(token) >= 4:
                by_loose.setdefault(token, item)

    matched = {}
    for mod_id, detail in (evidence.get('mods') or {}).items():
        key = mod_id.casefold()
        item = by_id.get(key)
        if item is None:
            item = by_loose.get(strip_mod_id(mod_id).casefold())
        if item is None:
            item = by_loose.get(key)
        if item is not None:
            matched[item['file']] = detail
    return matched


def build_diagnosis(mods: list, log_text: str = '') -> dict:
    """合并「日志证据 + Mod 元数据」→ 建议清单(不改动任何文件)。

    返回 ``{'suggestions': [...], 'notes': [...]}``;每条建议含
    ``file/name/description/level/reason``。
    """
    evidence = parse_log_evidence(log_text)
    matched = match_evidence_to_files(evidence, mods)
    suggestions = []

    for item in mods:
        # 已停用的 Mod 不可能再导致本次崩溃:日志里的条目多是历史遗留,直接跳过。
        if item.get('disabled'):
            continue
        detail = matched.get(item['file'])
        if detail and detail.get('errors'):
            trace = detail['errors'][0]
            reason = '日志中该类加载失败'
            if _CLIENT_TRACE.search(trace):
                reason = '日志显示它在服务端引用了客户端类'
            suggestions.append({
                'file': item['file'], 'name': item.get('name') or item['file'],
                'description': item.get('description') or '',
                'level': 'high', 'reason': reason, 'evidence': trace,
            })
            continue
        if (item.get('environment') or '').casefold() == 'client':
            suggestions.append({
                'file': item['file'], 'name': item.get('name') or item['file'],
                'description': item.get('description') or '',
                'level': 'medium',
                'reason': 'Mod 元数据声明仅客户端',
                'evidence': '',
            })
            continue
        if detail:
            suggestions.append({
                'file': item['file'], 'name': item.get('name') or item['file'],
                'description': item.get('description') or '',
                'level': 'low',
                'reason': detail['reasons'][0] if detail.get('reasons')
                          else '日志提到该 Mod 但证据不足',
                'evidence': '',
            })

    order = {'high': 0, 'medium': 1, 'low': 2}
    suggestions.sort(key=lambda row: (order.get(row['level'], 9),
                                      row['file'].casefold()))
    notes = []
    if not suggestions:
        notes.append('没有发现需要停用的 Mod 证据。')
    if not log_text:
        notes.append('未提供日志,只能依据 Mod 元数据声明的适用端判断。')
    if any(row['level'] == 'low' for row in suggestions):
        notes.append('标为「待复核」的条目证据不足,可能是前置缺失或版本不匹配,'
                     '不要仅凭此停用。')
    return {'suggestions': suggestions, 'notes': notes,
            'clientOnlyTrace': evidence.get('clientOnly', False)}


LEVEL_LABEL = {'high': '确定', 'medium': '很可能', 'low': '待复核'}


def suggestions_to_markdown(result: dict, limit: int = 40) -> str:
    """把诊断结果排成 Markdown 表格:左侧 Mod,右侧说明。

    ``chat_view`` 会把它渲染成真表格;模型自己读到的也是规整文本。
    """
    rows = (result.get('suggestions') or [])[:limit]
    lines = []
    if not rows:
        return '没有发现需要停用的 Mod 证据。'
    lines.append('建议停用的服务端 Mod(左:文件 / 右:说明)')
    lines.append('| Mod | 说明 |')
    lines.append('| --- | --- |')
    for row in rows:
        parts = [f"**{LEVEL_LABEL.get(row['level'], row['level'])}**"]
        parts.append(row['reason'])
        if row.get('description'):
            parts.append(row['description'])
        lines.append(f"| {row['file']} | {' · '.join(parts)} |")
    if len(result.get('suggestions') or []) > limit:
        lines.append(f"| … | 另有 {len(result['suggestions']) - limit} 项未列出 |")
    for note in result.get('notes') or []:
        lines.append('')
        lines.append(f"提示:{note}")
    return '\n'.join(lines)
