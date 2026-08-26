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
from modrinth import download_mod, get_project, search_mods_cn
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


def search_modpacks(query: str, game_version: str = "", loader: str = "") -> str:
    """搜整合包(Modrinth 项目类型 modpack,即 .mrpack),支持中文名。
    用户想"装一个整合包/整合包推荐"时用;结果里的 slug 可交给 install_modpack 直接下载导入。"""
    hits = search_mods_cn(query, game_version or None, loader or None,
                          project_type="modpack")
    if not hits:
        return "(没有找到整合包;可换关键词,或该整合包不在 Modrinth,需要用网盘/手动下载)"
    return "\n".join(f"{h['title']}  slug={h['slug']}  ⬇{h['downloads']:,}"
                     for h in hits[:12])


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
                game_dir: str = None, progress_callback=None) -> str:
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
    filename = download_mod(slug, gv, loader, mods_dir, version_number=version or None,
                            progress_callback=progress_callback)
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


def install_mods(slugs, instance: str, game_dir: str = None,
                 progress_callback=None) -> str:
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
        filename = download_mod(slug, gv, loader, mods_dir, progress_callback=progress_callback)
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
                     fabric_api_version: str | None = None,
                     game_dir: str = None, status=print,
                     progress_callback=None) -> str:
    """创建实例:原版本体 + (可选)加载器 + (可选)Fabric API/光影/优化 Mod。
    加载器版本留空 = 自动用最新。成功返回实例 id。"""
    version = (version or "").strip()
    if not version:
        return "错误:需要指定游戏版本(如 1.21.1)"
    loader = (loader or "").strip().lower()
    if loader and loader not in ("fabric", "forge", "neoforge"):
        return f"错误:不支持的加载器 {loader}(可选 fabric/forge/neoforge,留空=原版)"
    game_dir = _gd(game_dir)
    try:
        ensure_base(version, game_dir, status_callback=status, progress_callback=progress_callback)
    except Exception as e:
        return f"错误:原版 {version} 下载失败:{e}"
    instance_id = version
    if loader:
        try:
            instance_id = install_loader(loader, version, game_dir,
                                         loader_version=loader_version or None,
                                         status_callback=status)
        except Exception as e:
            return f"错误:{loader} 加载器安装失败:{e}"
        mods_dir = os.path.join(game_dir, "versions", instance_id, "mods")
        mr_loader = {"fabric": "fabric", "forge": "forge", "neoforge": "neoforge"}[loader]
        # Fabric API(绝大多数 Fabric 模组的前置;指定版本时自动装)
        if loader == "fabric" and fabric_api_version:
            try:
                filename = download_mod("fabric-api", version, "fabric", mods_dir,
                                        version_number=fabric_api_version or None)
                status(f"Fabric API:{filename or '无可用版本'}")
            except Exception as e:
                status(f"Fabric API 下载失败:{e}")
        if shader or optimize:
            if shader and mr_loader:
                slug = SHADER_MODS.get(mr_loader)
                if slug:
                    download_mod(slug, version, mr_loader, mods_dir)
            if optimize and mr_loader:
                for slug in OPTIMIZE_MODS.get(mr_loader, []):
                    download_mod(slug, version, mr_loader, mods_dir)
    return f"实例就绪:{instance_id}"


