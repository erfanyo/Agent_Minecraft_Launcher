# -*- coding: utf-8 -*-
"""
Agent 工具层:CLI 命令与 AI 工具调用共用的函数实现。

设计:每个函数"文本进 → 文本出",既被 `cli.py` 的命令调用,
也被 `assistant.py` 的工具调用(tool calling)当作工具执行体。
权限不在这一层——由调用方(assistant 的执行器)按只读/工作区可写拦截。
"""
import os

import paths
from backup import backup_instance as _backup_impl
from instances import scan_instances
from loaders import install_loader
from modpack import _ensure_base as ensure_base
from modrinth import download_mod, search_mods_cn
from settings import load_settings, save_settings

# 可选 Mod 清单(与 GUI 共用;定义在这里避免 CLI 依赖 Qt)
SHADER_MODS = {"fabric": "iris", "forge": "oculus", "neoforge": "iris"}
OPTIMIZE_MODS = {
    "fabric": ["sodium", "lithium", "ferrite-core"],
    "forge": ["embeddium", "ferrite-core"],
    "neoforge": ["sodium", "lithium", "ferrite-core"],
}


# ---------------- 读取类(只读) ----------------
def _gd(game_dir):
    """game_dir 缺省时用当前生效的游戏目录(设置里可改)"""
    return game_dir if game_dir is not None else paths.GAME_DIR


def list_instances(game_dir: str = None) -> str:
    insts = scan_instances(_gd(game_dir))
    if not insts:
        return "(还没有实例)"
    return "\n".join(f"{i['id']}  ({i['loader'] or '原版'} ← {i['base']})" for i in insts)


def list_mods(instance: str, game_dir: str = None) -> str:
    mods_dir = os.path.join(_gd(game_dir), "versions", instance, "mods")
    if not os.path.isdir(mods_dir):
        return f"({instance} 没有 mods 目录)"
    files = sorted(f for f in os.listdir(mods_dir) if f.endswith(".jar"))
    return "\n".join(files) if files else "(mods 目录为空)"


def search_mods(query: str, game_version: str = "", loader: str = "") -> str:
    """搜 Mod(支持中文名)。game_version/loader 为空时不按它们过滤"""
    hits = search_mods_cn(query, game_version or None, loader or None)
    if not hits:
        return "(没有找到结果)"
    return "\n".join(f"{h['title']}  slug={h['slug']}  ⬇{h['downloads']:,}"
                     for h in hits[:15])


def read_instance_log(instance: str, tail: int = 80, game_dir: str = None) -> str:
    log = os.path.join(_gd(game_dir), "versions", instance, "logs", "latest.log")
    if not os.path.isfile(log):
        return f"({instance} 还没有日志文件)"
    try:
        lines = open(log, encoding="utf-8", errors="replace").read().splitlines()
    except Exception as e:
        return f"(读取日志失败:{e})"
    return "\n".join(lines[-tail:])


def read_crash_report(instance: str, game_dir: str = None) -> str:
    cr_dir = os.path.join(_gd(game_dir), "versions", instance, "crash-reports")
    if not os.path.isdir(cr_dir):
        return f"({instance} 没有崩溃报告目录)"
    files = sorted(os.listdir(cr_dir), reverse=True)
    if not files:
        return f"({instance} 没有崩溃报告)"
    try:
        text = open(os.path.join(cr_dir, files[0]), encoding="utf-8",
                    errors="replace").read()
    except Exception as e:
        return f"(读取崩溃报告失败:{e})"
    return text[:4000]  # 截断,避免塞爆上下文


def get_settings() -> str:
    s = load_settings()
    return "\n".join(f"{k}: {v}" for k, v in s.items() if k != "ai_api_key")


# ---------------- 写操作类(需要工作区写权限) ----------------
def install_mod(slug: str, instance: str, version: str = "",
                game_dir: str = None) -> str:
    """给某实例安装 Mod(按实例的加载器 + 基础版本过滤)"""
    game_dir = _gd(game_dir)
    inst = next((i for i in scan_instances(game_dir) if i["id"] == instance), None)
    if inst is None:
        return f"错误:没有实例 {instance}(可用 list_instances 查看)"
    loader = inst["loader"]
    if loader not in ("fabric", "forge", "neoforge"):
        return f"错误:{instance} 不是 Mod 实例(加载器:{loader or '原版'})"
    gv = inst["base"]
    mods_dir = os.path.join(game_dir, "versions", instance, "mods")
    filename = download_mod(slug, gv, loader, mods_dir, version_number=version or None)
    if filename:
        return f"已安装 {filename} 到 {instance}"
    return (f"错误:{slug} 没有 {gv}+{loader} 的"
            f"{'指定版本' if version else '可用'}版本")


