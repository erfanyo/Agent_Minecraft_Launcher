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


# ---- 口语/别名/近义表(描述性叫法 → 规范 MC id)----
# 覆盖"纯名称对不上"的常见口语(如 会爆炸的怪、大绿、苦力怕同义词),让本地解析不再只会精确匹配。
COLLOQUIAL = {
    # 生物
    "minecraft:creeper": ["会爆炸的怪", "爆爆怪", "绿皮怪", "爆炸怪", "绿色苦力怕", "creeper怪"],
    "minecraft:zombie": ["丧尸", "活死人", "绿僵尸"], "minecraft:enderman": ["小黑", "黑基佬", "瞬移怪"],
    "minecraft:skeleton": ["白骨", "骷髅兵"], "minecraft:spider": ["蜘蛛怪"],
    "minecraft:cave_spider": ["毒蜘蛛", "蓝色蜘蛛"], "minecraft:witch": ["巫婆"],
    "minecraft:villager": ["村民大佬", "npc", "商人村民"], "minecraft:iron_golem": ["铁人", "铁巨人"],
    "minecraft:blaze": ["火人", "烈焰"], "minecraft:ghast": ["恶魂怪", "水母"],
    "minecraft:slime": ["史莱姆怪", "果冻怪"], "minecraft:magma_cube": ["岩浆史莱姆"],
    "minecraft:warden": ["循声者", "金刚", "声呐怪"], "minecraft:phantom": ["幻影", "夜行怪"],
    "minecraft:vex": ["小鬼", "恼鬼怪"], "minecraft:ravager": ["劫掠兽怪", "大斧怪"],
    "minecraft:guardian": ["鱼怪", "守卫者怪"], "minecraft:shulker": ["潜影", "炮弹怪"],
    "minecraft:evoker": ["唤魔", "召鬼的"], "minecraft:pillager": ["掠夺者怪", "十字弩怪"],
    "minecraft:vindicator": ["斧头怪", "卫道士怪"], "minecraft:piglin": ["猪人", "金甲猪灵"],
    "minecraft:piglin_brute": ["猪灵蛮王", "金斧猪灵"], "minecraft:hoglin": ["猪兽", "红猪"],
    "minecraft:strider": ["岩浆行走者", "红红鞍"], "minecraft:allay": ["小精灵", "拾物精灵"],
    "minecraft:ender_dragon": ["末影龙", "大黑龙", "终界龙"], "minecraft:wither": ["凋零", "凋零头", "老凋灵"],
    "minecraft:axolotl": ["娃娃鱼", "火蝾螈"], "minecraft:bee": ["蜜蜂精", "采蜜的"],
    "minecraft:hoglin": ["疣猪", "红皮猪"],
    # 物品/材料
    "minecraft:diamond": ["钻石矿", "真钻"], "minecraft:emerald": ["绿宝石矿", "绿钻"],
    "minecraft:redstone": ["红石", "redstone粉"], "minecraft:lapis_lazuli": ["青金石矿", "蓝石头"],
    "minecraft:netherite_ingot": ["下界合金", "顶级锭", "奈瑟"], "minecraft:netherite_scrap": ["下界合金碎片", "下界合金残片"],
    "minecraft:gold_ingot": ["金锭G", "金"], "minecraft:iron_ingot": ["铁锭I", "铁"],
    "minecraft:stick": ["木棒"], "minecraft:string": ["线材料"],
    "minecraft:gunpowder": ["火药粉", "tnt粉"], "minecraft:blaze_rod": ["烈焰棒材", "火棒"],
    "minecraft:ender_pearl": ["末影珍珠E", "传送珍珠"], "minecraft:ender_eye": ["末影之眼E", "传送眼"],
    "minecraft:slime_ball": ["粘液球", "史莱姆球"], "minecraft:magma_cream": ["岩浆膏M", "火药膏"],
    "minecraft:golden_apple": ["金苹果G", "神苹果"], "minecraft:elytra": ["鞘翅E", "滑翔翼"],
    "minecraft:shield": ["盾牌S", "防盾"],
    "minecraft:crafting_table": ["合成台", "工作台C"], "minecraft:furnace": ["炉子", "熔炉F"],
    "minecraft:chest": ["箱子C", "储物箱"], "minecraft:obsidian": ["黑曜", "obs"],
    "minecraft:glass": ["玻璃板", "玻璃G"],
    # 效果
    "minecraft:speed": ["加速", "velocity", "迅捷"], "minecraft:slowness": ["减速", "迟缓"],
    "minecraft:haste": ["急速", "挖矿加速"], "minecraft:strength": ["力量强化", "power"],
    "minecraft:regeneration": ["回血", "再生"], "minecraft:resistance": ["减伤", "抗性"],
    "minecraft:fire_resistance": ["防火", "火焰抵抗"], "minecraft:night_vision": ["夜视眼", "看清黑暗"],
    "minecraft:poison": ["剧毒", "毒上"], "minecraft:darkness": ["致盲", "黑暗效果"],
    # 附魔
    "minecraft:sharpness": ["锋利五", "sharp", "锋利附魔"], "minecraft:silk_touch": ["精准采集E", "丝触"],
    "minecraft:unbreaking": ["耐久三", "不坏"], "minecraft:fortune": ["时运三", "发财"],
    "minecraft:efficiency": ["效率五", "挖得快"], "minecraft:protection": ["防护四", "护甲附魔"],
    "minecraft:mending": ["修复", "经验修补E"], "minecraft:looting": ["抢夺三", "摸尸"],
    "minecraft:feather_falling": ["摔缓四", "缓降"], "minecraft:thorns": ["反伤", "荆棘三"],
    "minecraft:depth_strider": ["水中行走", "深海行者"],
}


