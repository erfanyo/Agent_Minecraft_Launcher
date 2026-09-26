# -*- coding: utf-8 -*-
"""Display declared Minecraft versions per loader from resource file records."""

import re


LOADER_NAMES = {
    'forge': 'Forge', 'neoforge': 'NeoForge', 'fabric': 'Fabric',
    'quilt': 'Quilt', 'iris': 'Iris', 'optifine': 'OptiFine',
    'minecraft': '原版', 'vanilla': '原版', 'datapack': '数据包',
    'resourcepack': '资源包',
}
_PREFERRED = ('forge', 'neoforge', 'fabric')


def _version_key(version: str):
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.split(r'(\d+)', version))


def format_compatibility(versions: list[dict], *, partial: bool = False,
                         source: str = 'modrinth') -> tuple[str, str]:
    """Return compact detail text and a tooltip with all declared versions.

    Endpoints are shown only with a count; they never imply all intermediate
    Minecraft versions work. Source data is the version/file record, not the
    project's independent loader and game-version unions.
    """
    groups: dict[str, set[str]] = {}
    for item in versions or []:
        if not isinstance(item, dict):
            continue
        game_versions = {str(value).strip() for value in item.get('game_versions') or []
                         if str(value).strip()}
        if not game_versions:
            continue
        loaders = item.get('loaders') or ['未注明加载器']
        for loader in loaders:
            key = str(loader).strip().lower() or '未注明加载器'
            groups.setdefault(key, set()).update(game_versions)

    if not groups:
        return '兼容范围：没有找到文件级版本声明', ''

    keys = [key for key in _PREFERRED if key in groups]
    keys.extend(sorted(key for key in groups if key not in _PREFERRED))
    lines = ['兼容范围 · 部分可能不支持']
    full = ['各文件声明的游戏版本（不是连续区间）：']
    for key in keys:
        label = LOADER_NAMES.get(key, key if key == '未注明加载器' else key.title())
        values = sorted(groups[key], key=_version_key, reverse=True)
        if len(values) <= 7:
            display = '、'.join(values)
        else:
            display = f'{values[0]} ～ {values[-1]}（共 {len(values)} 个）'
        lines.append(f'{label}：{display}')
        full.append(f'{label}：' + '、'.join(values))
    if partial:
        note = 'CurseForge 文件较多，仅统计已读取的最近文件；更早版本可能未显示。'
        lines.append(note)
        full.append(note)
    elif source == 'curseforge':
        lines.append('依据 CurseForge 文件标签，未标注的兼容性不作推断。')
    return '\n'.join(lines), '\n'.join(full)