def _resolve_slug(name: str) -> str:
    """中文名 → Modrinth slug(查本地库);英文 slug / 已是 slug 的原样返回"""
    name = name.strip()
    if not name:
        return name
    from mod_cn import find_slugs_by_cn, has_cjk
    if has_cjk(name):
        hits = find_slugs_by_cn(name)
        if hits:
            return hits[0]
    return name


def install_mods(slugs, instance: str, game_dir: str = None) -> str:
    """批量给实例安装多个 Mod(一次调用装完,省 AI 工具轮数)。
    slugs 支持中文名(如 钠/锂/玉/JEI)或英文 slug;可传 list,也可传逗号分隔字符串。
    逐项报告成功/失败,返回汇总。"""
    game_dir = _gd(game_dir)
    if isinstance(slugs, str):
        slugs = [s.strip() for s in slugs.replace("，", ",").split(",") if s.strip()]
    slugs = [s for s in (slugs or []) if str(s).strip()]
    if not slugs:
        return "错误:没有要安装的 Mod"
    inst = next((i for i in scan_instances(game_dir) if i["id"] == instance), None)
    if inst is None:
        return f"错误:没有实例 {instance}(可用 list_instances 查看)"
    loader = inst["loader"]
    if loader not in ("fabric", "forge", "neoforge"):
        return f"错误:{instance} 不是 Mod 实例(加载器:{loader or '原版'})"
    gv = inst["base"]
    mods_dir = os.path.join(game_dir, "versions", instance, "mods")

    def dl_one(s):
        slug = _resolve_slug(str(s))
        filename = download_mod(slug, gv, loader, mods_dir)
        if filename:
            return f"• {slug}: 已安装 {filename} ✅"
        return f"• {slug}: 错误:没有 {gv}+{loader} 的可用版本 ❌"

    # 并行下载(最多 4 个同时下),结果按输入顺序汇总
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = {}
    if len(slugs) <= 1:
        for s in slugs:
            results[str(s)] = dl_one(s)
    else:
        with ThreadPoolExecutor(max_workers=min(4, len(slugs))) as ex:
            futs = {ex.submit(dl_one, s): s for s in slugs}
            for f in as_completed(futs):
                s = futs[f]
                try:
                    results[s] = f.result()
                except Exception as e:
                    results[s] = f"• {s}: 安装失败:{type(e).__name__}: {e} ❌"
    lines = [results[str(s)] for s in slugs]
    ok = sum(1 for l in lines if "已安装" in l)
    return f"共 {len(slugs)} 个,成功 {ok} 个:\n" + "\n".join(lines)


def install_instance(version: str, loader: str = "", loader_version: str = "",
                     shader: bool = False, optimize: bool = False,
                     game_dir: str = None, status=print) -> str:
    """创建实例:原版本体 + (可选)加载器 + (可选)光影/优化 Mod"""
    game_dir = _gd(game_dir)
    ensure_base(version, game_dir, status_callback=status, progress_callback=None)
    instance_id = version
    if loader:
        instance_id = install_loader(loader, version, game_dir,
                                     loader_version=loader_version or None,
                                     status_callback=status)
        if shader or optimize:
            mods_dir = os.path.join(game_dir, "versions", instance_id, "mods")
            mr_loader = {"fabric": "fabric", "forge": "forge", "neoforge": "neoforge"}.get(loader)
            if shader and mr_loader:
                slug = SHADER_MODS.get(mr_loader)
                if slug:
                    download_mod(slug, version, mr_loader, mods_dir)
            if optimize and mr_loader:
                for slug in OPTIMIZE_MODS.get(mr_loader, []):
                    download_mod(slug, version, mr_loader, mods_dir)
    return f"实例就绪:{instance_id}"


def backup_instance(instance: str, game_dir: str = None) -> str:
    """备份某实例(存档 zip + 模组列表 txt),返回备份位置"""
    return f"已备份到:{_backup_impl(instance, _gd(game_dir))}"


def send_game_command(instance: str, command: str, game_dir: str = None) -> str:
    """向运行中的游戏发送指令(如 /summon zombie)。

    优先走 bridge-mod 本地指令口(正式方案,100% 精确反馈);
    实例 .bridge/token.txt 存在时用 bridge,否则回退 RCON 通道。"""
    import os as _os
    from game_command import send_bridge_command, send_game_command as _rcon_impl
    gd = _gd(game_dir)
    token_path = _os.path.join(gd, "versions", instance, ".bridge", "token.txt")
    if _os.path.isfile(token_path):
        return send_bridge_command(instance, command, gd)
    return _rcon_impl(instance, command, gd)