def _build_index(game_dir: str, instance: str | None) -> tuple:
    """构建 (zh_to_en, en_to_zh, id_to_en, aliases)。
    先内置信,再用实例 jar lang 覆盖补充(更全/更贴近真实游戏)。"""
    zh_to_en = {}   # 中文名(归一化) → 英文名
    en_to_zh = {}   # 英文名(归一化) → 中文名
    id_to_en = {}   # id → 英文名
    aliases = []    # [(归一化叫法, 英文名, id), ...] 供模糊/口语匹配
    for mcid, (zh, en) in VANILLA_NAMES.items():
        if zh:
            zh_to_en.setdefault(_norm(zh), en)
            en_to_zh.setdefault(_norm(en), zh)
        id_to_en.setdefault(mcid, en)
        id_to_en.setdefault("minecraft:" + _norm(en), en)
    # 口语/别名
    for mcid, lacks in COLLOQUIAL.items():
        for la in lacks:
            aliases.append((_norm(la), mcid.split(":")[-1], mcid))
            en = id_to_en.get(mcid, mcid.split(":")[-1])
            zh_to_en.setdefault(_norm(la), en)   # 让别名也能精确命中
            en_to_zh.setdefault(_norm(en), la)

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
    return zh_to_en, en_to_zh, id_to_en, aliases


def json_load(data: bytes):
    import json
    try:
        return json.loads(data.decode("utf-8", errors="replace"))
    except Exception:
        return None


def alias_id_map() -> dict:
    """口语/别名 → 规范 id(含内置名,归一化 key)。供 recipe_graph 等把别名并进物品索引,
    这样 get_recipe_path / compare_items 也吃口语叫法(如 会爆炸的怪 → minecraft:creeper)。"""
    m = {}
    for mcid, (zh, en) in VANILLA_NAMES.items():
        if zh:
            m[_norm(zh)] = mcid
            m[_norm(en)] = mcid
    for mcid, lacks in COLLOQUIAL.items():
        for la in lacks:
            m[_norm(la)] = mcid
    return m


def resolve_name_map(query: str, game_dir: str = None, instance: str = None) -> dict:
    """把叫法解析成 {query, name, id, zh, source}。找不到时 name/id 为空。
    source: id / name / fuzzy / none。"""
    if game_dir is None:
        import paths
        game_dir = paths.GAME_DIR
    zh_to_en, en_to_zh, id_to_en, aliases = _build_index(game_dir, instance)
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
    # 4) 口语/别名精确命中
    for an, aen, aid in aliases:
        if an == qn:
            return {"query": q, "name": aen, "id": aid,
                    "zh": en_to_zh.get(_norm(aen), q), "source": "name"}
    # 5) 模糊:拼音/部分命中——query 是某名的前缀,或某名包含 query
    best = _fuzzy_match(qn, zh_to_en, en_to_zh, aliases, id_to_en)
    if best:
        return {"query": q, "name": best[0], "id": best[1],
                "zh": best[2] or q, "source": "fuzzy"}
    return {"query": q, "name": q, "id": "", "zh": "", "source": "none"}


