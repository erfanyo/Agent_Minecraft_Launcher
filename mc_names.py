# -*- coding: utf-8 -*-
"""
MC 本地名称解析器:把用户口语/中文/英文叫法 → 规范 Minecraft 英文名 + id。

为什么需要:
  外部 wiki / 资料库 MCP(如 mc-wiki、minecraft.wiki)用【标准英文名或 id】检索。
  用户常给中文(苦力怕)、口语(会爆炸的怪)、或残缺名(cree)。本地先把叫法解析成
  "creeper / minecraft:creeper",wiki 检索命中率会准不少。

数据源(优先级从高到低):
  1. 实例 mods jar + 版本 jar 的 lang 文件(zh_cn.json / en_us.json,真实游戏数据,最全)
  2. 内置 VANILLA_NAMES 表(常见原版物品/方块/生物/效果/附魔 zh↔en,离线兜底)

导出:
  resolve_mc_name(query, game_dir=None, instance=None) -> str   # 文本结果,供 AI 工具直接返回
  resolve_name_map(query, game_dir=None, instance=None) -> dict # 结构化(名字/id/英文名/来源)
"""
import os
import zipfile


# ---- 内置原版双语表(zh 中文名 ↔ en 英文 id/名;离线兜底,随用随加)----
# 物品/方块(与 recipe_graph.MC_CN_ITEMS 互补;这里给英文 id 作规范名)
VANILLA_NAMES = {
    # 常用物品
    "minecraft:gold_ingot": ("金锭", "Gold Ingot"), "minecraft:iron_ingot": ("铁锭", "Iron Ingot"),
    "minecraft:copper_ingot": ("铜锭", "Copper Ingot"), "minecraft:netherite_ingot": ("下界合金锭", "Netherite Ingot"),
    "minecraft:diamond": ("钻石", "Diamond"), "minecraft:emerald": ("绿宝石", "Emerald"),
    "minecraft:coal": ("煤炭", "Coal"), "minecraft:charcoal": ("木炭", "Charcoal"),
    "minecraft:redstone": ("红石粉", "Redstone Dust"), "minecraft:lapis_lazuli": ("青金石", "Lapis Lazuli"),
    "minecraft:stick": ("木棍", "Stick"), "minecraft:oak_planks": ("橡木木板", "Oak Planks"),
    "minecraft:stone": ("石头", "Stone"), "minecraft:cobblestone": ("圆石", "Cobblestone"),
    "minecraft:obsidian": ("黑曜石", "Obsidian"), "minecraft:sand": ("沙子", "Sand"),
    "minecraft:glass": ("玻璃", "Glass"), "minecraft:crafting_table": ("工作台", "Crafting Table"),
    "minecraft:furnace": ("熔炉", "Furnace"), "minecraft:chest": ("箱子", "Chest"),
    "minecraft:gold_ore": ("金矿石", "Gold Ore"), "minecraft:iron_ore": ("铁矿石", "Iron Ore"),
    "minecraft:diamond_ore": ("钻石矿石", "Diamond Ore"), "minecraft:gold_block": ("金块", "Block of Gold"),
    "minecraft:iron_block": ("铁块", "Block of Iron"), "minecraft:diamond_block": ("钻石块", "Block of Diamond"),
    "minecraft:gold_nugget": ("金粒", "Gold Nugget"), "minecraft:iron_nugget": ("铁粒", "Iron Nugget"),
    "minecraft:gunpowder": ("火药", "Gunpowder"), "minecraft:blaze_rod": ("烈焰棒", "Blaze Rod"),
    "minecraft:ender_pearl": ("末影珍珠", "Ender Pearl"), "minecraft:ender_eye": ("末影之眼", "Eye of Ender"),
    "minecraft:blaze_powder": ("烈焰粉", "Blaze Powder"), "minecraft:slime_ball": ("黏液球", "Slimeball"),
    "minecraft:magma_cream": ("岩浆膏", "Magma Cream"), "minecraft:ghast_tear": ("恶魂之泪", "Ghast Tear"),
    "minecraft:golden_apple": ("金苹果", "Golden Apple"), "minecraft:elytra": ("鞘翅", "Elytra"),
    "minecraft:shield": ("盾牌", "Shield"), "minecraft:bow": ("弓", "Bow"),
    "minecraft:arrow": ("箭", "Arrow"), "minecraft:experience_bottle": ("附魔之瓶", "Bottle o' Enchanting"),
    "minecraft:milk_bucket": ("奶桶", "Milk Bucket"), "minecraft:water_bucket": ("水桶", "Water Bucket"),
    "minecraft:lava_bucket": ("熔岩桶", "Lava Bucket"), "minecraft:egg": ("鸡蛋", "Egg"),
    # 常见生物(实体)
    "minecraft:zombie": ("僵尸", "Zombie"), "minecraft:creeper": ("苦力怕", "Creeper"),
    "minecraft:enderman": ("末影人", "Enderman"), "minecraft:skeleton": ("骷髅", "Skeleton"),
    "minecraft:spider": ("蜘蛛", "Spider"), "minecraft:cave_spider": ("洞穴蜘蛛", "Cave Spider"),
    "minecraft:witch": ("女巫", "Witch"), "minecraft:villager": ("村民", "Villager"),
    "minecraft:iron_golem": ("铁傀儡", "Iron Golem"), "minecraft:snow_golem": ("雪傀儡", "Snow Golem"),
    "minecraft:blaze": ("烈焰人", "Blaze"), "minecraft:ghast": ("恶魂", "Ghast"),
    "minecraft:slime": ("史莱姆", "Slime"), "minecraft:magma_cube": ("岩浆怪", "Magma Cube"),
    "minecraft:pig": ("猪", "Pig"), "minecraft:cow": ("牛", "Cow"), "minecraft:sheep": ("羊", "Sheep"),
    "minecraft:chicken": ("鸡", "Chicken"), "minecraft:horse": ("马", "Horse"),
    "minecraft:wolf": ("狼", "Wolf"), "minecraft:cat": ("猫", "Cat"), "minecraft:fox": ("狐狸", "Fox"),
    "minecraft:bee": ("蜜蜂", "Bee"), "minecraft:axolotl": ("美西螈", "Axolotl"),
    "minecraft:warden": ("循声守卫", "Warden"), "minecraft:phantom": ("幻翼", "Phantom"),
    "minecraft:vex": ("恼鬼", "Vex"), "minecraft:ravager": ("劫掠兽", "Ravager"),
    "minecraft:guardian": ("守卫者", "Guardian"), "minecraft:elder_guardian": ("远古守卫者", "Elder Guardian"),
    "minecraft:shulker": ("潜影贝", "Shulker"), "minecraft:evoker": ("唤魔者", "Evoker"),
    "minecraft:pillager": ("掠夺者", "Pillager"), "minecraft:vindicator": ("卫道士", "Vindicator"),
    "minecraft:piglin": ("猪灵", "Piglin"), "minecraft:piglin_brute": ("猪灵蛮兵", "Piglin Brute"),
    "minecraft:hoglin": ("疣猪兽", "Hoglin"), "minecraft:zoglin": ("僵尸疣猪兽", "Zoglin"),
    "minecraft:strider": ("炽足兽", "Strider"), "minecraft:allay": ("悦灵", "Allay"),
    "minecraft:camel": ("骆驼", "Camel"), "minecraft:sniffer": ("嗅探兽", "Sniffer"),
    "minecraft:endermite": ("末影螨", "Endermite"), "minecraft:silverfish": ("蠹虫", "Silverfish"),
    "minecraft:ender_dragon": ("末影龙", "Ender Dragon"), "minecraft:wither": ("凋灵", "Wither"),
    "minecraft:drowned": ("溺尸", "Drowned"), "minecraft:husk": ("尸壳", "Husk"),
    "minecraft:stray": ("流浪者", "Stray"), "minecraft:zombie_villager": ("僵尸村民", "Zombie Villager"),
    # 效果(状态)
    "minecraft:speed": ("速度", "Speed"), "minecraft:slowness": ("缓慢", "Slowness"),
    "minecraft:haste": ("急迫", "Haste"), "minecraft:mining_fatigue": ("挖掘疲劳", "Mining Fatigue"),
    "minecraft:strength": ("力量", "Strength"), "minecraft:instant_health": ("瞬间治疗", "Instant Health"),
    "minecraft:instant_damage": ("瞬间伤害", "Instant Damage"), "minecraft:jump_boost": ("跳跃提升", "Jump Boost"),
    "minecraft:regeneration": ("生命恢复", "Regeneration"), "minecraft:resistance": ("抗性提升", "Resistance"),
    "minecraft:fire_resistance": ("抗火", "Fire Resistance"), "minecraft:water_breathing": ("水下呼吸", "Water Breathing"),
    "minecraft:night_vision": ("夜视", "Night Vision"), "minecraft:hunger": ("饥饿", "Hunger"),
    "minecraft:poison": ("中毒", "Poison"), "minecraft:wither_effect": ("凋零", "Wither"),
    "minecraft:darkness": ("黑暗", "Darkness"),
    # 附魔
    "minecraft:sharpness": ("锋利", "Sharpness"), "minecraft:smite": ("亡灵杀手", "Smite"),
    "minecraft:bane_of_arthropods": ("节肢杀手", "Bane of Arthropods"),
    "minecraft:knockback": ("击退", "Knockback"), "minecraft:fire_aspect": ("火焰附加", "Fire Aspect"),
    "minecraft:looting": ("抢夺", "Looting"), "minecraft:sweeping_edge": ("横扫之刃", "Sweeping Edge"),
    "minecraft:efficiency": ("效率", "Efficiency"), "minecraft:silk_touch": ("精准采集", "Silk Touch"),
    "minecraft:unbreaking": ("耐久", "Unbreaking"), "minecraft:fortune": ("时运", "Fortune"),
    "minecraft:protection": ("保护", "Protection"), "minecraft:fire_protection": ("火焰保护", "Fire Protection"),
    "minecraft:blast_protection": ("爆炸保护", "Blast Protection"),
    "minecraft:feather_falling": ("摔落缓冲", "Feather Falling"),
    "minecraft:thorns": ("荆棘", "Thorns"), "minecraft:respiration": ("水下呼吸", "Respiration"),
    "minecraft:aqua_affinity": ("水下速掘", "Aqua Affinity"), "minecraft:depth_strider": ("深海探索者", "Depth Strider"),
    "minecraft:frost_walker": ("冰霜行者", "Frost Walker"), "minecraft:mending": ("经验修补", "Mending"),
    "minecraft:luck_of_the_sea": ("海之眷顾", "Luck of the Sea"),
    "minecraft:impaling": ("穿刺", "Impaling"), "minecraft:loyalty": ("忠诚", "Loyalty"),
    "minecraft:riptide": ("激流", "Riptide"), "minecraft:channeling": ("引雷", "Channeling"),
    "minecraft:multishot": ("多重射击", "Multishot"), "minecraft:quick_charge": ("快速装填", "Quick Charge"),
    "minecraft:piercing": ("穿透", "Piercing"),
}


