"""Summarize an already inspected archive without executing package contents."""
from pathlib import PurePosixPath


def review_inspection(inspection):
    files = list((inspection.get('files') or {}).keys())
    names = [name.replace('\\', '/').casefold() for name in files]
    executable_extensions = {'.exe', '.msi', '.dll', '.com', '.scr', '.vbs', '.ps1', '.bat', '.cmd', '.sh', '.py', '.js'}
    executable = [name for name in files if PurePosixPath(name).suffix.casefold() in executable_extensions]
    # These are structural hints, not trusted manifests or a promise of compatibility.
    basename = {PurePosixPath(name).name for name in names}
    manifests = bool({'modrinth.index.json', 'manifest.json'} & basename)
    content = any(name.startswith(('mods/', '.minecraft/mods/', 'versions/')) or
                  '/mods/' in name or '/.minecraft/' in name for name in names)
    server = inspection.get('kind') == 'server'
    kind = 'server-candidate' if server else 'modpack-candidate' if manifests or content else 'unknown-archive'
    warnings = ['结构与完整性检查不是杀毒扫描，不能证明代码无害；不会运行包内文件或自动导入。']
    if kind == 'unknown-archive':
        warnings.append('未识别到足够的 Minecraft 整合包结构，可能是软件发布包或其他压缩包，请人工确认。')
    if executable:
        warnings.append('包含程序或脚本，只作静态列举；整合包中的模组 JAR 本身也属于可执行代码。')
    return {'kind': kind, 'structure_checked': True, 'malware_free_verified': False,
            'executable_or_script_count': len(executable), 'executable_or_script_examples': executable[:20],
            'warnings': warnings}
