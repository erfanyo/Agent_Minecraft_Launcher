# -*- coding: utf-8 -*-
"""
配方旁路:直接读 mod jar / 原版版本 jar 里的 datapack 配方(无需进游戏)。

背景:配方数据目前靠 bridge-mod 进游戏导出(.bridge/recipes.json,扁平格式);
本模块实现"旁路"——直接解析 jar 内 `data/<ns>/recipe/*.json`(datapack 格式):

1. 解析:crafting_shaped(pattern+key 展开)/ crafting_shapeless / smelting 等烧炼 /
   stonecutting / smithing_transform(_trim) / 模组自定义类型(Mekanism 冶金灌注等,含化学输入)
2. tag 解析:配方里的 {"tag": ...} 引用 → 具体物品(data/<ns>/tags/item/*.json,支持递归),
   解析不出保留 "(tag:<id>)" 伪原料(recipe_graph 视为不可展开)
3. 输出统一转成 bridge 扁平格式 {"id","type","output":{"item","count"},"ingredients":[...]},
   与 recipe_graph 消费格式对齐,改动最小

缓存:解析结果落 AMCL/cache/recipes-jar/<实例>.json(带签名,jar 变了才重扫;
遵循 AI规划 §11 —— 文件只放启动器自己的 AMCL 目录,不散落用户系统)。
"""
import json
import os
import time
import zipfile

from paths import cache_dir  # 统一路径访问层

CACHE_DIR = cache_dir("recipes-jar")
CACHE_SCHEMA = 2   # 缓存格式版本:解析逻辑升级时 +1,旧缓存自动作废重扫

# 需要"单原料"的烧炼/加工类型
_SINGLE_TYPES = ("smelting", "blasting", "smoking", "campfire_cooking", "stonecutting")
# 锻造台类型
_SMITHING_TYPES = ("smithing_transform", "smithing_trim")
# 模组自定义类型的通用输入字段(按顺序尝试)
_GENERIC_INPUT_FIELDS = ("item_input", "input", "ingredient", "base", "addition",
                         "template", "main", "sub", "left", "right")
# 化学/流体类输入字段 → 伪原料 "(chem:<id>)"
_CHEM_FIELDS = ("chemical_input", "infusionInput", "gas_input", "fluid_input", "chemical")

# 常用约定 tag 兜底:jar 里没有 tag 定义时(如 c:/forge: 约定 tag),给一个代表性物品,
# 让配方能显示具体原料。只覆盖常见项,未知 tag 仍保留 "(tag:<id>)" 伪原料。
_COMMON_TAG_FALLBACK = {
    # c: 约定(通用合成标签)
    "c:ingots/iron": "minecraft:iron_ingot",
    "c:ingots/gold": "minecraft:gold_ingot",
    "c:ingots/copper": "minecraft:copper_ingot",
    "c:ingots/netherite": "minecraft:netherite_ingot",
    "c:ingots/osmium": "mekanism:ingot_osmium",
    "c:ingots/steel": "mekanism:ingot_steel",
    "c:nuggets/iron": "minecraft:iron_nugget",
    "c:nuggets/gold": "minecraft:gold_nugget",
    "c:raw_materials/iron": "minecraft:raw_iron",
    "c:raw_materials/gold": "minecraft:raw_gold",
    "c:dusts/redstone": "minecraft:redstone",
    "c:dusts/iron": "mekanism:dust_iron",
    "c:dusts/gold": "mekanism:dust_gold",
    "c:dusts/osmium": "mekanism:dust_osmium",
    "c:dusts/steel": "mekanism:dust_steel",
    "c:gems/diamond": "minecraft:diamond",
    "c:gems/emerald": "minecraft:emerald",
    "c:gems/lapis": "minecraft:lapis_lazuli",
    "c:stones/redstone_ores": "minecraft:redstone_ore",
    # forge: 旧式约定
    "forge:ingots/iron": "minecraft:iron_ingot",
    "forge:ingots/gold": "minecraft:gold_ingot",
    "forge:ingots/copper": "minecraft:copper_ingot",
    "forge:nuggets/iron": "minecraft:iron_nugget",
    "forge:dusts/redstone": "minecraft:redstone",
}