def _fuzzy_match(qn: str, zh_to_en: dict, en_to_zh: dict, aliases: list, id_to_en: dict):
    """query 是中文名的子串 / 英文名的前缀 → 返回 (英文名, id, 中文名)。
    优先级:英文前缀 > 中文子串 > 别名子串(英文前缀最可能是用户在打英文名)。长度过短(<2)不模糊。"""
    if len(qn) < 2:
        return None
    best = None
    best_len = 0
    # 英文前缀命中(如 "cree" → creeper)
    for en_raw, zh in en_to_zh.items():
        if en_raw.startswith(qn) and len(en_raw) > best_len and len(en_raw) <= 16:
            # 优先取"非别名"的规范中文名:zh 若本身是个口语再向 zh_to_en 反查规范
            canon_zh = _canonical_zh(en_raw, zh_to_en)
            best = (en_raw, _id_for_en(en_raw, id_to_en), canon_zh)
            best_len = len(en_raw)
    # 中文子串命中(如 "苦力"、"力怕" → 苦力怕)
    for zh_raw, en in zh_to_en.items():
        if qn in zh_raw and len(zh_raw) > best_len and len(zh_raw) <= 12:
            canon_zh = _canonical_zh(en, zh_to_en)
            best = (en, _id_for_en(en, id_to_en), canon_zh)
            best_len = len(zh_raw)
    # 别名子串命中(仅当前面都没命中更长的)
    if best is None:
        for an, aen, aid in aliases:
            if qn in an and len(an) > best_len and len(an) <= 12:
                best = (aen, aid, en_to_zh.get(_norm(aen), ""))
                best_len = len(an)
    return best


def _canonical_zh(en: str, zh_to_en: dict) -> str:
    """给英文名找规范中文名(反查,排除把口语当地名)。找不到就返回空。"""
    if not en:
        return ""
    for zh_raw, _e in zh_to_en.items():
        if _e == en and len(zh_raw) <= 12:
            return zh_raw
    return ""


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
    zh = r.get("zh") or ""
    if zh and _norm(zh) != _norm(q):
        parts.append(f"中文: {zh}")
    parts.append("(用上面这个标准英文名/id 去 wiki/资料库检索,命中更准)")
    return " | ".join(parts)


def resolve_for_wiki(query: str, wiki_lang: str = "en", game_dir: str = None,
                     instance: str = None) -> dict:
    """按目标 wiki 语言返回适合检索的名字。
    wiki_lang: 'en'(默认,如 minecraft.wiki / L3-N0X 宿主) 或 'zh'(中文 wiki,如 mc-wiki-fetch-mcp)。
    返回 {query, search_name, id, zh, en}。search_name = 该 wiki 该用的检索名。"""
    r = resolve_name_map(query, game_dir=game_dir, instance=instance)
    en = r.get("name") or query
    zh = r.get("zh") or ""
    if wiki_lang and str(wiki_lang).lower().startswith("zh"):
        return {"query": query, "search_name": zh or en, "id": r.get("id", ""),
                "zh": zh, "en": en, "source": r.get("source", "none")}
    return {"query": query, "search_name": en or zh, "id": r.get("id", ""),
            "zh": zh, "en": en, "source": r.get("source", "none")}


# ---------------- 按实例持久化的中文物品名索引 ----------------
# 目的:把"该实例 mods 里所有 mod + 原版 jar 的中文物品/方块/实体名"解析成一张
#   zh_to_id / id_to_zh 对照表,**持久化**到 AMCL/cache/item_names/<instance>.json,
#   避免每次查攻略都重扫 jar。绑定实例:某个名字解析不出来 = 该实例没装对应 mod,
#   或该 mod 没做中文翻译(两种都说明当前实例查不到)。
#   (对比:resolve_mc_name 是"单点查询";本函数产"全量表",供攻略链路批量/统一用。)


def _inst_name_index_path(game_dir: str, instance: str) -> str:
    try:
        from paths import cache_dir
        d = cache_dir("item_names")
        safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in (instance or "root"))
        return os.path.join(d, f"{safe}.json")
    except Exception:
        return ""


def _inst_signature(game_dir: str, instance: str) -> str:
    """实例 mods jar + 版本 jar 的"文件名:修改时间"签名,判断是否需要重扫。"""
    try:
        base = os.path.join(game_dir, "versions", instance or "")
        paths = []
        if os.path.isdir(base):
            for n in sorted(os.listdir(base)):
                if n.endswith(".jar"):
                    p = os.path.join(base, n)
                    paths.append(f"{n}:{int(os.path.getmtime(p))}")
        md = os.path.join(base, "mods")
        if os.path.isdir(md):
            for n in sorted(os.listdir(md)):
                if n.endswith(".jar"):
                    p = os.path.join(md, n)
                    paths.append(f"m:{n}:{int(os.path.getmtime(p))}")
        return "|".join(paths)
    except Exception:
        return ""