def _norm(s: str) -> str:
    """归一化:去空白/下划线/连字符/引号,小写,去前缀 minecraft: 以允许命中"""
    s = (s or "").strip().lower()
    for ch in (" ", "_", "-", "'", '"', "，", "`", "·"):
        s = s.replace(ch, "")
    if s.startswith("minecraft:"):
        s = s[len("minecraft:"):]
    return s


def _build_index(game_dir: str, instance: str | None) -> tuple:
    """构建 (zh_to_en, en_to_zh, id_to_en)。
    先内置信,再用实例 jar lang 覆盖补充(更全/更贴近真实游戏)。"""
    zh_to_en = {}   # 中文名(归一化) → 英文名
    en_to_zh = {}   # 英文名(归一化) → 中文名
    id_to_en = {}   # id → 英文名
    for mcid, (zh, en) in VANILLA_NAMES.items():
        if zh:
            zh_to_en.setdefault(_norm(zh), en)
            en_to_zh.setdefault(_norm(en), zh)
        id_to_en.setdefault(mcid, en)
        id_to_en.setdefault("minecraft:" + _norm(en), en)

    # 从实例 jar lang 补充(真实游戏数据,最全)
    try:
        base = os.path.join(game_dir, "versions", instance or "")
        jars = []
        if os.path.isdir(base):
            jars += [os.path.join(base, f) for f in sorted(os.listdir(base)) if f.endswith(".jar")]
        md = os.path.join(base, "mods")
        if os.path.isdir(md):
            jars += [os.path.join(md, f) for f in sorted(os.listdir(md)) if f.endswith(".jar")]
        key_prefixes = ("item.", "block.", "entity.", "enchantment.", "effect.",
                        "potion.", "fluid.", "biome.")
        for path in jars:
            try:
                with zipfile.ZipFile(path) as z:
                    entries = {e.filename for e in z.infolist()}
                    for pre in key_prefixes:
                        langfile = None
                        for suf in ("zh_cn.json", "en_us.json"):
                            hit = next((e for e in entries if e.endswith(f"/lang/{suf}")), None)
                            if hit:
                                langfile = (hit, suf)
                                break
                        if not langfile:
                            continue
                        hit, _suf = langfile
                        data = json_load(z.read(hit))
                        for key, val in (data or {}).items():
                            if not isinstance(val, str) or not key.startswith(pre):
                                continue
                            rest = key[len(pre):]
                            if rest.endswith(".name"):
                                rest = rest[:-5]
                            parts = rest.split(".")
                            if len(parts) < 2 or not parts[0] or not parts[1]:
                                continue
                            # key.item.minecraft.xxx → id minecraft:xxx(兼容 ns 前有 minecraft)
                            ns = parts[0] if len(parts) >= 2 else "minecraft"
                            mcid2 = f"{ns}:{parts[1]}"
                            zh_to_en.setdefault(_norm(val), val)
                            en_to_zh.setdefault(_norm(val), val)
                            id_to_en.setdefault(mcid2, val)
            except Exception:
                continue
    except Exception:
        pass
    return zh_to_en, en_to_zh, id_to_en


