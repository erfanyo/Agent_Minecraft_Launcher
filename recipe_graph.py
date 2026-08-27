# -*- coding: utf-8 -*-
"""
JEI/配方数据分析器(启动器侧):
读取 bridge-mod 导出的 .bridge/recipes.json 与 .bridge/items.json,
提供:
1. 套娃合成计算:find_recipe_path(目标物品, 数量) → 一路拆到原材料
2. 完整合成树:describe_full(中文名/英文名/id) → 合成树(每步标注机器) + 材料总账
3. 中文名索引:从实例 mods 目录的 jar 语言文件(zh_cn.json/en_us.json)构建
   中文名/英文名 → 物品 id 映射,AI 直接传中文就能查
4. 物品参数比较:compare_items(属性) → 谁最强(挖掘等级/武器伤害/护甲等)

数据结构(与 bridge-mod 约定):
- recipes.json: [{id, type, output:{item,count}, ingredients:[{item,count}...]}]
- items.json:   [{id, max_stack, attributes:{attack_damage, armor, ...}, tags:[...]}]

数据定位:
- load_bridge_data(game_dir, instance_id) 指定实例;instance 缺省时自动探测
  所有实例,取 .bridge/recipes.json 最新导出的那个(避免"数据明明导出了却查不到")。
"""
import json
import os
import time
import zipfile
from collections import deque  # noqa: F401 (保留导入,避免其它模块误用)

import recipe_datapack  # 配方旁路:直接读 mod jar / 版本 jar 的 datapack 配方(无需进游戏)

# 配方类型 → 中文机器名(合成/加工设备)
MACHINE_CN = {
    "crafting": "工作台(3×3合成)",
    "crafting_shaped": "工作台(3×3合成)",
    "crafting_shapeless": "工作台(无序合成)",
    "crafting_special_*": "特殊合成(工作台)",
    "smelting": "熔炉",
    "blasting": "高炉",
    "smoking": "烟熏炉",
    "campfire_cooking": "营火",
    "stonecutting": "切石机",
    "smithing": "锻造台",
    "smithing_transform": "锻造台",
    "smithing_trim": "锻造台",
    # Mekanism 系机器
    "mekanism:metallurgic_infusing": "冶金灌注机",
    "mekanism:enriching": "富集仓",
    "mekanism:crushing": "粉碎机",
    "mekanism:combining": "组合机",
    "mekanism:injecting": "化学注入机",
    "mekanism:purifying": "净化仓",
    "mekanism:sawing": "精密锯木机",
    "mekanism:smelting": "电力冶炼炉",
    "mekanism:energized_smelting": "电力冶炼炉",
    "mekanism:pigment_extracting": "颜料提取器",
    "mekanism:painting": "颜料喷涂机",
    "mekanism:dissolution": "化学溶解室",
    "mekanism:crystallizing": "化学结晶器",
    "mekanism:oxidizing": "化学氧化机",
    "mekanism:washing": "化学清洗机",
    "mekanism:infusing": "化学灌注机",
    "mekanism:rotary": "气液转换机",
    "mekanism:separating": "电解分离机",
    "mekanism:reaction": "加压反应室",
    "mekanism:nucleosynthesizing": "原子核合成器",
    "mekanism:sps": "超临界移相器",
}

# 语言 key 前缀 → 物品 id 解析(如 item.mekanism.alloy_atomic → mekanism:alloy_atomic)
# 含 entity.(生物/实体) — 用户查攻略也要生物名(掉落/打法等),不只 item/block
_LANG_PREFIXES = ("item.", "block.", "entity.")

