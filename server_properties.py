# -*- coding: utf-8 -*-
"""``server.properties`` 的结构化读写与可视化编辑所需的元数据。

**为什么单独成模块**:这个文件是服务端的「总开关」,但纯文本编辑极易改坏——少一个
空格、把 ``true`` 写成 ``True``、误删 ``level-name``,都可能让服务端起不来或**生成
一个全新的空世界**。所以这里把「解析/序列化」做成纯函数并配单测,UI 只负责填表单。

设计要点:

1. **保留未知键与注释**。Minecraft 会写入自己的键,Mod/插件也会追加键;编辑器只改
   用户动过的项,其余原样保留(未知键照原顺序写回),避免"用启动器存一次就丢配置"。
2. **编码按规范**:``server.properties`` 官方是 ISO-8859-1(即 latin-1)。我们读写都走
   latin-1,遇到非 latin-1 字符(如中文 motd)用 ``errors='replace'`` 兜底而不是崩溃。
3. **无副作用**:本模块不写文件、不备份——落盘与备份属于 :mod:`server_properties_io`。
"""
from __future__ import annotations

import re

# 值类型
BOOL, INT, STR = 'bool', 'int', 'str'

# 分组(仅用于 UI 归类)
GROUP_NETWORK = '网络与连接'
GROUP_GAME = '游戏规则'
GROUP_WORLD = '世界生成'
GROUP_PLAYER = '玩家与权限'
GROUP_SECURITY = '安全与运维'
GROUP_ADVANCED = '性能与高级'