def json_load(data: bytes):
    import json
    try:
        return json.loads(data.decode("utf-8", errors="replace"))
    except Exception:
        return None


def resolve_name_map(query: str, game_dir: str = None, instance: str = None) -> dict:
    """把叫法解析成 {query, name, id, zh, source}。找不到时 name/id 为空。"""
    if game_dir is None:
        import paths
        game_dir = paths.GAME_DIR
    zh_to_en, en_to_zh, id_to_en = _build_index(game_dir, instance)
    q = (query or "").strip()
    qn = _norm(q)
    # 1) 直接是 id(minecraft:xx 或 ns:xx)
    if ":" in q and qn:
        en = id_to_en.get(q, "") or id_to_en.get("minecraft:" + _norm(q.split(":")[-1]), "")
        return {"query": queries_caption(q), "name": en or q, "id": q,
                "zh": en_to_zh.get(_norm(en), ""), "source": "id"}
    # 2) 中文/英文名
    if qn in zh_to_en:
        en = zh_to_en[qn]
        return {"query": q, "name": en, "id": _id_for_en(en, id_to_en),
                "zh": q, "source": "name"}
    if qn in en_to_zh:
        zh = en_to_zh[qn]
        return {"query": q, "name": q, "id": _id_for_en(q, id_to_en),
                "zh": zh, "source": "name"}
    # 3) 英文 id 去前缀后匹配(如 creeper)——仅当像规范注册名(ASCII、无空格)才回退造 id
    if qn.isascii() and not any(c in qn for c in " /é"):
        id2 = _id_for_en(qn, id_to_en)
        if id2:
            en = id_to_en.get(id2, "") or id2
            return {"query": q, "name": en or q, "id": id2,
                    "zh": en_to_zh.get(_norm(en), ""), "source": "id"}
    return {"query": q, "name": q, "id": "", "zh": "", "source": "none"}


