# -*- coding: utf-8 -*-
"""
指令中心模板库(skill):覆盖常用游戏指令 + NBT 场景。
- 模板里的 {arg} 是待填参数,UI 填参后替换;args 列表给参数说明
- 省 token:AI/用户从库里选模板填参,而不是让 AI 现编指令
- 实例管理对话框「指令库」tab 使用;每实例可保存自定义指令(独立 JSON)
- 部分 mod 会加额外标签/指令:模板里留了通用 {nbt}/{custom} 插槽,
  实例自定义库里可补充 mod 专属指令
"""
COMMAND_TEMPLATES = {
    "天气/时间": [
        ("天气 → 晴天", "weather clear", []),
        ("天气 → 雨天", "weather rain", []),
        ("天气 → 雷暴", "weather thunder", []),
        ("时间 → 白天(0 点)", "time set day", []),
        ("时间 → 正午", "time set noon", []),
        ("时间 → 夜晚", "time set night", []),
        ("时间 → 午夜", "time set midnight", []),
        ("时间 → 增加", "time add {tick}",
         ["tick: 要增加的游戏刻(20 刻 = 1 秒)"]),
    ],
    "生成实体": [
        ("生成 → 僵尸", "summon zombie ~ ~ ~", []),
        ("生成 → 苦力怕", "summon creeper ~ ~ ~", []),
        ("生成 → 骷髅", "summon skeleton ~ ~ ~", []),
        ("生成 → 凋灵", "summon wither ~ ~ ~", []),
        ("生成 → 末影龙", "summon ender_dragon ~ ~ ~", []),
        ("生成 → 铁傀儡", "summon iron_golem ~ ~ ~", []),
        ("生成任意实体", "summon {entity} ~ ~ ~",
         ["entity: 实体 id,如 zombie / villager / evoker"]),
        ("生成带 NBT 的实体", "summon {entity} ~ ~ ~ {nbt}",
         ["entity: 实体 id",
          "nbt: JSON 标签,如 {CustomName:'\"小明\"',PersistenceRequired:1b}"]),
        ("生成指定职业村民", "summon villager ~ ~ ~ {VillagerData:{profession:'{profession}'}}",
         ["profession: farmer / fisherman / librarian / armoror / cleric / butcher / cartographer / "
          "fletcher / leatherworker / librarian / mason / shepherd / toolsmith / weaponsmith / nitwit"]),
        ("生成带装备的僵尸(钻石套+剑)", "summon zombie ~ ~ ~ "
         "{HandItems:[{id:'diamond_sword',Count:1},{}],"
         "ArmorItems:[{id:'diamond_boots',Count:1},{id:'diamond_leggings',Count:1},"
         "{id:'diamond_chestplate',Count:1},{id:'diamond_helmet',Count:1}]}",
         []),
        ("生成发光史莱姆", "summon slime ~ ~ ~ {Size:3,Glowing:1b}", []),
    ],
    "附魔/物品": [
        ("附魔 → 锋利 V 钻石剑", "give @p diamond_sword 1 {Enchantments:[{id:'sharpness',lvl:5}]}", []),
        ("附魔 → 保护 IV 胸甲", "give @p netherite_chestplate 1 {Enchantments:[{id:'protection',lvl:4}]}", []),
        ("附魔 → 效率 V + 时运 III 镐", "give @p netherite_pickaxe 1 "
         "{Enchantments:[{id:'efficiency',lvl:5},{id:'fortune',lvl:3}]}", []),
        ("附魔 → 精准采集 + 耐久 III 镐", "give @p netherite_pickaxe 1 "
         "{Enchantments:[{id:'silk_touch',lvl:1},{id:'unbreaking',lvl:3}]}", []),
        ("附魔 → 力量 V 弓", "give @p bow 1 {Enchantments:[{id:'power',lvl:5}]}", []),
        ("附魔任意物品", "give @p {item} 1 {Enchantments:[{id:'{ench}',lvl:{lvl}}]}",
         ["item: 物品 id,如 netherite_sword",
          "ench: 附魔 id,如 sharpness / efficiency / mending",
          "lvl: 等级"]),
        ("附魔书(存任意附魔)", "give @p enchanted_book 1 {StoredEnchantments:[{id:'{ench}',lvl:{lvl}}]}",
         ["ench: 附魔 id", "lvl: 等级"]),
        ("给任意物品 × N", "give @p {item} {count}",
         ["item: 物品 id", "count: 数量"]),
        ("给整套下界合金装备", "give @p netherite_helmet 1\ngive @p netherite_chestplate 1\n"
         "give @p netherite_leggings 1\ngive @p netherite_boots 1", []),
    ],
    "生物/玩家效果": [
        ("击杀 → 半径内实体", "kill @e[type={entity},distance=..{r}]",
         ["entity: 实体类型(如 zombie / @e 全部)", "r: 半径(格)"]),
        ("治愈 + 再生", "effect give @p regeneration 30 2", []),
        ("力量 II", "effect give @p strength 60 1", []),
        ("速度 II", "effect give @p speed 60 1", []),
        ("跳跃提升", "effect give @p jump_boost 60 2", []),
        ("夜视", "effect give @p night_vision 300 0", []),
        ("任意效果", "effect give @p {effect} {sec} {amp}",
         ["effect: 效果 id,如 strength / speed / resistance",
          "sec: 持续秒数", "amp: 等级-1(0=一级)"]),
        ("清除全部效果", "effect clear @p", []),
        ("传送玩家", "tp @p {x} {y} {z}", ["x y z: 坐标,可写 ~ 相对位置"]),
    ],
    "其他常用": [
        ("给予经验", "xp add @p {amount}", ["amount: 经验点数"]),
        ("游戏模式 → 创造", "gamemode creative @p", []),
        ("游戏模式 → 生存", "gamemode survival @p", []),
        ("游戏模式 → 冒险", "gamemode adventure @p", []),
        ("定位结构", "locate structure {structure}",
         ["structure: 如 village / fortress / ancient_city / stronghold"]),
        ("定位生物群系", "locate biome {biome}",
         ["biome: 如 plains / desert / cherry_grove"]),
        ("冻结/解冻生物(调试)", "tick freeze", []),
        ("显示实体计数", "list", []),
    ],
}