# Minecraft 自带基础物品的中文名兜底表:minecraft.jar 不在实例 mods 目录,
# 语言文件扫不到,这里内置一份常用表(mod 有翻译时会被覆盖)
MC_CN_ITEMS = {
    "minecraft:gold_ingot": "金锭", "minecraft:iron_ingot": "铁锭",
    "minecraft:copper_ingot": "铜锭", "minecraft:netherite_ingot": "下界合金锭",
    "minecraft:diamond": "钻石", "minecraft:emerald": "绿宝石",
    "minecraft:coal": "煤炭", "minecraft:charcoal": "木炭",
    "minecraft:redstone": "红石粉", "minecraft:lapis_lazuli": "青金石",
    "minecraft:stick": "木棍", "minecraft:planks": "木板",
    "minecraft:oak_planks": "橡木木板", "minecraft:oak_log": "橡木原木",
    "minecraft:stone": "石头", "minecraft:cobblestone": "圆石",
    "minecraft:obsidian": "黑曜石", "minecraft:sand": "沙子",
    "minecraft:glass": "玻璃", "minecraft:crafting_table": "工作台",
    "minecraft:furnace": "熔炉", "minecraft:chest": "箱子",
    "minecraft:gold_ore": "金矿石", "minecraft:iron_ore": "铁矿石",
    "minecraft:deepslate_gold_ore": "深层金矿石",
    "minecraft:deepslate_iron_ore": "深层铁矿石",
    "minecraft:coal_ore": "煤矿石", "minecraft:diamond_ore": "钻石矿石",
    "minecraft:raw_gold": "粗金", "minecraft:raw_iron": "粗铁",
    "minecraft:raw_gold_block": "粗金块", "minecraft:raw_iron_block": "粗铁块",
    "minecraft:gold_block": "金块", "minecraft:iron_block": "铁块",
    "minecraft:diamond_block": "钻石块", "minecraft:gold_nugget": "金粒",
    "minecraft:iron_nugget": "铁粒", "minecraft:netherite_scrap": "下界合金碎片",
    "minecraft:nether_gold_ore": "下界金矿石",
    "minecraft:apple": "苹果", "minecraft:bread": "面包",
    "minecraft:string": "线", "minecraft:leather": "皮革",
    "minecraft:feather": "羽毛", "minecraft:gunpowder": "火药",
    "minecraft:paper": "纸", "minecraft:book": "书",
    "minecraft:ender_pearl": "末影珍珠", "minecraft:blaze_rod": "烈焰棒",
    "minecraft:bone": "骨头", "minecraft:arrow": "箭",
    "minecraft:bow": "弓", "minecraft:diamond_pickaxe": "钻石镐",
    "minecraft:iron_pickaxe": "铁镐", "minecraft:diamond_sword": "钻石剑",
    "minecraft:dirt": "泥土", "minecraft:mycelium": "菌丝",
    "minecraft:gravel": "沙砾", "minecraft:clay": "黏土",
    "minecraft:soul_sand": "灵魂沙", "minecraft:glowstone": "萤石",
    "minecraft:quartz": "下界石英", "minecraft:flint": "燧石",
    "minecraft:flint_and_steel": "打火石", "minecraft:bucket": "铁桶",
    "minecraft:water_bucket": "水桶", "minecraft:lava_bucket": "熔岩桶",
    "minecraft:glass_bottle": "玻璃瓶", "minecraft:experience_bottle": "附魔之瓶",
    "minecraft:slime_ball": "黏液球", "minecraft:magma_cream": "岩浆膏",
    "minecraft:ender_eye": "末影之眼", "minecraft:ghast_tear": "恶魂之泪",
    "minecraft:blaze_powder": "烈焰粉", "minecraft:spider_eye": "蜘蛛眼",
    "minecraft:fermented_spider_eye": "发酵蛛眼", "minecraft:golden_apple": "金苹果",
    "minecraft:shield": "盾牌", "minecraft:elytra": "鞘翅",
}


def _lang_key_to_item(key: str) -> str | None:
    """把语言文件 key(item.<ns>.<path> 或 block.<ns>.<path>)转成物品 id"""
    for pre in _LANG_PREFIXES:
        if key.startswith(pre):
            rest = key[len(pre):]
            if rest.endswith(".name"):      # 旧版 key 尾巴带 .name
                rest = rest[:-5]
            if "." in rest:
                ns, path = rest.split(".", 1)
                if ns and path:
                    return f"{ns}:{path}"
    return None


def _is_real_item(item) -> bool:
    """可展开/显示的原料:排除旧式特殊伪原料 "(...)",但保留 "(chem:...)" 化学原料
    (旁路从 jar 读到的化学输入,如冶金灌注的灌注材料:可显示、计入材料账,但不递归展开)。"""
    return not (isinstance(item, str) and item.startswith("(")
                and not item.startswith("(chem:"))


def _real_ings(recipe: dict) -> list:
    """配方里可展开/显示的原料列表((chem:...) 保留,旧式 "(...)" 伪原料排除)"""
    return [i for i in recipe.get("ingredients", [])
            if i.get("item") and _is_real_item(i["item"])]


# 进程内中文索引缓存:mods 目录签名 → 索引,避免每次查询都重读 jar
_zh_cache = {}