# ---------- 基础工具 ----------
def _norm_type(t: str) -> str:
    """datapack type → recipe_graph 消费的类型(minecraft: 前缀去掉,模组类型保留)"""
    if not t:
        return ""
    if t.startswith("minecraft:"):
        return t[len("minecraft:"):]
    return t


def _norm_ingredient(ing):
    """把 datapack 原料(字符串/字典/嵌套 ingredient/列表)归一成 {"item"|"tag", "count"}。"""
    if isinstance(ing, str):
        ing = ing.strip()
        if not ing:
            return None
        if ing.startswith("#"):
            return {"tag": ing[1:], "count": 1}
        return {"item": ing, "count": 1}
    if isinstance(ing, list) and ing:
        return _norm_ingredient(ing[0])          # 备选列表取第一个
    if isinstance(ing, dict):
        count = ing.get("count", 1) or 1
        if "item" in ing and isinstance(ing["item"], str):
            return {"item": ing["item"], "count": count}
        if "tag" in ing and isinstance(ing["tag"], str):
            return {"tag": ing["tag"], "count": count}
        if "ingredient" in ing:                  # 嵌套: {"input": {"ingredient": {...}}}
            g = _norm_ingredient(ing["ingredient"])
            if g:
                g["count"] = g.get("count", 1) * count
                return g
        if "id" in ing and isinstance(ing["id"], str):   # 极简 {"id": x, "count": n}
            return {"item": ing["id"], "count": count}
    return None


def _result_item(result) -> str:
    """datapack 的 result/output → 物品 id(兼容 1.21 的 result.id 与旧版 result.item)"""
    if not isinstance(result, dict):
        return ""
    return result.get("id") or result.get("item") or ""


def _result_count(result) -> int:
    if not isinstance(result, dict):
        return 1
    return result.get("count", 1) or 1


# ---------- 单条配方解析 ----------
def parse_recipe_json(recipe_id: str, data: dict) -> dict | None:
    """datapack 配方 JSON → bridge 扁平格式(未解析 tag)。解析不了返回 None。"""
    if not isinstance(data, dict):
        return None
    rtype = _norm_type(data.get("type", ""))
    result = data.get("result") or data.get("output") or {}
    out_item = _result_item(result)
    out_count = _result_count(result)
    if not out_item or out_item == "minecraft:air":
        return None
    ings = []

    if rtype == "crafting_shaped":
        # pattern 二维字符数组 × key 映射 → 原料计数(空格=空槽,忽略)
        pattern = data.get("pattern") or []
        key = data.get("key") or {}
        counts = {}
        for row in pattern:
            for ch in row:
                if ch == " " or ch not in key:
                    continue
                counts[ch] = counts.get(ch, 0) + 1
        for ch, n in counts.items():
            g = _norm_ingredient(key.get(ch))
            if g:
                g["count"] = g.get("count", 1) * n
                ings.append(g)
    elif rtype == "crafting_shapeless":
        for ing in data.get("ingredients") or []:
            g = _norm_ingredient(ing)
            if g:
                ings.append(g)
    elif rtype in _SINGLE_TYPES:
        g = _norm_ingredient(data.get("ingredient"))
        if g:
            ings.append(g)
    elif rtype in _SMITHING_TYPES:
        for f in ("template", "base", "addition"):
            g = _norm_ingredient(data.get(f))
            if g:
                ings.append(g)
        if rtype == "smithing_trim":
            # 纹饰的产物 = 基底物品(模板/材料只决定纹饰外观)
            base = data.get("base") or {}
            b = _result_item(base) if isinstance(base, dict) else ""
            if b:
                out_item = b
    else:
        # 模组自定义类型(如 mekanism:metallurgic_infusing):通用输入字段 + 化学输入
        for f in _GENERIC_INPUT_FIELDS:
            g = _norm_ingredient(data.get(f))
            if g:
                g["count"] = g.get("count", 1)
                ings.append(g)
        for f in _CHEM_FIELDS:
            ch = data.get(f)
            if isinstance(ch, dict):
                cid = ch.get("tag") or ch.get("item") or ch.get("chemical") or ""
                if cid:
                    amt = ch.get("amount", 1) or 1
                    ings.append({"item": f"(chem:{cid})", "count": amt})
    return {"id": recipe_id, "type": rtype,
            "output": {"item": out_item, "count": out_count},
            "ingredients": ings}