# ================= 版本感知的指令指南(给 AI 助手,重点:NBT 写法) =================
# 指令体系分水岭:
#   ≥1.20.5  : 物品数据从 NBT 改为「组件」(方括号语法);实体仍是 NBT
#   1.13-1.20.4: 1.13 指令大改版(新 /effect、/tp 等);物品/实体都用 NBT(花括号)
#   ≤1.12    : 旧指令;附魔/效果用数字 id;实体名大写;NBT 无命名空间

def _ver_tuple(version: str) -> tuple:
    """'1.21.1' → (1,21,1);'26.2' → (26,2)"""
    nums = []
    for part in str(version).split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            nums.append(int(digits))
        else:
            break
    return tuple(nums) if nums else (0,)


def version_bucket(mc_version: str) -> str:
    """返回版本分段:components(≥1.20.5) / modern_nbt(1.13-1.20.4) / legacy(≤1.12)"""
    t = _ver_tuple(mc_version)
    if t >= (1, 20, 5):
        return "components"
    if t >= (1, 13, 0):
        return "modern_nbt"
    return "legacy"


BUCKET_NAME = {
    "components": "现代(1.20.5+,物品组件)",
    "modern_nbt": "现代 NBT(1.13-1.20.4)",
    "legacy": "旧版(≤1.12,数字 id)",
}

# 每个版本分段的「指令要点」
BUCKET_SUMMARY = {
    "components": [
        "1.20.5+ 重大变化:物品数据用「组件」方括号语法,不再是 NBT 花括号",
        "give 附魔:/give @p minecraft:diamond_sword[minecraft:enchantments={levels:{\"minecraft:sharpness\":5}}]",
        "自定义名:/give @p minecraft:stick[minecraft:custom_name='\"我的棍子\"']",
        "实体(生物/玩家)仍是 NBT 花括号:/summon minecraft:zombie ~ ~ ~ {CustomName:'\"小明\"',NoAI:1b}",
        "附魔书:/give @p minecraft:enchanted_book[minecraft:stored_enchantments={levels:{\"minecraft:mending\":1}}]",
        "指令基础:summon/effect/time/weather/gamemode 等与 1.13+ 一致",
    ],
    "modern_nbt": [
        "1.13 指令大改版:effect 用 /effect give @p <效果> <秒> <等级-1>;/tp 坐标直接写",
        "物品附魔(花括号 NBT):/give @p minecraft:diamond_sword{Enchantments:[{id:\"minecraft:sharpness\",lvl:5}]}",
        "自定义名:/give @p minecraft:stick{CustomName:'\"我的棍子\"'}",
        "实体 NBT:/summon minecraft:zombie ~ ~ ~ {CustomName:'\"小明\"',PersistenceRequired:1b}",
        "村民职业:/summon minecraft:villager ~ ~ ~ {VillagerData:{profession:'librarian'}}",
        "实体装备:/summon minecraft:zombie ~ ~ ~ {ArmorItems:[{id:'minecraft:diamond_boots',count:1},{},{},{}],HandItems:[{id:'minecraft:diamond_sword',count:1},{}]}",
        "附魔书:/give @p minecraft:enchanted_book{StoredEnchantments:[{id:'minecraft:mending',lvl:1}]}",
    ],
    "legacy": [
        "1.12 及以前:附魔/效果用数字 id,实体名大写(如 Zombie / Villager)",
        "物品附魔:/give @p minecraft:diamond_sword 1 0 {ench:[{id:16s,lvl:5s}]}",
        "常用附魔数字:0保护 16锋利 17亡灵杀手 18节肢杀手 19击退 20火焰附加 21抢夺 22效率 23精准采集 24耐久 25时运 32力量 33冲击 34火矢 35无限 48经验修补",
        "效果数字:/effect @p 5 60 1(5=力量 1=速度 8=跳跃提升 10=抗性提升 11=抗火 12=水下呼吸)",
        "自定义名:/summon Zombie ~ ~ ~ {CustomName:\"小明\"}",
        "实体装备:/summon Zombie ~ ~ ~ {Equipment:[{id:276,Count:1},{id:310,Count:1},{},{},{}]}(0=主手 1=头盔 2=胸甲 3=护腿 4=靴子;物品用数字 id)",
        "坐标用 ~ ~ ~ 相对位置,选择器 @e[type=Zombie,r=5]",
    ],
}