def install_modpack(slug_or_url: str, instance_name: str = "",
                    game_dir: str = None, progress_callback=None) -> str:
    """下载并导入整合法包(Modrinth 项目类型 modpack,即 .mrpack)。

    用法/时机:用户想"装一个整合包"且给的是 Modrinth 链接/slug 时直接下载导入成新实例
    (自动装基础版+加载器+整合包全部 mod)。若整合包不在 Modrinth 上,返回明确提示,
    让用户用网盘/官方链接手动下载,再引导(可配合安装引导)。

    - slug_or_url: Modrinth 整合包 slug 或完整链接(如 https://modrinth.com/modpack/smithing)。
    - instance_name: 可选,自定义实例名(不传用整合包名)。
    """
    import os as _os
    import shutil as _sh
    from modpack import import_modpack
    from modrinth import (download_modpack, get_modpack_file, get_project,
                          resolve_modpack_ref)
    gd = _gd(game_dir)
    ref = resolve_modpack_ref(slug_or_url)
    if not ref:
        return ("错误:无法识别整合包引用(需要 Modrinth 链接或 slug,"
                "如 https://modrinth.com/modpack/smithing)。可先用 search_modpacks 搜。")
    try:
        proj = get_project(ref)
    except Exception as e:
        return (f"错误:Modrinth 上找不到整合包 {ref}({type(e).__name__}: {e})。"
                "它可能不在 Modrinth —— 把下载链接/网盘链接给用户,让 TA 手动下载后"
                "用启动器的「导入整合包」或告诉我路径由我来配置。")
    if proj.get("project_type") != "modpack":
        return (f"错误:{proj.get('title')} 不是整合包(项目类型是 {proj.get('project_type')})。"
                "整合包在 Modrinth 项目类型为 modpack;若想装单个 Mod 请用 install_mod。")
    # 确定要用的 .mrpack 文件(不指定版本 → 最新)
    try:
        info = get_modpack_file(ref)
    except Exception as e:
        return f"错误:获取整合包 {ref} 的下载信息失败:{type(e).__name__}: {e}"
    if not info:
        return (f"错误:{proj.get('title')} 没有可下载的 .mrpack 文件。"
                "可能需要向作者申请权限或手动下载,请把官方下载链接给用户。")
    # 下载 .mrpack 到 downloads 目录的细分子目录(临时),导入成功后清理
    work = _os.path.join(gd, "downloads", "modpack_tmp")
    try:
        local = download_modpack(ref, work, progress_callback=progress_callback)
    except Exception as e:
        return f"错误:下载整合包 {ref} 失败:{type(e).__name__}: {e}"
    if not local:
        return f"错误:{proj.get('title')} 下载失败(无可用文件)。"
    try:
        # instance_name 为空 → import_modpack 默认用包名/文件名
        inst = import_modpack(local, gd, instance_id=instance_name or None,
                              status_callback=print,
                              progress_callback=progress_callback)
    except Exception as e:
        # 导入失败可能是同名实例;兜底给友好提示
        return (f"错误:导入整合包失败:{type(e).__name__}: {e}。"
                "已存在同名实例时请自定义 instance_name。")
    finally:
        try:
            _sh.rmtree(work, ignore_errors=True)
        except Exception:
            pass
    return f"✅ 整合包导入完成:{inst}({info.get('version_number', '最新')}, {proj.get('title')})"


def backup_instance(instance: str, game_dir: str = None) -> str:
    """备份某实例(存档 zip + 模组列表 txt),返回备份位置"""
    return f"已备份到:{_backup_impl(instance, _gd(game_dir))}"