# ---------- jar 扫描 ----------
def _recipe_id_from_path(entry: str) -> str | None:
    """jar 内配方路径 → 配方 id:
    data/<ns>/recipe/<path>.json → <ns>:<path>
    data/<ns>/datapacks/<name>/data/<ns2>/recipe/<path>.json → <ns2>:<path>"""
    if "/recipe/" not in entry or not entry.endswith(".json"):
        return None
    seg = entry.split("/recipe/", 1)[0]
    if "/datapacks/" in seg:
        ns = seg.rsplit("/data/", 1)[-1].split("/", 1)[0]
    elif seg.startswith("data/"):
        ns = seg.split("/", 1)[1]
    else:
        return None
    path = entry.split("/recipe/", 1)[-1][:-5]   # 去 .json(可能含子目录)
    return f"{ns}:{path}" if ns else None


def _is_tag_entry(entry: str) -> bool:
    return entry.endswith(".json") and ("/tags/item/" in entry or "/tags/items/" in entry)


def _tag_id_from_path(entry: str) -> str:
    for marker in ("/tags/item/", "/tags/items/"):
        if marker in entry:
            before, after = entry.split(marker, 1)
            ns = before.split("/", 1)[1] if before.startswith("data/") else ""
            return f"{ns}:{after[:-5]}"
    return ""


def _collect_tags(z, names: list) -> dict:
    tags = {}
    for n in names:
        if not _is_tag_entry(n):
            continue
        tid = _tag_id_from_path(n)
        if not tid:
            continue
        try:
            data = json.loads(z.read(n).decode("utf-8", errors="replace"))
        except Exception:
            continue
        vals = data.get("values") if isinstance(data, dict) else None
        if isinstance(vals, list) and vals:
            tags[tid] = vals
    return tags


def _resolve_tag(tag_id: str, tags: dict, _seen=None, _depth: int = 0) -> str | None:
    """tag id → 第一个能解析出的具体物品 id;解析不出返回 None(循环/深度保护)。
    先查 jar 里的 tag 定义,再查常用约定 tag 兜底表。"""
    if _depth > 10:
        return None
    _seen = _seen or set()
    if tag_id in _seen:
        return None
    _seen = _seen | {tag_id}
    for v in tags.get(tag_id) or []:
        vid = v.get("id") if isinstance(v, dict) else str(v)
        vid = (vid or "").strip()
        if not vid:
            continue
        if vid.startswith("#"):
            r = _resolve_tag(vid[1:], tags, _seen, _depth + 1)
            if r:
                return r
        return vid
    return _COMMON_TAG_FALLBACK.get(tag_id)


def _resolve_ingredients(recipes: list, tags: dict) -> list:
    """把配方里的 {"tag": x} 换成具体物品;解析不出 → "(tag:<id>)" 伪原料"""
    out = []
    for r in recipes:
        ings = []
        for g in r.get("ingredients", []):
            if "tag" in g:
                item = _resolve_tag(g["tag"], tags)
                ings.append({"item": item or f"(tag:{g['tag']})", "count": g.get("count", 1)})
            else:
                ings.append(g)
        r["ingredients"] = ings
        out.append(r)
    return out


def scan_jar_recipes(jar_path: str) -> tuple:
    """读一个 jar 里的 datapack 配方与 tag。返回 (recipes, tags)。失败返回 ([], {})。"""
    recipes, tags = [], {}
    try:
        with zipfile.ZipFile(jar_path) as z:
            names = z.namelist()
            for n in names:
                if not n.endswith(".json"):
                    continue
                if "/recipe/" in n:
                    rid = _recipe_id_from_path(n)
                    if not rid:
                        continue
                    try:
                        data = json.loads(z.read(n).decode("utf-8", errors="replace"))
                    except Exception:
                        continue
                    r = parse_recipe_json(rid, data)
                    if r:
                        recipes.append(r)
            tags = _collect_tags(z, names)
    except Exception:
        pass
    return recipes, tags