#: 已知键目录。``default`` 仅用于「恢复默认」按钮,不代表我们会写入。
CATALOG = [
    # ---- 网络与连接 ----
    dict(key='server-port', type=INT, default='25565', group=GROUP_NETWORK,
         label='服务器端口', hint='玩家连接用端口。改完需重启服务端，并在防火墙放行。'),
    dict(key='server-ip', type=STR, default='', group=GROUP_NETWORK,
         label='绑定 IP', hint='留空 = 监听所有网卡。一般不要填。'),
    dict(key='online-mode', type=BOOL, default='true', group=GROUP_NETWORK,
         label='正版验证',
         hint='true = 只允许正版账号；false = 允许离线(盗版)账号登录。'
              '关闭后任何人可用任意 ID 进入，且无法防冒充。', danger=True),
    dict(key='max-players', type=INT, default='20', group=GROUP_NETWORK,
         label='最大玩家数', hint='同时在线人数上限。'),
    dict(key='motd', type=STR, default='A Minecraft Server', group=GROUP_NETWORK,
         label='服务器标语', hint='多人列表里显示的一句话。支持 § 颜色代码。'),
    dict(key='enable-status', type=BOOL, default='true', group=GROUP_NETWORK,
         label='允许查询状态', hint='关闭后多人列表看不到在线人数/标语。'),
    dict(key='network-compression-threshold', type=INT, default='256',
         group=GROUP_NETWORK, label='网络压缩阈值',
         hint='字节；-1 = 关闭压缩。改小省带宽、费 CPU。'),
    dict(key='query.port', type=INT, default='25565', group=GROUP_NETWORK,
         label='Query 查询端口', hint='第三方查询协议端口。'),

    # ---- 玩家与权限 ----
    dict(key='white-list', type=BOOL, default='false', group=GROUP_PLAYER,
         label='启用白名单', hint='开启后只有 whitelist.json 里的玩家能进。'),
    dict(key='enforce-whitelist', type=BOOL, default='false', group=GROUP_PLAYER,
         label='强制踢出不在白名单的在线玩家',
         hint='开启后，被移出白名单的在线玩家会被立即踢下线。'),
    dict(key='gamemode', type=STR, default='survival', group=GROUP_PLAYER,
         label='默认游戏模式',
         hint='survival / creative / adventure / spectator。'),
    dict(key='force-gamemode', type=BOOL, default='false', group=GROUP_PLAYER,
         label='每次登录强制套用游戏模式',
         hint='开启后玩家每次进服都会被重置为上面的模式。'),
    dict(key='difficulty', type=STR, default='easy', group=GROUP_PLAYER,
         label='难度', hint='peaceful / easy / normal / hard。'),
    dict(key='hardcore', type=BOOL, default='false', group=GROUP_PLAYER,
         label='极限模式', hint='死亡后自动变为旁观者，不可复活。', danger=True),
    dict(key='pvp', type=BOOL, default='true', group=GROUP_PLAYER,
         label='允许玩家互相伤害', hint='关闭即禁止 PVP。'),
    dict(key='player-idle-timeout', type=INT, default='0', group=GROUP_PLAYER,
         label='挂机踢出(分钟)', hint='0 = 不踢。'),
    dict(key='op-permission-level', type=INT, default='4', group=GROUP_PLAYER,
         label='OP 权限等级', hint='1~4；4 = 完全控制。'),
    dict(key='allow-flight', type=BOOL, default='false', group=GROUP_PLAYER,
         label='允许飞行',
         hint='生存模式下若未开启，长时间滞空可能被判定为作弊踢出。'),

    # ---- 世界生成 ----
    dict(key='level-name', type=STR, default='world', group=GROUP_WORLD,
         label='世界文件夹名',
         hint='服务端读取/创建的存档目录名。改错会生成一个全新空世界！',
         danger=True),
    dict(key='level-seed', type=STR, default='', group=GROUP_WORLD,
         label='世界种子', hint='仅对尚未生成的世界生效。'),
    dict(key='level-type', type=STR, default='minecraft:normal', group=GROUP_WORLD,
         label='世界类型',
         hint='如 minecraft:normal / flat / large_biomes / amplified，'
              'Mod 也可能注册自己的类型。', danger=True),
    dict(key='generator-settings', type=STR, default='{}', group=GROUP_WORLD,
         label='生成器参数', hint='超平坦等的 JSON 参数。', danger=True),
    dict(key='max-world-size', type=INT, default='29999984', group=GROUP_WORLD,
         label='世界边界半径', hint='方块。'),
    dict(key='spawn-protection', type=INT, default='16', group=GROUP_WORLD,
         label='出生点保护半径', hint='0 = 关闭保护。'),
    dict(key='allow-nether', type=BOOL, default='true', group=GROUP_WORLD,
         label='允许下界', hint='关闭后无法前往下界。'),
    dict(key='generate-structures', type=BOOL, default='true', group=GROUP_WORLD,
         label='生成结构', hint='村庄/神殿等。仅影响未生成的区块。'),

    # ---- 游戏规则 ----
    dict(key='spawn-monsters', type=BOOL, default='true', group=GROUP_GAME,
         label='生成怪物', hint='关闭后不自然生成敌对生物。'),
    dict(key='spawn-animals', type=BOOL, default='true', group=GROUP_GAME,
         label='生成动物', hint=''),
    dict(key='spawn-npcs', type=BOOL, default='true', group=GROUP_GAME,
         label='生成村民', hint=''),
    dict(key='allow-command-block', type=BOOL, default='false', group=GROUP_GAME,
         label='启用命令方块', hint=''),
    dict(key='enable-command-block', type=BOOL, default='true', group=GROUP_GAME,
         label='命令方块可用(别名键)', hint='部分版本读这个键，两个都开着最稳。'),
    dict(key='function-permission-level', type=INT, default='2', group=GROUP_GAME,
         label='函数/数据包权限等级', hint='1~4。'),

    # ---- 安全与运维 ----
    dict(key='enable-rcon', type=BOOL, default='false', group=GROUP_SECURITY,
         label='启用 RCON 远程控制', hint='开启后可用外部工具发指令。', danger=True),
    dict(key='rcon.port', type=INT, default='25575', group=GROUP_SECURITY,
         label='RCON 端口', hint=''),
    dict(key='rcon.password', type=STR, default='', group=GROUP_SECURITY,
         label='RCON 密码', hint='留空且启用 RCON 会导致启动失败。请设置强密码。',
         secret=True, danger=True),
    dict(key='enable-query', type=BOOL, default='false', group=GROUP_SECURITY,
         label='启用 Query 查询', hint=''),
    dict(key='enforce-secure-profile', type=BOOL, default='true',
         group=GROUP_SECURITY, label='强制安全聊天签名',
         hint='关闭后正版玩家也可能被标记为不安全聊天。'),
    dict(key='prevent-proxy-connections', type=BOOL, default='false',
         group=GROUP_SECURITY, label='阻止代理连接', hint=''),
    dict(key='rate-limit', type=INT, default='0', group=GROUP_SECURITY,
         label='数据包限流', hint='0 = 关闭。'),
    dict(key='max-tick-time', type=INT, default='60000', group=GROUP_SECURITY,
         label='单 tick 超时(ms)', hint='-1 = 关闭看门狗。卡顿排查时可临时调大。'),
    dict(key='view-distance', type=INT, default='10', group=GROUP_SECURITY,
         label='视距(区块)', hint='3~32。越大越吃内存/CPU。'),
    dict(key='simulation-distance', type=INT, default='10', group=GROUP_SECURITY,
         label='模拟距离(区块)', hint='实体/方块更新的范围。'),

    # ---- 性能与高级 ----
    dict(key='sync-chunk-writes', type=BOOL, default='true', group=GROUP_ADVANCED,
         label='同步写区块', hint='关闭可提升性能，但断电时更容易损坏存档。'),
    dict(key='max-build-height', type=INT, default='320', group=GROUP_ADVANCED,
         label='最大建筑高度', hint='一般不要改。'),
    dict(key='entity-broadcast-range-percentage', type=INT, default='100',
         group=GROUP_ADVANCED, label='实体同步范围(%)',
         hint='降低可省带宽(1.18+ 有效)。'),
    dict(key='hide-online-players', type=BOOL, default='false', group=GROUP_ADVANCED,
         label='隐藏在线玩家列表', hint=''),
    dict(key='broadcast-console-to-ops', type=BOOL, default='true',
         group=GROUP_ADVANCED, label='把控制台输出广播给 OP', hint=''),
    dict(key='broadcast-rcon-to-ops', type=BOOL, default='true',
         group=GROUP_ADVANCED, label='把 RCON 输出广播给 OP', hint=''),
    dict(key='log-ips', type=BOOL, default='true', group=GROUP_ADVANCED,
         label='日志记录玩家 IP', hint=''),
    dict(key='text-filtering-config', type=STR, default='', group=GROUP_ADVANCED,
         label='聊天过滤配置', hint='一般留空。'),
    dict(key='initial-enabled-packs', type=STR, default='vanilla',
         group=GROUP_ADVANCED, label='初始启用的数据包', hint=''),
    dict(key='initial-disabled-packs', type=STR, default='', group=GROUP_ADVANCED,
         label='初始禁用的数据包', hint=''),
]