def launch_game(instance: str, game_dir: str = None) -> str:
    """启动某实例的游戏(写操作,需要工作区写权限)。
    注意:这样启动的进程启动器不跟踪日志/退出,关闭游戏窗口即退出。"""
    import os as _os
    import subprocess
    from java_manager import ensure_java
    from launcher import build_launch_command, resolve_inherited_json
    gd = _gd(game_dir)
    inst = next((i for i in scan_instances(gd) if i["id"] == instance), None)
    if inst is None:
        return f"错误:没有实例 {instance}(可用 list_instances 查看)"
    try:
        d = resolve_inherited_json(inst["id"], gd)
    except Exception as e:
        return f"错误:读取 {inst['id']} 版本数据失败:{e}"
    required_java = (d.get("javaVersion") or {}).get("majorVersion", 8)
    try:
        java_exe = ensure_java(_os.path.join(gd, "runtime"), required_java)
    except Exception as e:
        return f"错误:准备 Java 失败:{e}"
    game_dir_run = _os.path.join(gd, "versions", inst["id"])   # PCL2 风格实例目录
    try:
        from settings import load_settings as _ls
        _memory = _ls().get("memory_gb", 4)
        cmd = build_launch_command(
            d, game_dir_run, java_exe,
            username="Player", memory_gb=_memory,
            assets_dir=_os.path.join(gd, "assets"),
            install_dir=gd)
    except Exception as e:
        return f"错误:构建启动命令失败:{e}"
    # javaw:无控制台黑框
    javaw = _os.path.join(_os.path.dirname(java_exe), "javaw.exe")
    if _os.path.isfile(javaw):
        cmd = [javaw] + cmd[1:]
    creationflags = subprocess.CREATE_NO_WINDOW if _os.name == "nt" else 0
    try:
        p = subprocess.Popen(cmd, cwd=game_dir_run, creationflags=creationflags)
    except Exception as e:
        return f"错误:启动失败:{e}"
    return (f"✅ 已启动 {inst['id']}(PID {p.pid})。"
            f"注意:这样启动的进程启动器不跟踪日志,关闭游戏窗口即退出。")


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
    instance 缺省时自动探测。数据来源:jar 旁路(直接读 mod jar 配方,无需进游戏)
    + bridge 导出(实际生效,覆盖 jar)。"""
    import recipe_graph
    gd = _gd(game_dir)
    rd = recipe_graph.load_recipe_data(gd, instance)
    if rd is None:
        # 收敛:明确告诉 AI 哪个实例有/缺数据,避免它反复试其它工具
        have = recipe_graph.instances_with_recipe_data(gd)
        if have:
            return (f"还没有{instance or '指定'}实例的配方数据,但以下实例有:"
                    f"{', '.join(have)}。请用 instance 参数指定其中一个再查;"
                    f"装了 mod 的实例通常无需进游戏(旁路直接读 jar 配方)。")
        return ("还没有任何实例的配方数据:装 bridge-mod 进一次世界会自动导出配方"
                "到 .bridge/recipes.json;已装 mod 的实例也可以直接读 jar 配方。"
                "不要重复调用其它工具,直接告诉用户这一步即可。")
    src = {"bridge+jar": "jar 旁路 + bridge 导出", "jar": "jar 旁路(无需进游戏)",
           "bridge": f"bridge 导出({rd.exported_at})"}.get(
        getattr(rd, "source_kind", "bridge"), "bridge")
    head = f"【数据:{rd.source_instance} · {src}】\n"
    if brief:
        return head + rd.quick_recipe(item)
    return head + rd.describe_recipe(item, count, recipe_index=recipe_index)


def compare_items(attribute: str, top_n: int = 10, game_dir: str = None) -> str:
    """比较物品参数,返回最强的 N 个。
    attribute 支持:武器伤害 / 护甲 / 护甲韧性 / 攻速 / 挖掘等级 等。"""
    import recipe_graph
    rd = recipe_graph.load_bridge_data(_gd(game_dir))
    if rd is None:
        return ("该实例未导出物品属性数据(.bridge/items.json)——较老版本的 bridge-mod 不导出此项。"
                "我若凭通用知识/模型判断,结果【可能不准确】。请告诉用户:该版本的物品属性比较仅供参考。")
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


def resolve_mc_name(query: str, instance: str = None, game_dir: str = None) -> str:
    """本地把物品/生物/效果/附魔的中文/口语/英文叫法解析成【规范英文名 + id】。
    用于查 wiki/资料库前先归一化(如 苦力怕 → Creeper/minecraft:creeper),检索命中更准。
    读实例 mods jar + 版本 jar 的 lang 文件(zh_cn/en_us),外置原版常见词表兜底。"""
    from mc_names import resolve_mc_name as _r
    return _r(query, game_dir=_gd(game_dir), instance=instance)


def translate_mod_desc(slug: str, game_version: str = "", loader: str = "") -> str:
    """翻译 Mod 描述(英→中,本地 AI;缓存优先,失败显示原文)。
    用于:用户问"这个 mod 是干什么的/什么意思"时,取详情并翻成中文。
    slug 支持中文名(自动解析为 Modrinth slug)。"""
    slug = _resolve_slug(slug)
    try:
        p = get_project(slug)
    except Exception as e:
        return f"错误:获取 {slug} 详情失败:{type(e).__name__}: {e}"
    desc = (p.get("description") or "").strip()
    title = p.get("title") or slug
    if not desc:
        return f"{title}({slug}):该 Mod 没有描述"
    from mod_translate import translate_text_safe
    r = translate_text_safe(desc, slug=slug, field="description")
    head = f"{title}({slug})\n"
    note = "\n(机翻仅供参考)" if (r["translated"] and r["machine"]) else ""
    return head + r["text"] + note


# 工具名 → 实现函数(供 assistant 工具调用注册)
TOOL_FUNCS = {
    "list_instances": list_instances,
    "list_mods": list_mods,
    "search_mods": search_mods,
    "search_modpacks": search_modpacks,
    "read_instance_log": read_instance_log,
    "read_crash_report": read_crash_report,
    "get_settings": get_settings,
    "install_mod": install_mod,
    "install_mods": install_mods,
    "install_instance": install_instance,
    "install_modpack": install_modpack,
    "backup_instance": backup_instance,
    "set_setting": set_setting,
    "send_game_command": send_game_command,
    "get_command_guide": get_command_guide,
    "get_key_bindings": get_key_bindings,
    "get_recipe_path": get_recipe_path,
    "compare_items": compare_items,
    "translate_mod_desc": translate_mod_desc,
    "resolve_mc_name": resolve_mc_name,
}