# 每版本分段的核心模板(覆盖常用指令;NBT/组件写法已在上方要点里)
BUCKET_TEMPLATES = {
    "components": {
        "天气/时间": [
            ("天气 → 雨天", "weather rain", []),
            ("天气 → 晴天/雷暴", "weather clear|thunder", []),
            ("时间 → 白天/夜晚", "time set day|night", []),
        ],
        "生成实体": [
            ("生成僵尸", "summon minecraft:zombie ~ ~ ~", []),
            ("生成带名字的僵尸", "summon minecraft:zombie ~ ~ ~ {CustomName:'\"{name}\"',NoAI:0b}",
             ["name: 名字"]),
            ("生成指定职业村民", "summon minecraft:villager ~ ~ ~ {VillagerData:{profession:'{profession}'}}",
             ["profession: farmer/librarian/armorer/cleric 等"]),
            ("生成穿钻石套的僵尸", "summon minecraft:zombie ~ ~ ~ {HandItems:[{id:'minecraft:diamond_sword',count:1},{}],ArmorItems:[{id:'minecraft:diamond_boots',count:1},{id:'minecraft:diamond_leggings',count:1},{id:'minecraft:diamond_chestplate',count:1},{id:'minecraft:diamond_helmet',count:1}]}", []),
            ("生成任意实体带 NBT", "summon minecraft:{entity} ~ ~ ~ {nbt}",
             ["entity: 实体 id", "nbt: NBT 标签"]),
        ],
        "附魔/物品(组件)": [
            ("锋利 V 钻石剑", "give @p minecraft:diamond_sword[minecraft:enchantments={levels:{\"minecraft:sharpness\":5}}]", []),
            ("效率 V + 时运 III 镐", "give @p minecraft:netherite_pickaxe[minecraft:enchantments={levels:{\"minecraft:efficiency\":5,\"minecraft:fortune\":3}}]", []),
            ("保护 IV 全套胸甲", "give @p minecraft:netherite_chestplate[minecraft:enchantments={levels:{\"minecraft:protection\":4}}]", []),
            ("附魔书(经验修补)", "give @p minecraft:enchanted_book[minecraft:stored_enchantments={levels:{\"minecraft:mending\":1}}]", []),
            ("任意附魔", "give @p minecraft:{item}[minecraft:enchantments={levels:{\"minecraft:{ench}\":{lvl}}}]",
             ["item: 物品", "ench: 附魔 id", "lvl: 等级"]),
            ("给物品", "give @p minecraft:{item} {count}", ["item", "count"]),
        ],
        "效果/传送/其他": [
            ("力量 II", "effect give @p minecraft:strength 60 1", []),
            ("任意效果", "effect give @p minecraft:{effect} {sec} {amp}",
             ["effect: strength/speed/resistance 等", "sec: 秒", "amp: 等级-1"]),
            ("传送", "tp @p {x} {y} {z}", []),
            ("击杀半径内实体", "kill @e[type=minecraft:{entity},distance=..{r}]", ["entity", "r"]),
            ("定位结构", "locate structure {structure}", ["structure"]),
        ],
    },
    "modern_nbt": {
        "天气/时间": [
            ("天气 → 雨天", "weather rain", []),
            ("时间 → 白天/夜晚", "time set day|night", []),
        ],
        "生成实体": [
            ("生成僵尸", "summon minecraft:zombie ~ ~ ~", []),
            ("生成指定职业村民", "summon minecraft:villager ~ ~ ~ {VillagerData:{profession:'{profession}'}}",
             ["profession"]),
            ("生成穿钻石套的僵尸", "summon minecraft:zombie ~ ~ ~ {HandItems:[{id:'minecraft:diamond_sword',count:1},{}],ArmorItems:[{id:'minecraft:diamond_boots',count:1},{id:'minecraft:diamond_leggings',count:1},{id:'minecraft:diamond_chestplate',count:1},{id:'minecraft:diamond_helmet',count:1}]}", []),
            ("生成任意实体带 NBT", "summon minecraft:{entity} ~ ~ ~ {nbt}",
             ["entity", "nbt"]),
        ],
        "附魔/物品(NBT)": [
            ("锋利 V 钻石剑", "give @p minecraft:diamond_sword{Enchantments:[{id:'minecraft:sharpness',lvl:5}]}", []),
            ("效率 V + 时运 III 镐", "give @p minecraft:netherite_pickaxe{Enchantments:[{id:'minecraft:efficiency',lvl:5},{id:'minecraft:fortune',lvl:3}]}", []),
            ("附魔书(经验修补)", "give @p minecraft:enchanted_book{StoredEnchantments:[{id:'minecraft:mending',lvl:1}]}", []),
            ("任意附魔", "give @p minecraft:{item}{Enchantments:[{id:'minecraft:{ench}',lvl:{lvl}}]}",
             ["item", "ench", "lvl"]),
            ("给物品", "give @p minecraft:{item} {count}", ["item", "count"]),
        ],
        "效果/传送/其他": [
            ("力量 II", "effect give @p minecraft:strength 60 1", []),
            ("任意效果", "effect give @p minecraft:{effect} {sec} {amp}", ["effect", "sec", "amp"]),
            ("传送", "tp @p {x} {y} {z}", []),
            ("击杀半径内实体", "kill @e[type=minecraft:{entity},distance=..{r}]", ["entity", "r"]),
            ("定位结构", "locate structure {structure}", ["structure"]),
        ],
    },
    "legacy": {
        "天气/时间": [
            ("天气 → 雨天", "weather rain", []),
            ("时间 → 白天/夜晚", "time set day|night", []),
        ],
        "生成实体": [
            ("生成僵尸", "summon Zombie ~ ~ ~", []),
            ("生成指定职业村民", "summon Villager ~ ~ ~ {Profession:3,Career:2}", []),
            ("生成穿装备的僵尸", "summon Zombie ~ ~ ~ {Equipment:[{id:276,Count:1},{id:310,Count:1},{id:311,Count:1},{id:312,Count:1},{id:313,Count:1}]}", []),
            ("生成任意实体", "summon {entity} ~ ~ ~ {nbt}",
             ["entity: 大写名,如 Zombie/Skeleton/Creeper", "nbt"]),
        ],
        "附魔/物品(数字 id)": [
            ("锋利 V 钻石剑", "give @p minecraft:diamond_sword 1 0 {ench:[{id:16s,lvl:5s}]}", []),
            ("效率 V + 时运 III 镐", "give @p minecraft:diamond_pickaxe 1 0 {ench:[{id:22s,lvl:5s},{id:25s,lvl:3s}]}", []),
            ("附魔书(经验修补)", "give @p minecraft:enchanted_book 1 0 {StoredEnchantments:[{id:48s,lvl:1s}]}", []),
            ("给物品", "give @p minecraft:{item} {count}", ["item", "count"]),
        ],
        "效果/传送/其他": [
            ("力量 II", "effect @p 5 60 1", []),
            ("任意效果", "effect @p {id} {sec} {amp}",
             ["id: 效果数字(5=力量 1=速度 10=抗性提升)", "sec", "amp"]),
            ("传送", "tp @p {x} {y} {z}", []),
            ("击杀半径内实体", "kill @e[type={entity},r={r}]", ["entity", "r"]),
            ("定位结构", "locate {structure}", ["structure"]),
        ],
    },
}


def version_guide(mc_version: str, max_templates: int = 30) -> str:
    """给 AI 的版本指令指南文本:要点(NBT 重点) + 核心模板"""
    bucket = version_bucket(mc_version)
    name = BUCKET_NAME[bucket]
    lines = [f"【指令指南 {mc_version} → {name}】", "指令要点(NBT 写法重点):"]
    for note in BUCKET_SUMMARY[bucket]:
        lines.append("· " + note)
    lines.append("核心模板:")
    count = 0
    for cat, items in BUCKET_TEMPLATES[bucket].items():
        lines.append(f"— {cat}:")
        for tpl_name, tpl, _args in items:
            lines.append(f"  {tpl_name}: {tpl}")
            count += 1
            if count >= max_templates:
                break
        if count >= max_templates:
            break
    return "\n".join(lines)