CATALOG_BY_KEY = {item['key']: item for item in CATALOG}
GROUP_ORDER = [GROUP_NETWORK, GROUP_PLAYER, GROUP_WORLD, GROUP_GAME,
               GROUP_SECURITY, GROUP_ADVANCED]

#: 允许的取值(用于校验;不在表内的键按类型宽松校验)
ENUMS = {
    'gamemode': {'survival', 'creative', 'adventure', 'spectator'},
    'difficulty': {'peaceful', 'easy', 'normal', 'hard'},
}

_TRUE = {'true', '1', 'yes', 'on'}
_FALSE = {'false', '0', 'no', 'off'}

_LINE_RE = re.compile(r'^\s*(?P<key>[^#!\s][^=\s]*)\s*=\s*(?P<value>.*)$')


def parse(text: str) -> list:
    """解析 ``server.properties`` → 有序记录列表。

    每项形如 ``{'kind','key','value','raw'}``:
    - ``kind='entry'``:普通键值对(``key``/``value`` 已去首尾空白)
    - ``kind='comment'``:注释或空行,``raw`` 保存原文,写回时原样输出
    - ``kind='unknown'``:语法上不像键值对的行,同样按 ``raw`` 原样保留

    之所以记录 ``kind`` 而不是直接给 dict:必须能**原样回写**,否则编辑器保存一次
    就会丢掉注释和未知行。
    """
    records = []
    for line in (text or '').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('!'):
            records.append({'kind': 'comment', 'key': '', 'value': '', 'raw': line})
            continue
        match = _LINE_RE.match(line)
        if not match:
            records.append({'kind': 'unknown', 'key': '', 'value': '', 'raw': line})
            continue
        records.append({'kind': 'entry', 'key': match.group('key'),
                        'value': match.group('value').strip(), 'raw': line})
    return records


def serialize(records: list) -> str:
    """把 :func:`parse` 的结果写回文本,保留注释/未知行与原有顺序。"""
    lines = []
    for record in records or []:
        if record.get('kind') == 'entry':
            lines.append(f"{record.get('key', '')}={record.get('value', '')}")
        else:
            lines.append(record.get('raw', ''))
    return '\n'.join(lines) + '\n'


