"""Build launcher context from data snapshots, without reading any widgets."""
from launcher_app.ai.ai_actions import permission_instructions, plain_language_instructions


def launcher_context(settings, instance, language, skill_hints=()):
    if language == 'en':
        language_instruction = ('Reply in English by default. Keep technical terms, command names, '
            'Mod/instance IDs, paths and error messages in their original form (do not force-translate them).')
    else:
        language_instruction = ('默认用中文回答。Mod 名、命令、实例 id、路径、报错等专业/英文术语保留原样,'
                                '不要强行翻译。')
    lines = ['你是 Agent Minecraft Launcher 启动器里内置的 AI 助手。', language_instruction,
        f"启动器设置: 离线游戏名 {settings.get('username', 'Player')},"
        f" 内存 {str(settings.get('memory_gb')) + 'G' if settings.get('memory_gb') else '自动（按可用内存）'},"
        f" 版本隔离 {'开' if settings.get('version_isolation', True) else '关'}"]
    if instance:
        lines.append(f"当前选中的实例: {instance['id']}"
                     f"(加载器:{instance['loader'] or '原版'}, 基础版本:{instance['base']})")
    lines.extend((permission_instructions(settings), plain_language_instructions(settings)))
    lines.extend(skill_hints)
    return '\n'.join(lines)
