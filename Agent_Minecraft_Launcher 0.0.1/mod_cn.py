# -*- coding: utf-8 -*-
"""
本地中文名数据库:Modrinth slug → 中文名。

参考 PCL2 的做法:平台 API 只认英文 slug,中文名靠本地库翻译。
这里维护一份常用 Mod 的对照表(起步 60+ 个,以后随用随加)。
搜索含中文的关键词时,先查这个库,把中文名映射成 slug,再去 Modrinth 取详情。
"""
CN_NAMES = {
    # ---- 性能优化 ----
    "sodium": "钠 (Sodium)",
    "lithium": "锂 (Lithium)",
    "phosphor": "磷 (Phosphor)",
    "ferrite-core": "铁氧体核心 (FerriteCore)",
    "starlight": "星光 (Starlight)",
    "immediatelyfast": "立刻快 (ImmediatelyFast)",
    "modernfix": "ModernFix",
    # ---- 光影 ----
    "iris": "鸢尾花 (Iris Shaders)",
    "oculus": "视界 (Oculus)",
    "embeddium": "钕 (Embeddium)",
    "rubidium": "铷 (Rubidium)",
    "optifine": "OptiFine(高清修复)",
    # ---- 加载器与 API ----
    "fabric-api": "Fabric API",
    "fabric-language-kotlin": "Fabric Kotlin 语言支持",
    "architectury-api": "Architectury API",
    "cloth-config": "布料配置 (Cloth Config)",
    # ---- 物品/合成/信息 ----
    "jei": "JEI 物品管理器 (Just Enough Items)",
    "rei": "REI 物品管理器 (Roughly Enough Items)",
    "emi": "EMI 物品管理器",
    "jade": "玉 (Jade)",
    "wthit": "WTHIT",
    "appleskin": "苹果皮 (AppleSkin)",
    # ---- 地图/世界 ----
    "xaeros-minimap": "Xaero 的小地图",
    "xaeros-world-map": "Xaero 的世界地图",
    "journeymap": "旅行地图 (JourneyMap)",
    "worldedit": "创世神 (WorldEdit)",
    "worldguard": "世界守护 (WorldGuard)",
    # ---- 玩法/内容 ----
    "create": "机械动力 (Create)",
    "tinkers-construct": "匠魂 (Tinkers' Construct)",
    "thermal-foundation": "热力基本 (Thermal Foundation)",
    "ae2": "应用能源2 (Applied Energistics 2)",
    "refined-storage": "精致存储 (Refined Storage)",
    "projecte": "等价交换重置版 (ProjectE)",
    "botania": "植物魔法 (Botania)",
    "quark": "夸克 (Quark)",
    "draconic-evolution": "龙之研究 (Draconic Evolution)",
    "twilight-forest": "暮色森林 (The Twilight Forest)",
    "aether": "天境 (The Aether)",
    "ice-and-fire-dragons": "冰与火之歌 (Ice and Fire)",
    "iron-chests": "铁箱子 (Iron Chests)",
    "backpacked": "背包 (Backpacked)",
    "carry-on": "举起来 (Carry On)",
    "gravestone-mod": "墓碑 (Gravestone Mod)",
    "corpse": "尸体 (Corpse)",
    "inventory-profiles-next": "物品栏整理 (Inventory Profiles Next)",
    "controllable": "控制器支持 (Controllable)",
    "betterf3": "更好的 F3 (BetterF3)",
    "mouse-tweaks": "鼠标手势 (Mouse Tweaks)",
    "smooth-scroll": "平滑滚动 (Smooth Scroll)",
    # ---- 农业/食物 ----
    "farmers-delight": "农夫乐事 (Farmer's Delight)",
    "pam-harvestcraft-2-food-core": "潘马斯农场2 (Pam's HarvestCraft 2)",
    # ---- 魔法 ----
    "irons-spells-n-spellbooks": "铁魔法 (Iron's Spells 'n Spellbooks)",
    "ars-nouveau": "新生魔法艺术 (Ars Nouveau)",
    "occultism": "神秘学 (Occultism)",
    # ---- 科技 ----
    "mekanism": "通用机械 (Mekanism)",
    "industrial-foregoing": "工业先锋 (Industrial Foregoing)",
    "pneumaticcraft-repressurized": "气动工艺 (PneumaticCraft)",
    "immersiveengineering": "沉浸工程 (Immersive Engineering)",
    "powah": "帕瓦 (Powah)",
    "mekanism-generators": "通用机械发电机 (Mekanism Generators)",
    # ---- 存储 ----
    "storage-drawers": "存储抽屉 (Storage Drawers)",
    "functional-storage": "功能存储 (Functional Storage)",
    "trashslot": "垃圾槽 (TrashSlot)",
    "enderchests": "末影箱子 (EnderChests)",
}


def has_cjk(text: str) -> bool:
    """判断文本里是否含中文(CJK 统一表意文字)"""
    return any("\u4e00" <= c <= "\u9fff" for c in text)


def find_slugs_by_cn(query: str) -> list:
    """用中文名(或其片段)查库,返回匹配的 Modrinth slug 列表"""
    q = query.strip().lower()
    hits = []
    for slug, cn in CN_NAMES.items():
        if q in cn.lower() or cn.lower() in q:
            hits.append(slug)
    return hits