def as_dict(records: list) -> dict:
    """取键值映射(同名键后出现者覆盖前者,与 Minecraft 读取行为一致)。"""
    out = {}
    for record in records or []:
        if record.get('kind') == 'entry':
            out[record['key']] = record.get('value', '')
    return out


def _find(records: list, key: str):
    """返回该键**最后**一条 entry 记录(与 Minecraft 取值规则一致)。"""
    found = None
    for record in records or []:
        if record.get('kind') == 'entry' and record.get('key') == key:
            found = record
    return found


def set_values(records: list, values: dict) -> list:
    """在解析结果上套用改动;已存在的键就地改,不存在的新键追加到末尾。

    不修改传入的列表(返回新列表),便于 UI 做「预览改动后差异」。
    """
    out = [dict(record) for record in (records or [])]
    pending = dict(values or {})
    for record in out:
        if record.get('kind') == 'entry' and record.get('key') in pending:
            key = record['key']
            record['value'] = _stringify(pending.pop(key))
    for key, value in pending.items():
        out.append({'kind': 'entry', 'key': key, 'value': _stringify(value),
                    'raw': f'{key}={_stringify(value)}'})
    return out


def _stringify(value) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return '' if value is None else str(value)


def normalise_bool(value: str):
    """把各种写法归一成 ``'true'``/``'false'``;无法识别返回 None。

    Minecraft 自己认 ``true``/``false``,但社区文件里常见 ``1``/``yes``/``on``。
    我们**只读时宽容**、**写回时统一成 true/false**,避免写出服务端不认的值。
    """
    text = str(value or '').strip().casefold()
    if text in _TRUE:
        return 'true'
    if text in _FALSE:
        return 'false'
    return None


def validate(key: str, value: str):
    """校验一个键值 → ``(ok, message)``;message 为人类可读中文说明。"""
    item = CATALOG_BY_KEY.get(key)
    raw = '' if value is None else str(value)
    kind = (item or {}).get('type', STR)

    if kind == BOOL:
        if normalise_bool(raw) is None:
            return False, f"应为 true 或 false，当前是 “{raw}”"
        return True, ''
    if kind == INT:
        text = raw.strip()
        if not re.fullmatch(r'-?\d+', text or ''):
            return False, f"应为整数，当前是 “{raw}”"
        number = int(text)
        if key in ('server-port', 'query.port', 'rcon.port') and not (1 <= number <= 65535):
            return False, '端口需在 1~65535 之间'
        if key == 'max-players' and number < 1:
            return False, '至少为 1'
        if key == 'player-idle-timeout' and number < 0:
            return False, '不能为负数'
        if key == 'view-distance' and not (3 <= number <= 32):
            return False, '建议在 3~32 之间'
        if key == 'simulation-distance' and not (3 <= number <= 32):
            return False, '建议在 3~32 之间'
        if key == 'op-permission-level' and not (1 <= number <= 4):
            return False, '需在 1~4 之间'
        if key == 'spawn-protection' and number < 0:
            return False, '不能为负数'
        return True, ''
    allowed = ENUMS.get(key)
    if allowed and raw.strip().casefold() not in allowed:
        return False, '可选值：' + ' / '.join(sorted(allowed))
    return True, ''


def validate_all(values: dict) -> list:
    """批量校验 → ``[(key, message), ...]``;空列表表示全部通过。"""
    problems = []
    for key, value in (values or {}).items():
        ok, message = validate(key, value)
        if not ok:
            problems.append((key, message))
    return problems


def label_for(key: str) -> str:
    """键的中文名(未知键回落为键名本身)。"""
    item = CATALOG_BY_KEY.get(key)
    return (item or {}).get('label') or key


def hint_for(key: str) -> str:
    """键的说明(未知键返回空串)。"""
    return (CATALOG_BY_KEY.get(key) or {}).get('hint', '')


def is_dangerous(key: str) -> bool:
    """改错可能导致「起不来 / 丢档 / 生成新世界」的键。"""
    return bool((CATALOG_BY_KEY.get(key) or {}).get('danger'))


def is_secret(key: str) -> bool:
    """含敏感值(如 RCON 密码)的键——落盘备份/报告时要脱敏。"""
    return bool((CATALOG_BY_KEY.get(key) or {}).get('secret'))


def known_keys() -> set:
    return set(CATALOG_BY_KEY)