def get_command_guide(mc_version: str) -> str:
    """按游戏版本返回指令指南(指令要点 + NBT/组件写法 + 核心模板)。
    生成指令前先调用,避免版本语法错误(1.13 指令改版 / 1.20.5 物品组件 / 老版本数字 id)。"""
    from command_templates import version_guide
    return version_guide(mc_version)


def get_key_bindings(instance: str, query: str, game_dir: str = None) -> str:
    """查询按键绑定(bridge-mod 导出):
    - 输入按键(如 空格/左Shift/W/32) → 返回该键绑了哪些操作(含 mod,一键多操作全列出)
    - 输入功能(如 前进/攻击/背包/JEI) → 返回对应按键
    数据由 bridge-mod 进游戏后自动导出,改键自动刷新。"""
    from key_bindings import query_keybindings
    return query_keybindings(_gd(game_dir), instance, query)


def get_recipe_path(item: str, count: int = 1, instance: str = None,
                    game_dir: str = None, brief: bool = True,
                    recipe_index: int = 0) -> str:
    """查询合成配方。默认返回精简版(只列直接配方一层,省 token);
    brief=False 时返回 EMI 风格完整配方:先列出该物品全部合成方式
    (工作台/熔炉/机器,recipe_index 选第 N 种,默认第 1 种),
    再套娃展开合成树 + 材料总账。item 支持中文名(如 终极感应供应器)。
    instance 缺省时自动用最新导出的数据。"""
    import recipe_graph
    gd = _gd(game_dir)
    rd = recipe_graph.load_bridge_data(gd, instance)
    if rd is None:
        # 收敛:明确告诉 AI 哪个实例有/缺数据,避免它反复试其它工具
        have = recipe_graph.instances_with_bridge(gd)
        if have:
            return (f"还没有{instance or '指定'}实例的配方数据,但以下实例已导出过配方:"
                    f"{', '.join(have)}。请用 instance 参数指定其中一个再查,"
                    f"或让用户启动目标实例进一次世界导出数据(bridge-mod 会自动导出)。")
        return ("还没有任何实例的配方数据:需要先装 bridge-mod 并启动游戏进一次世界,"
                "它会导出配方到实例的 .bridge/recipes.json。"
                "不要重复调用其它工具,直接告诉用户这一步即可。")
    head = f"【数据:{rd.source_instance},导出于 {rd.exported_at}】\n"
    if brief:
        return head + rd.quick_recipe(item)
    return head + rd.describe_recipe(item, count, recipe_index=recipe_index)


def compare_items(attribute: str, top_n: int = 10, game_dir: str = None) -> str:
    """比较物品参数,返回最强的 N 个。
    attribute 支持:武器伤害 / 护甲 / 护甲韧性 / 攻速 / 挖掘等级 等。"""
    import recipe_graph
    rd = recipe_graph.load_bridge_data(_gd(game_dir))
    if rd is None:
        return ("还没有物品数据:需要 bridge-mod 导出 .bridge/items.json"
                "(装 bridge-mod 进一次世界即可)")
    rows = rd.compare_items(attribute, top_n)
    if not rows:
        return f"没有找到属性 {attribute} 的数据"
    key = list(rows[0].keys())[1]
    return "\n".join(f"{r['item']}  →  {key} = {r[key]}" for r in rows)


def set_setting(key: str, value: str, game_dir: str = None) -> str:
    s = load_settings()
    if key not in s:
        return f"错误:未知设置 {key}(可用 get_settings 查看)"
    old = s[key]
    if isinstance(old, bool):
        s[key] = value.strip().lower() in ("1", "true", "yes", "开", "on")
    elif isinstance(old, int):
        try:
            s[key] = int(value)
        except ValueError:
            return f"错误:{key} 需要整数"
    else:
        s[key] = value
    if key == "game_dir":
        paths.set_game_dir(s[key])   # 改游戏目录:立即全局生效
    save_settings(s)
    return f"{key} = {s[key]}"


# 工具名 → 实现函数(供 assistant 工具调用注册)
TOOL_FUNCS = {
    "list_instances": list_instances,
    "list_mods": list_mods,
    "search_mods": search_mods,
    "read_instance_log": read_instance_log,
    "read_crash_report": read_crash_report,
    "get_settings": get_settings,
    "install_mod": install_mod,
    "install_instance": install_instance,
    "backup_instance": backup_instance,
    "set_setting": set_setting,
    "send_game_command": send_game_command,
    "get_command_guide": get_command_guide,
    "get_key_bindings": get_key_bindings,
    "get_recipe_path": get_recipe_path,
    "compare_items": compare_items,
}
