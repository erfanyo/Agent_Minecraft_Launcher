# -*- coding: utf-8 -*-
"""
Agent 工具层:CLI 命令与 AI 工具调用共用的函数实现。

设计:每个函数"文本进 → 文本出",既被 `cli.py` 的命令调用,
也被 `assistant.py` 的工具调用(tool calling)当作工具执行体。
权限不在这一层——由调用方(assistant 的执行器)按只读/工作区可写拦截。
"""
import os

from backup import GAME_DIR, backup_instance as _backup_impl
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
def list_instances(game_dir: str = GAME_DIR) -> str:
    insts = scan_instances(game_dir)
    if not insts:
        return "(还没有实例)"
    return "\n".join(f"{i['id']}  ({i['loader'] or '原版'} ← {i['base']})" for i in insts)


def list_mods(instance: str, game_dir: str = GAME_DIR) -> str:
    mods_dir = os.path.join(game_dir, "versions", instance, "mods")
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


def read_instance_log(instance: str, tail: int = 80, game_dir: str = GAME_DIR) -> str:
    log = os.path.join(game_dir, "versions", instance, "logs", "latest.log")
    if not os.path.isfile(log):
        return f"({instance} 还没有日志文件)"
    try:
        lines = open(log, encoding="utf-8", errors="replace").read().splitlines()
    except Exception as e:
        return f"(读取日志失败:{e})"
    return "\n".join(lines[-tail:])


def read_crash_report(instance: str, game_dir: str = GAME_DIR) -> str:
    cr_dir = os.path.join(game_dir, "versions", instance, "crash-reports")
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
                game_dir: str = GAME_DIR) -> str:
    """给某实例安装 Mod(按实例的加载器 + 基础版本过滤)"""
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


def install_instance(version: str, loader: str = "", loader_version: str = "",
                     shader: bool = False, optimize: bool = False,
                     game_dir: str = GAME_DIR, status=print) -> str:
    """创建实例:原版本体 + (可选)加载器 + (可选)光影/优化 Mod"""
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


def backup_instance(instance: str, game_dir: str = GAME_DIR) -> str:
    """备份某实例(存档 zip + 模组列表 txt),返回备份位置"""
    return f"已备份到:{_backup_impl(instance, game_dir)}"



def set_setting(key: str, value: str, game_dir: str = GAME_DIR) -> str:
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
}