def _mods_signature(mods_dir: str) -> str:
    try:
        names = sorted(os.listdir(mods_dir))
    except OSError:
        return ""
    parts = []
    for n in names:
        try:
            parts.append(f"{n}:{int(os.path.getmtime(os.path.join(mods_dir, n)))}")
        except OSError:
            parts.append(n)
    return "|".join(parts)


def _jar_mtime(jar_path: str) -> str:
    try:
        return f"{os.path.basename(jar_path)}:{int(os.path.getmtime(jar_path))}"
    except OSError:
        return os.path.basename(jar_path)


def build_zh_index(mods_dir: str, extra_jars: list | None = None) -> tuple:
    """扫实例 mods 目录里所有 jar 的语言文件,构建:
    (zh_to_id, en_to_id, id_to_zh)。带签名缓存,jar 没变就不重读。
    extra_jars:额外补充的 jar(如原版版本 jar,含 en_us 语言文件)。"""
    sig = _mods_signature(mods_dir) + "|" + "+".join(_jar_mtime(j) for j in (extra_jars or []))
    if mods_dir in _zh_cache and _zh_cache[mods_dir][0] == sig:
        return _zh_cache[mods_dir][1]
    zh_to_id = {v: k for k, v in MC_CN_ITEMS.items()}
    id_to_zh = dict(MC_CN_ITEMS)
    en_to_id = {}
    # 并入 mc_names 的口语/别名/内置名(中文叫法 → 规范 id),让 resolve_item 也吃口语
    try:
        from mc_names import alias_id_map
        for _alias, _id in alias_id_map().items():
            zh_to_id.setdefault(_alias, _id)
    except Exception:
        pass
    jars = []
    if os.path.isdir(mods_dir):
        try:
            files = sorted(os.listdir(mods_dir))
        except OSError:
            files = []
        jars = [os.path.join(mods_dir, f) for f in files if f.endswith(".jar")]
    jars += list(extra_jars or [])
    for path in jars:
        try:
            with zipfile.ZipFile(path) as z:
                entries = {e.filename for e in z.infolist()}
                for lang, target in (("en_us.json", en_to_id), ("zh_cn.json", zh_to_id)):
                    hit = next((e for e in entries if e.endswith(f"/lang/{lang}")), None)
                    if hit is None:
                        continue
                    try:
                        data = json.loads(z.read(hit).decode("utf-8", errors="replace"))
                    except Exception:
                        continue
                    for key, val in data.items():
                        if not isinstance(val, str):
                            continue
                        item_id = _lang_key_to_item(key)
                        if not item_id:
                            continue
                        name = val.strip()
                        if not name or len(name) > 30:
                            continue
                        target[name] = item_id
                        if lang == "zh_cn.json":
                            id_to_zh[item_id] = name      # 中文优先
                        else:
                            id_to_zh.setdefault(item_id, name)  # 英文兜底
        except Exception:
            continue
    _zh_cache[mods_dir] = (sig, (zh_to_id, en_to_id, id_to_zh))
    return zh_to_id, en_to_id, id_to_zh