def _id_for_en(en: str, id_to_en: dict) -> str:
    if not en:
        return ""
    e = _norm(en)
    for k, v in id_to_en.items():
        if _norm(v) == e:
            return k
    # 没在索引里:不造 id,除非已是合法注册名形态(minecraft: 前缀 + 纯 ASCII)
    if e.startswith("minecraft:") and e[len("minecraft:"):]:
        return e
    return ""


def queries_caption(q: str) -> str:
    return q


def resolve_mc_name(query: str, game_dir: str = None, instance: str = None) -> str:
    """文本结果:给出规范英文名 + id + 中文名,供 AI 拿去查 wiki/资料库。"""
    r = resolve_name_map(query, game_dir=game_dir, instance=instance)
    q = r.get("query") or query
    if not r.get("id"):
        return (f"本地没查到「{q}」的规范名(可能是 Mod 专属或太生僻)。"
                f"可换个叫法再试,或直接用它检索 wiki。")
    parts = [f"「{q}」→ {r['name']}"]
    if r.get("id"):
        parts.append(f"id: {r['id']}")
    if r.get("zh"):
        parts.append(f"中文: {r['zh']}")
    parts.append("(用上面这个标准英文名/id 去 wiki/资料库检索,命中更准)")
    return " | ".join(parts)