# ---------- 实例扫描 + 缓存(AMCL/cache/recipes-jar,见 AI规划 §11) ----------
def instance_jars(game_dir: str, instance_id: str) -> tuple:
    """实例目录里的 jar:返回 (版本 jar 列表, mods jar 列表)"""
    base = os.path.join(game_dir, "versions", instance_id)
    vjars, mjars = [], []
    if not os.path.isdir(base):
        return vjars, mjars
    try:
        vjars = [os.path.join(base, f) for f in sorted(os.listdir(base)) if f.endswith(".jar")]
    except OSError:
        pass
    md = os.path.join(base, "mods")
    if os.path.isdir(md):
        try:
            mjars = [os.path.join(md, f) for f in sorted(os.listdir(md)) if f.endswith(".jar")]
        except OSError:
            pass
    return vjars, mjars


def _jar_signature(jars: list) -> str:
    parts = []
    for j in jars:
        try:
            parts.append(f"{os.path.basename(j)}:{int(os.path.getmtime(j))}:{int(os.path.getsize(j))}")
        except OSError:
            parts.append(os.path.basename(j))
    return "|".join(parts)


def _cache_path(instance_id: str) -> str:
    return os.path.join(CACHE_DIR, f"{instance_id}.json")


def scan_instance(game_dir: str, instance_id: str, use_cache: bool = True) -> dict | None:
    """解析一个实例的全部 jar 配方(版本 jar + mods jar,带缓存)。

    返回 {"signature", "instance", "recipes", "tags", "scanned_at",
          "version_jars", "mods_jars"} 或 None(实例无 jar)。
    缓存:AMCL/cache/recipes-jar/<实例>.json,签名变(jar 增删/改动)自动重扫。"""
    vjars, mjars = instance_jars(game_dir, instance_id)
    jars = vjars + mjars
    if not jars:
        return None
    sig = _jar_signature(jars)
    cp = _cache_path(instance_id)
    if use_cache and os.path.isfile(cp):
        try:
            with open(cp, encoding="utf-8") as f:
                cached = json.load(f)
            if (cached.get("schema") == CACHE_SCHEMA
                    and cached.get("signature") == sig
                    and isinstance(cached.get("recipes"), list)):
                return cached
        except Exception:
            pass
    recipes, tags = [], {}
    for j in jars:
        r, t = scan_jar_recipes(j)
        recipes.extend(r)
        tags.update(t)
    # 去重(同 id 保留先扫到的:版本 jar 优先,再 mods)
    seen, uniq = set(), []
    for r in recipes:
        rid = r.get("id")
        if rid in seen:
            continue
        seen.add(rid)
        uniq.append(r)
    recipes = _resolve_ingredients(uniq, tags)
    data = {"schema": CACHE_SCHEMA, "signature": sig, "instance": instance_id,
            "recipes": recipes, "tags": tags,
            "scanned_at": time.strftime("%Y-%m-%d %H:%M"),
            "version_jars": vjars, "mods_jars": mjars}
    if use_cache:
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass
    return data


def list_instances_with_recipes(game_dir: str) -> list:
    """有可解析 jar 配方数据的实例 id(版本 jar 内含 recipe),按版本 jar 修改时间新→旧"""
    versions_dir = os.path.join(game_dir, "versions")
    if not os.path.isdir(versions_dir):
        return []
    try:
        names = os.listdir(versions_dir)
    except OSError:
        return []
    rows = []
    for name in names:
        vjars, _mj = instance_jars(game_dir, name)
        best = None
        for j in vjars:
            try:
                with zipfile.ZipFile(j) as z:
                    has = any("/recipe/" in e and e.endswith(".json") for e in z.namelist())
            except Exception:
                has = False
            if has:
                try:
                    m = os.path.getmtime(j)
                except OSError:
                    m = 0
                if best is None or m > best[0]:
                    best = (m, name)
        if best:
            rows.append(best)
    rows.sort(reverse=True)
    return [n for _m, n in rows]