class RecipeData:
    def __init__(self, recipes: list, items: list,
                 source_instance: str | None = None, exported_at: str | None = None,
                 zh_to_id: dict | None = None, en_to_id: dict | None = None,
                 id_to_zh: dict | None = None):
        self.recipes = recipes
        self.items = items
        self.source_instance = source_instance   # 数据来自哪个实例
        self.exported_at = exported_at           # 导出时间(字符串)
        self.zh_to_id = zh_to_id or {}
        self.en_to_id = en_to_id or {}
        self.id_to_zh = id_to_zh or {}
        # 输出物品 → 可用配方列表(先按"原料不含该物品本身"排序,避免套娃死循环)
        self.by_output = {}
        for r in recipes:
            out = r.get("output", {}).get("item")
            if out:
                self.by_output.setdefault(out, []).append(r)
        # 查询缓存(同一次启动内重复查询不重算,省 IO/时间;配 quick_ref 落盘可跨会话)
        self._path_cache = {}
        self._cmp_cache = {}

    # ---------- 名称解析 ----------
    def resolve_item(self, name: str) -> str | None:
        """把 中文名/英文显示名/id 统一解析成物品 id(如 终极感应供应器 → mekanism:ultimate_induction_provider)"""
        name = (name or "").strip()
        if not name:
            return None
        low = name.lower()
        if ":" in low:
            return low
        if low in self.zh_to_id:
            return self.zh_to_id[low]
        if low in self.en_to_id:
            return self.en_to_id[low]
        # 去掉空格/下划线再试(如 "ultimate induction provider")
        compact = low.replace(" ", "_")
        if compact in self.en_to_id:
            return self.en_to_id[compact]
        if compact in self.zh_to_id:
            return self.zh_to_id[compact]
        return "minecraft:" + compact

    def display(self, item_id: str) -> str:
        """物品 id → 显示名:有中文用中文,附 id 方便 AI 继续查"""
        if isinstance(item_id, str) and item_id.startswith("(chem:"):
            return f"化学:{item_id[6:-1]}"
        zh = self.id_to_zh.get(item_id)
        return f"{zh}({item_id})" if zh else item_id

    # ---------- 套娃合成 ----------
    def find_recipe_path(self, target_item: str, count: int = 1, depth: int = 6) -> dict:
        """计算合成 {count} 个 target_item 需要的原材料树(套娃展开)。
        返回 {item, need, steps:[...]} 或 {error}。结果按 (item,count) 缓存。"""
        target_item = (target_item or "").strip().lower()
        if not target_item.startswith("minecraft:") and ":" not in target_item:
            target_item = "minecraft:" + target_item
        key = (target_item, count)
        if key in self._path_cache:
            return self._path_cache[key]
        plan = {}
        ok = self._expand(target_item, count, plan, depth)
        if not ok:
            result = {"error": f"找不到 {target_item} 的合成配方(可能是自然生成/挖掘获取)"}
        else:
            result = {"item": target_item, "need": count, "steps": plan}
        self._path_cache[key] = result
        return result

    def _expand(self, item: str, need: int, plan: dict, depth: int) -> bool:
        """把 need 个 item 拆成原料,写进 plan(item -> 需要量);返回能否完全拆解"""
        if depth <= 0:
            return False
        recipe = self._pick_recipe(item)
        if recipe is None or self._is_unpack(recipe):
            # 无法合成 / 拆块配方:当作原材料(或不可获得)
            plan[item] = plan.get(item, 0) + need
            return True
        ings = _real_ings(recipe)
        if not ings:
            # 空原料配方(如冶金灌注的灌注类型 bridge 未导出):当作"需要直接获得"
            plan[item] = plan.get(item, 0) + need
            return True
        out_count = recipe["output"].get("count", 1) or 1
        # 需要做几炉
        batches = -(-need // out_count)   # 向上取整
        for ing in ings:
            ing_item = ing["item"]
            ing_need = ing.get("count", 1) * batches
            if ing_item == item:
                continue   # 防止自引用死循环(如某种无限合成)
            if not self._expand(ing_item, ing_need, plan, depth - 1):
                return False
        return True

    def _is_unpack(self, recipe: dict) -> bool:
        """拆块配方:1 个原料 → N 个同材料件,且存在反向合成配方
        (如 1 粗金块 → 9 粗金,反向 9 粗金 → 1 粗金块)。
        套娃展开时跳过这类配方——拆块不是"合成到原材料"的路径,
        直接把它当可获得的原材料,避免 block⇄item 每层 ×9 循环爆炸。"""
        ings = _real_ings(recipe)
        if len(ings) != 1:
            return False
        out = recipe.get("output", {})
        out_item = out.get("item")
        if not out_item or (out.get("count", 1) or 1) < 2:
            return False
        ing_item = ings[0]["item"]
        if ing_item == out_item:
            return False
        # 反向:该原料(如粗金块)存在配方把它合成出来,且该配方的原料含本配方输出
        # (粗金) → block⇄item 互转,判定为拆块配方
        for r2 in self.by_output.get(ing_item, []):
            if r2.get("output", {}).get("item") != ing_item:
                continue
            r2_ings = [i.get("item") for i in _real_ings(r2)]
            if out_item in r2_ings:
                return True
        return False

    def _pick_recipe(self, item: str) -> dict | None:
        """选一个配方:优先"非拆块、原料非空且数量少"的(避免空原料的特殊配方
        和拆块配方,也避免套娃环);实在没有才退回。"""
        cands = self.by_output.get(item) or []
        if not cands:
            return None

        def nonempty(r):
            return _real_ings(r)

        cands.sort(key=lambda r: (1 if self._is_unpack(r) else 0,
                                  0 if nonempty(r) else 1,
                                  len(nonempty(r))))
        return cands[0]

    def recipes_for(self, item: str) -> list:
        """物品的所有配方(EMI 风格:一个物品可能工作台/熔炉/机器都能做,全部列出)。
        返回 [{machine, type, ingredients:[显示文本], recipe}] 按"非拆块/非空/原料少"排序。"""
        target = self.resolve_item(item)
        if target is None:
            return []
        cands = self.by_output.get(target) or []

        def nonempty(r):
            return _real_ings(r)

        cands.sort(key=lambda r: (1 if self._is_unpack(r) else 0,
                                  0 if nonempty(r) else 1,
                                  len(nonempty(r))))
        out = []
        for r in cands:
            rtype = r.get("type") or ""
            mach = MACHINE_CN.get(rtype, rtype or "特殊工序")
            ings = [f"{self.display(i['item'])}×{i.get('count', 1)}" for i in nonempty(r)]
            out.append({"machine": mach, "type": rtype, "ingredients": ings, "recipe": r})
        return out

    # ---------- 完整合成树 + 材料总账(EMI 风格) ----------
    def describe_recipe(self, item: str, count: int = 1, recipe_index: int = 0,
                        depth: int = 8, max_lines: int = 50) -> str:
        """EMI 风格完整配方:先列出该物品的全部合成方式(工作台/熔炉/机器...),
        再用选中的配方(默认第 1 种,可 recipe_index=N 切换)套娃展开合成树 + 材料总账。
        item 支持中文名。树里每个数字 = 总共需要合成/获得的数量(已按一炉产出向上取整)。"""
        target = self.resolve_item(item)
        if target is None:
            return f"无法识别物品:{item}"
        all_rec = self.recipes_for(target)
        if not all_rec:
            return f"找不到 {target} 的合成配方(可能自然生成/挖掘获取)"
        idx = max(0, min(recipe_index, len(all_rec) - 1))

        lines = [f"{self.display(target)}  — 共 {len(all_rec)} 种配方:"]
        for i, r in enumerate(all_rec):
            mark = "  ◀ 当前展开" if i == idx else ""
            ing_txt = " + ".join(r["ingredients"]) or "(特殊工序,原料未导出,需游戏内确认)"
            lines.append(f"  [{i + 1}] {r['machine']}: {ing_txt}{mark}")
        if len(all_rec) > 1:
            lines.append("(换配方展开:下次查询加 recipe_index=N, N 为上面的编号-1)")

        tree = self._tree_node(target, count, depth, set(),
                               forced_recipe=all_rec[idx]["recipe"])
        lines.append("")
        lines.append(f"【合成树 · 用第 {idx + 1} 种配方】(数字=总共需要):")
        self._fmt_tree(tree, lines, "", True, max_lines)
        # 材料总账:聚合所有叶子(不可再展开/特殊工序/达上限)的原材料
        acc = {}
        self._collect_leaf(tree, acc)
        lines.append("")
        lines.append("【材料总账】(展开到不能继续合成的原材料):")
        for it, n in sorted(acc.items(), key=lambda x: -x[1]):
            lines.append(f"  {self.display(it)} ×{n}")
        return "\n".join(lines)

    def describe_full(self, item: str, count: int = 1, max_lines: int = 45) -> str:
        """兼容旧接口:完整套娃展开(等效 describe_recipe 用第 1 种配方)"""
        return self.describe_recipe(item, count, recipe_index=0, max_lines=max_lines)

    def _tree_node(self, item: str, need: int, depth: int, seen: set,
                   forced_recipe: dict | None = None) -> dict | None:
        recipe = forced_recipe if forced_recipe is not None else self._pick_recipe(item)
        if recipe is None or (forced_recipe is None and self._is_unpack(recipe)):
            # 无配方 / 拆块配方(1 block→9 item):当作可获得的原材料(叶子)
            return {"item": item, "need": need, "machine": None, "leaf": True,
                    "children": [], "note": None, "n_recipes": 0}
        rtype = recipe.get("type") or ""
        machine = MACHINE_CN.get(rtype, rtype or "特殊工序")
        n_recipes = len(self.by_output.get(item) or [])   # 该物品共有几种配方(EMI 提示)
        if item in seen or depth <= 0:
            return {"item": item, "need": need, "machine": machine, "leaf": True,
                    "children": [], "note": "…(已达展开上限)", "n_recipes": n_recipes}
        ings = [i for i in recipe.get("ingredients", [])
                if i.get("item") and not i["item"].startswith("(")]
        if not ings:
            return {"item": item, "need": need, "machine": machine, "leaf": True,
                    "children": [], "note": "(特殊工序/原料未导出,需游戏内确认)",
                    "n_recipes": n_recipes}
        out_count = recipe.get("output", {}).get("count", 1) or 1
        batches = -(-need // out_count)
        children = []
        for ing in ings:
            iid = ing["item"]
            if iid == item:
                continue
            children.append(self._tree_node(iid, ing.get("count", 1) * batches,
                                            depth - 1, seen | {item}))
        return {"item": item, "need": need, "machine": machine, "leaf": False,
                "children": children, "count": out_count, "batches": batches,
                "n_recipes": n_recipes}

    def _fmt_tree(self, node, lines, prefix, is_last, max_lines, depth=0, _cut=None):
        if _cut is None:
            _cut = [False]
        if len(lines) >= max_lines:
            _cut[0] = True
            return
        label = self.display(node["item"])
        multi = f"  ({node.get('n_recipes', 0)} 种配方)" if node.get("n_recipes", 0) > 1 else ""
        mach = f"  ← {node['machine']}" if node.get("machine") else ""
        note = f"  {node['note']}" if node.get("note") else ""
        if depth == 0:
            lines.append(f"{label} ×{node['need']}{multi}{mach}{note}")
        else:
            branch = "└─ " if is_last else "├─ "
            lines.append(f"{prefix}{branch}{label} ×{node['need']}{multi}{mach}{note}")
            prefix += "   " if is_last else "│  "
        kids = node.get("children", [])
        for i, c in enumerate(kids):
            self._fmt_tree(c, lines, prefix, i == len(kids) - 1, max_lines, depth + 1, _cut)
            if _cut[0]:
                break
        if _cut[0] and (not lines or not lines[-1].startswith("…")):
            lines.append("…(已截断,可指定更小的 count 或单独查某一层)")

    def _collect_leaf(self, node, acc: dict):
        if not node.get("children"):
            acc[node["item"]] = acc.get(node["item"], 0) + node["need"]
            return
        for c in node["children"]:
            self._collect_leaf(c, acc)

    # ---------- 给 AI 的摘要 ----------
    def summarize(self, target_item: str, count: int = 1, max_lines: int = 25) -> str:
        r = self.find_recipe_path(target_item, count)
        if "error" in r:
            return r["error"]
        lines = [f"合成 {count} 个 {self.display(r['item'])} 需要:"]
        for item, need in sorted(r["steps"].items(), key=lambda x: -x[1]):
            lines.append(f"  {self.display(item)} × {need}")
        if len(lines) > max_lines:
            lines = lines[:max_lines] + ["…(继续展开中)"]
        return "\n".join(lines)

    def quick_recipe(self, target_item: str) -> str:
        """精简合成速查(只列直接配方一层,不套娃展开)——给 AI 用,省 token。
        如:钻石镐 = 钻石×3 + 木棍×2 [工作台]。查不到返回提示。"""
        target = self.resolve_item(target_item)
        if target is None:
            return f"无法识别物品:{target_item}"
        recipe = self._pick_recipe(target)
        if recipe is None:
            return f"{target} 没有直接合成配方(可能自然生成/挖掘/其他方式获取)"
        out = recipe["output"]
        rtype = recipe.get("type") or ""
        mach = MACHINE_CN.get(rtype, rtype or "特殊工序")
        parts = []
        for ing in recipe.get("ingredients", []):
            item = ing.get("item")
            if item and _is_real_item(item):
                parts.append(f"{self.display(item)}×{ing.get('count', 1)}")
        s = f"{out['item']} = " + (" + ".join(parts) if parts else "(特殊工序,原料未导出)")
        return f"{s}  [{mach}]"

    # ---------- 物品参数比较 ----------
    def compare_items(self, attribute: str, top_n: int = 10) -> list:
        """按属性排序物品(如 attack_damage / armor / armor_toughness / attack_speed)。
        attribute 支持中文别名:武器伤害→attack_damage, 护甲→armor, 护甲韧性→armor_toughness。
        结果按 (attribute, top_n) 缓存。"""
        alias = {
            # 中文
            "武器伤害": "attack_damage", "伤害": "attack_damage",
            "攻击伤害": "attack_damage", "护甲": "armor",
            "护甲韧性": "armor_toughness", "攻速": "attack_speed",
            "挖掘等级": "mining_level",
            # 英文(小模型常输出英文,直接映射,不依赖模型表现)
            "damage": "attack_damage", "attack_damage": "attack_damage",
            "armor": "armor", "armor_toughness": "armor_toughness",
            "attack_speed": "attack_speed", "speed": "attack_speed",
            "mining_level": "mining_level", "mining": "mining_level",
            "toughness": "armor_toughness",
        }
        attr = alias.get(attribute, attribute)
        if attr != attribute:
            attr = attr  # 已映射
        elif isinstance(attribute, str):
            # 未命中映射:去空格/小写后再试一次英文(容错 " Damage " 之类)
            cleaned = attribute.strip().lower()
            attr = alias.get(cleaned, cleaned)
        key = (attr, top_n)
        if key in self._cmp_cache:
            return self._cmp_cache[key]
        if attr == "mining_level":
            rows = self._compare_mining(top_n)
        else:
            rows = []
            for it in self.items:
                v = it.get("attributes", {}).get(attr)
                if v is None or v <= 0:
                    continue
                rows.append((it["id"], v))
            rows.sort(key=lambda x: -x[1])
            rows = [{"item": i, attr: v} for i, v in rows[:top_n]]
        self._cmp_cache[key] = rows
        return rows

    def _compare_mining(self, top_n: int = 10) -> list:
        """挖掘等级按工具标签推断:wooden=0 stone=1 iron=2 diamond=3 netherite=4"""
        tiers = {
            "minecraft:wooden_tools": 0,
            "minecraft:stone_tools": 1,
            "minecraft:iron_tools": 2,
            "minecraft:golden_tools": 2,
            "minecraft:diamond_tools": 3,
            "minecraft:netherite_tools": 4,
        }
        rows = []
        for it in self.items:
            tags = set(it.get("tags", []))
            level = max((tiers[t] for t in tags if t in tiers), default=-1)
            if level >= 0:
                rows.append((it["id"], level))
        rows.sort(key=lambda x: (-x[1], x[0]))
        return [{"item": i, "mining_level": v} for i, v in rows[:top_n]]


# ---------- 数据定位与加载 ----------
def locate_bridge(game_dir: str, instance_id: str | None = None):
    """定位实例的 .bridge 数据,返回 (instance_id, base_dir, rec_path) 或 None。
    instance_id 缺省时自动探测所有实例,取 recipes.json 最新导出的。"""
    versions_dir = os.path.join(game_dir, "versions")
    if instance_id:
        base = os.path.join(versions_dir, instance_id)
        rec = os.path.join(base, ".bridge", "recipes.json")
        return (instance_id, base, rec) if os.path.isfile(rec) else None
    if os.path.isdir(versions_dir):
        best = None
        try:
            names = os.listdir(versions_dir)
        except OSError:
            names = []
        for name in names:
            rec = os.path.join(versions_dir, name, ".bridge", "recipes.json")
            if os.path.isfile(rec):
                m = os.path.getmtime(rec)
                if best is None or m > best[0]:
                    best = (m, name, rec)
        if best:
            _, name, rec = best
            return (name, os.path.join(versions_dir, name), rec)
    return None


def instances_with_bridge(game_dir: str) -> list:
    """列出已导出过配方数据的实例 id(按导出时间新→旧)"""
    versions_dir = os.path.join(game_dir, "versions")
    if not os.path.isdir(versions_dir):
        return []
    rows = []
    try:
        names = os.listdir(versions_dir)
    except OSError:
        return []
    for name in names:
        rec = os.path.join(versions_dir, name, ".bridge", "recipes.json")
        if os.path.isfile(rec):
            rows.append((os.path.getmtime(rec), name))
    rows.sort(reverse=True)
    return [n for _m, n in rows]


def load_bridge_data(game_dir: str, instance_id: str | None = None) -> RecipeData | None:
    """读实例运行目录 .bridge/recipes.json + items.json;
    instance_id 缺省时自动探测最新导出的实例(修正"数据明明导出了却查不到")。
    顺带从该实例 mods 目录的 jar 构建中文名索引。找不到返回 None。"""
    found = locate_bridge(game_dir, instance_id)
    if found is None:
        return None
    inst, base, rec_path = found
    try:
        recipes = json.load(open(rec_path, encoding="utf-8"))
    except Exception:
        recipes = []
    it_path = os.path.join(base, ".bridge", "items.json")
    try:
        items = json.load(open(it_path, encoding="utf-8"))
    except Exception:
        items = []
    exported_at = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(rec_path)))
    zh_to_id, en_to_id, id_to_zh = build_zh_index(os.path.join(base, "mods"))
    return RecipeData(recipes, items,
                      source_instance=inst, exported_at=exported_at,
                      zh_to_id=zh_to_id, en_to_id=en_to_id, id_to_zh=id_to_zh)


