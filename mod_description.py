# -*- coding: utf-8 -*-
"""Mod 描述补全:给「建议停用清单」右侧那一列提供可读说明。

优先级(便宜的先用,网络只在前两者都给不出时用):

1. JAR 元数据自带的 ``description``(本地读取,离线可用)
2. Modrinth 项目简介(按 modId 或去中文前缀的文件名反查)
3. 机翻成中文(复用 ``mod_translate``;失败就保留原文并标注)

任何一步失败都不抛异常——描述缺失只是表格少一列内容,不该让诊断整体失败。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from mod_deps import read_mod_metadata


def _local_description(jar_path: str) -> tuple:
    """→ (name, description);读不出来返回空串。"""
    try:
        info = read_mod_metadata(jar_path) or {}
    except Exception:
        return '', ''
    return (str(info.get('name') or ''), str(info.get('description') or '').strip())


def _modrinth_description(mod_id: str, file_name: str) -> str:
    """用 modId / 文件名反查 Modrinth 简介;查不到返回空串。"""
    try:
        from modrinth import get_project
    except Exception:
        return ''
    for candidate in _project_candidates(mod_id, file_name):
        try:
            project = get_project(candidate)
        except Exception:
            continue
        if not isinstance(project, dict):
            continue
        description = str(project.get('description') or '').strip()
        title = str(project.get('title') or '').strip()
        if description:
            return f'{title}:{description}' if title else description
    return ''


def _project_candidates(mod_id: str, file_name: str) -> list:
    """按可信度给出待查 slug:先是 modId,再是去掉修饰的文件名前缀。"""
    out = []
    for value in (mod_id, _stem_hint(file_name)):
        cleaned = str(value or '').strip().lower()
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


def _stem_hint(file_name: str) -> str:
    """``[FTB任务] ftb-quests-forge-2001.4.22.jar`` → ``ftb-quests``。

    只做到「去掉版本号之前的那一段」,不追求精确:后面还有 Modrinth 校验,
    查不到就当没有,不会写错描述。
    """
    name = str(file_name or '')
    if ']' in name:
        name = name.split(']', 1)[1]
    name = name.rsplit('.', 1)[0]
    for suffix in ('.disabled',):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    parts = name.split('-')
    keep = []
    for part in parts:
        if part and part[0].isdigit():
            break
        keep.append(part)
    return '-'.join(keep) if keep else name


def describe_mod(mod_id: str, file_name: str, jar_path: str) -> dict:
    """给一个 Mod 取说明。返回 ``{'name','description','source'}``,失败留空。"""
    name, description = _local_description(jar_path)
    source = 'jar' if description else ''
    if not description:
        description = _modrinth_description(mod_id, file_name)
        if description:
            source = 'modrinth'
    if description:
        description = _maybe_translate(description, mod_id)
    return {'file': file_name, 'name': name or file_name,
            'description': description, 'source': source or 'none'}


def _maybe_translate(text: str, slug: str) -> str:
    """英文简介机翻成中文;任何异常都原文返回(描述缺失不该炸诊断)。"""
    try:
        from mod_translate import translate_text_safe
    except Exception:
        return text
    try:
        result = translate_text_safe(text, slug=slug or 'mod', field='description')
    except Exception:
        return text
    if not isinstance(result, dict):
        return text
    translated = str(result.get('text') or '').strip()
    if not translated:
        return text
    if result.get('translated') and result.get('machine'):
        return translated
    return translated or text


def annotate_mods(mods: list, worker=None, max_workers: int = 6) -> list:
    """给 Mod 列表并发补上 description(仅补缺失的,已有的不覆盖)。

    ``mods`` 形如 ``[{'file','modId','description','path'}]``,返回同结构新列表。
    网络查询走线程池,避免逐个串行等待把界面卡住。
    """
    targets = [item for item in mods if not str(item.get('description') or '').strip()]
    if not targets:
        return mods
    results = {}
    runner = worker or _run_describe
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(targets)))) as pool:
        futures = {pool.submit(runner, item): item for item in targets}
        for future in as_completed(futures):
            item = futures[future]
            try:
                results[item['file']] = future.result()
            except Exception:
                results[item['file']] = {'description': '', 'source': 'none'}
    out = []
    for item in mods:
        filled = dict(item)
        got = results.get(item['file'])
        if got:
            filled['description'] = filled.get('description') or got.get('description') or ''
            if got.get('name') and not filled.get('name'):
                filled['name'] = got['name']
            filled['descriptionSource'] = got.get('source') or 'none'
        out.append(filled)
    return out


def _run_describe(item: dict) -> dict:
    return describe_mod(item.get('modId') or '', item.get('file') or '',
                        item.get('path') or '')