# 覆盖物品/方块/实体/附魔/效果/药水/流体/生物群系——攻略查询用到的全部名称类别
_INDEX_PREFIXES = ("item.", "block.", "entity.", "enchantment.", "effect.",
                   "potion.", "fluid.", "biome.")


def instance_zh_id_index(game_dir: str, instance: str | None) -> tuple[dict, dict]:
    """按实例构建/读取(持久化)中文名↔id 对照表。

    返回 (zh_to_id, id_to_zh):
    - zh_to_id: 中文名(规整) → id("ns:path")
    - id_to_zh: id → 中文名
    结果落盘 AMCL/cache/item_names/<instance>.json;实例 jar 更新(签名变化)才重扫。

    **绑定实例**:只解析该实例 mods + 版本 jar 的名字。某中文名解析不到,
    说明该实例没装对应 mod,或该 mod 没做中文翻译——都代表"当前实例查不到"。
    """
    import paths
    game_dir = game_dir or paths.GAME_DIR
    cache_path = _inst_name_index_path(game_dir, instance)
    sig = _inst_signature(game_dir, instance)
    # 内置原版表作基座(minecraft 不在实例 jar 里)。注意 VANILLA_NAMES 是 {id: (zh, en)}。
    zh_to_id = {}
    id_to_zh = {}
    for mcid, (zh, en) in VANILLA_NAMES.items():
        if zh:
            zh_to_id.setdefault(zh, mcid)
        id_to_zh.setdefault(mcid, zh or en)

    # ① 读磁盘缓存(签名匹配直接返回,不重扫 jar)
    import json as _json
    try:
        if cache_path and os.path.isfile(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                cached = _json.load(f)
            if cached.get("_sig") == sig:
                return cached.get("zh_to_id", {}), cached.get("id_to_zh", {})
    except Exception:
        pass

    # ② 扫实例 jar(版本 jar + mods 目录),item./block./entity. 等
    try:
        base = os.path.join(game_dir, "versions", instance or "")
        jars = []
        if os.path.isdir(base):
            jars += [os.path.join(base, f) for f in sorted(os.listdir(base)) if f.endswith(".jar")]
        md = os.path.join(base, "mods")
        if os.path.isdir(md):
            jars += [os.path.join(md, f) for f in sorted(os.listdir(md)) if f.endswith(".jar")]
        for path in jars:
            try:
                with zipfile.ZipFile(path) as z:
                    entries = {e.filename for e in z.infolist()}
                    for pre in _INDEX_PREFIXES:
                        langfile = next((e for e in entries if e.endswith(f"/lang/zh_cn.json")), None)
                        if langfile is None:
                            continue
                        data = _json.loads(z.read(langfile).decode("utf-8", "replace"))
                        for key, val in (data or {}).items():
                            if not isinstance(val, str) or not val.strip() or not key.startswith(pre):
                                continue
                            if len(val.strip()) > 40:
                                continue
                            item_id = _lang_key_to_id(key)
                            if not item_id:
                                continue
                            zh = val.strip()
                            zh_to_id.setdefault(zh, item_id)
                            id_to_zh.setdefault(item_id, zh)
            except Exception:
                continue
    except Exception:
        pass

    # ③ 落盘(带签名,下次命中缓存)
    try:
        if cache_path:
            with open(cache_path, "w", encoding="utf-8") as f:
                _json.dump({"_sig": sig, "zh_to_id": zh_to_id, "id_to_zh": id_to_zh},
                           f, ensure_ascii=False)
    except Exception:
        pass
    return zh_to_id, id_to_zh


def _lang_key_to_id(key: str) -> str | None:
    """语言文件 key(item./block./entity./...)<ns>.<path>(可带 .name 尾巴)→ ns:path"""
    for pre in _INDEX_PREFIXES:
        if key.startswith(pre):
            rest = key[len(pre):]
            if rest.endswith(".name"):
                rest = rest[:-5]
            parts = rest.split(".")
            # 兼容 item.minecraft.xxx 或 item.mekanism.xxx(2/3 段,ns 取第一段)
            if len(parts) >= 2 and parts[0] and parts[1]:
                ns = parts[0]
                return f"{ns}:{parts[1]}"
    return None
