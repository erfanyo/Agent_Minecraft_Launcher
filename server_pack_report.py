"""Human- and machine-readable reports for candidate server builds."""
from __future__ import annotations

import json


def report_text(report):
    lines = [
        'AMCL 客户端实例 → 候选服务端审核报告',
        '',
        f"名称：{report['name']}",
        f"Minecraft：{report['minecraftVersion']}",
        f"加载器：{report['loader']} {report.get('loaderVersion') or ''}".rstrip(),
        f"验证状态：{report['verification']['label']}",
        '',
        '边界：',
        '- 原客户端实例仅以只读方式扫描，未在原目录写入或删除文件。',
        ('- AMCL 未替你接受 EULA；已使用隔离测试实例尝试启动，未部署正式服务器。'
         if report['verification'].get('level') in ('startup-tested', 'startup-attempted')
         else '- AMCL 未接受 EULA，也未启动或部署正式服务器。'),
        '- 仅排除有明确本地证据的客户端 Mod；未知项继续保留。',
        '- 顶层目录采用“宁多不少”：白名单之外的自定义目录（如 hotai、'
        'tlm_custom_pack）会被完整复制，只跳过启动器/个人数据。',
        '',
        '说明：',
        '自动导出服务端比较保守，会保留不少多余 mod/配置，精益求精的整合包作者'
        '应该会自己清理的，对吧？',
        '',
        'Mod 处理：',
    ]
    for item in report['mods']:
        mark = '排除' if item['action'] == 'excluded' else '保留'
        lines.append(f"- [{mark}] {item['name']} ({item['file']})：{item['reason']}")
    lines.extend(['', '警告：'])
    lines.extend('- ' + item for item in report.get('warnings') or ['无'])
    lines.extend([
        '',
        '下一步：',
        '1. 将候选包导入 AMCL 服务端列表。',
        '2. 在启动前阅读并由你本人确认 Minecraft EULA。',
        '3. 首次隔离启动，查看日志；对未知 Mod 逐项验证，不要批量删除。',
        '4. 确认可启动且功能正常后，再部署到正式服务器。',
        '',
        '还原：删除候选服务端目录或导出的候选 ZIP 即可；原客户端实例没有被修改。',
    ])
    return '\n'.join(lines) + '\n'


def report_json(report):
    return json.dumps(report, ensure_ascii=False, indent=2)