# ---------- 配方旁路(直接读 jar,无需进游戏)+ bridge 合并 ----------
def load_recipe_data(game_dir: str, instance_id: str | None = None,
                     include_bridge: bool = True, use_cache: bool = True) -> RecipeData | None:
    """配方查询统一入口(旁路 + bridge 合并):

    - **jar 数据 = 基座**:直接解析实例 mods/*.jar 与版本 jar 里的 datapack 配方,
      已装 mod 无需进游戏即可查(recipe_datapack.py)
    - **bridge 数据 = 覆盖**:.bridge/recipes.json(实际生效),同 id 以 bridge 为准
    - instance 缺省:优先最新 bridge 实例;否则取有 jar 配方数据的实例
    - 返回的 RecipeData 带 source_kind:"bridge+jar" / "jar" / "bridge"
    """
    # 1) 定位实例
    inst = instance_id
    bridge_found = None
    if include_bridge:
        bridge_found = locate_bridge(game_dir, inst)
        if bridge_found:
            inst = bridge_found[0]
    if inst is None:
        jinst = recipe_datapack.list_instances_with_recipes(game_dir)
        if jinst:
            inst = jinst[0]
    if inst is None:
        return None
    base = os.path.join(game_dir, "versions", inst)

    # 2) jar 旁路(基座)
    scan = recipe_datapack.scan_instance(game_dir, inst, use_cache=use_cache)
    jar_recipes = scan["recipes"] if scan else []

    # 3) bridge(覆盖)
    bridge_recipes, items, exported_at = [], [], None
    if bridge_found and bridge_found[0] == inst:
        rec_path = bridge_found[2]
        try:
            bridge_recipes = json.load(open(rec_path, encoding="utf-8"))
        except Exception:
            bridge_recipes = []
        it_path = os.path.join(base, ".bridge", "items.json")
        try:
            items = json.load(open(it_path, encoding="utf-8"))
        except Exception:
            items = []
        exported_at = time.strftime("%Y-%m-%d %H:%M",
                                    time.localtime(os.path.getmtime(rec_path)))
    if not jar_recipes and not bridge_recipes:
        return None

    # 4) 合并:bridge 覆盖同 id(实际生效),但 bridge 同 id 配方"原料未导出"(空原料)
    #    而 jar 旁路读到了原料 → 用 jar 原料补上缺口(验收标准 4:特殊配方旁路直接补)
    jar_by_id = {r.get("id"): r for r in jar_recipes if r.get("id")}
    merged, used_ids = [], set()
    for r in bridge_recipes:
        rid = r.get("id")
        if rid in used_ids:
            continue
        used_ids.add(rid)
        jr = jar_by_id.get(rid)
        if jr and not _real_ings(r) and _real_ings(jr):
            r = dict(r)                       # 保留 bridge 元数据(实际生效)
            r["ingredients"] = jr["ingredients"]   # 原料由 jar 旁路补齐
        merged.append(r)
    merged += [r for r in jar_recipes if r.get("id") not in used_ids]

    # 5) 中文名索引:mods jar + 版本 jar(原版 en_us 等)
    vjars = scan["version_jars"] if scan else []
    zh_to_id, en_to_id, id_to_zh = build_zh_index(os.path.join(base, "mods"),
                                                  extra_jars=vjars or None)

    if bridge_recipes and jar_recipes:
        source_kind = "bridge+jar"
    elif jar_recipes:
        source_kind = "jar"
    else:
        source_kind = "bridge"
    exported_disp = exported_at
    if not exported_disp and scan:
        exported_disp = scan.get("scanned_at", "")
    rd = RecipeData(merged, items, source_instance=inst, exported_at=exported_disp,
                    zh_to_id=zh_to_id, en_to_id=en_to_id, id_to_zh=id_to_zh)
    rd.source_kind = source_kind
    return rd


def instances_with_recipe_data(game_dir: str) -> list:
    """有配方数据的实例(bridge 导出优先,其次 jar 旁路可解析),新→旧"""
    b = instances_with_bridge(game_dir)
    j = recipe_datapack.list_instances_with_recipes(game_dir)
    return b + [x for x in j if x not in b]
