# -*- coding: utf-8 -*-
"""路径常量:整个项目共用的数据根目录与游戏目录位置。

数据根目录(BASE_DIR)采用 PCL 式"就地创建"便携设计,优先级:
1. 环境变量 AML_DATA_DIR 显式指定(最优先,适合多配置/绿色便携)
2. 打包后(exe):exe 所在目录 —— 数据跟着 exe 走,整个文件夹可随意搬动
3. 源码运行:项目目录
4. 就地目录不可写(如 Program Files)→ 自动退回 %APPDATA%\\AgentMinecraftLauncher

这样 PyInstaller 打包后数据不会写进临时解压目录(%TEMP%\\_MEIxxx,重启即丢),
config.json(游戏目录/AI 设置)、.minecraft、runtime 全部持久化在 exe 旁边。

支持在设置/首次引导里改游戏目录:
- set_game_dir() 更新模块级 GAME_DIR / RUNTIME_DIR,改完立即全局生效
- 模块导入时会先读 config.json 里保存的 game_dir(有则优先,没有就用默认 .minecraft)
"""
import json
import os
import sys


def _pick_base_dir() -> str:
    """选择数据根目录(见模块注释的优先级规则)"""
    env = os.environ.get("AML_DATA_DIR", "").strip()
    if env:
        return os.path.abspath(env)
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后:sys.executable 才是 exe 真实路径,__file__ 是临时解压目录
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    # 就地目录可写 → 便携模式;不可写(只读目录)→ 系统用户目录
    try:
        probe = os.path.join(base, ".aml_write_probe")
        with open(probe, "w") as f:
            f.write("1")
        os.remove(probe)
        return base
    except OSError:
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(appdata, "AgentMinecraftLauncher")


BASE_DIR = _pick_base_dir()
# 配置文件收进 AMCL 子目录:exe 旁边只留 .minecraft/runtime 等"看着就像数据"的文件夹,
# 避免用户把 config.json 当垃圾误删;AMCL 目录自动创建
CONFIG_DIR = os.path.join(BASE_DIR, "AMCL")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
_LEGACY_CONFIG = os.path.join(BASE_DIR, "config.json")   # 旧版直接放根目录的配置


def _ensure_config_dir() -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
    except OSError:
        pass


_ensure_config_dir()
# 首次迁移:旧位置(项目/exe 旁的 config.json)复制进 AMCL,用户已有设置不丢
if not os.path.exists(CONFIG_PATH) and os.path.exists(_LEGACY_CONFIG):
    try:
        import shutil
        shutil.copy2(_LEGACY_CONFIG, CONFIG_PATH)
    except OSError:
        pass

DEFAULT_GAME_DIR = os.path.join(BASE_DIR, ".minecraft")


def _saved_game_dir() -> str:
    """config.json 里用户保存的游戏目录(空 = 未配置)"""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        g = data.get("game_dir")
        if isinstance(g, str) and g.strip():
            return g.strip()
    except Exception:
        pass
    return ""


GAME_DIR = _saved_game_dir() or DEFAULT_GAME_DIR
RUNTIME_DIR = os.path.join(GAME_DIR, "runtime")


def set_game_dir(path: str) -> None:
    """更新全局游戏目录(设置/引导界面保存后调用)。空值回到默认位置。"""
    global GAME_DIR, RUNTIME_DIR
    p = (path or "").strip()
    GAME_DIR = p if p else DEFAULT_GAME_DIR
    RUNTIME_DIR = os.path.join(GAME_DIR, "runtime")


def looks_like_game_dir(path: str) -> bool:
    """粗略判断一个目录是不是 .minecraft(有 versions / assets / libraries 之一)"""
    if not path:
        return False
    for sub in ("versions", "assets", "libraries"):
        if os.path.isdir(os.path.join(path, sub)):
            return True
    return False


def version_isolation_enabled() -> bool:
    """读取当前的版本隔离开关。

    延迟导入 settings，避免 settings 初始化时反向导入 paths。所有需要定位
    实例运行文件的模块应使用下面两个函数，不能自行拼接 versions/<id>。
    """
    try:
        from settings import load_settings
        return bool(load_settings().get("version_isolation", True))
    except Exception:
        return True


def instance_dir(instance_id: str, game_dir: str | None = None) -> str:
    """返回实例实际运行目录，兼容开启/关闭版本隔离两种布局。"""
    gd = game_dir or GAME_DIR
    return os.path.join(gd, "versions", instance_id) if version_isolation_enabled() else gd


def bridge_dir(instance_id: str, game_dir: str | None = None) -> str:
    """返回 bridge-mod 与启动器共享的 .bridge 目录（不创建目录）。"""
    return os.path.join(instance_dir(instance_id, game_dir), ".bridge")


# ================= 统一路径访问层(收口散落在各模块的 AMCL 子路径) =================
# 之前各模块各自 os.path.join(CONFIG_DIR, "cache", "xxx"),分散难维护。
# 这里提供稳定的 getter,集中管理 + 自动建目录;不改动任何现有目录结构(仍便携式)。
#
# 缓存子目录(cache/ 下):
#   icons/desc/avatars/item_names/translations/recipes-jar/glossary_hit + ai_quota.json
# 数据子目录(AMCL/ 下):models/runtime/online/chat_archive/languages

_AMCL_SUBDIRS = {"models", "runtime", "online", "chat_archive", "languages"}
_CACHE_SUBDIRS = {"icons", "desc", "avatars", "item_names", "translations",
                  "recipes-jar", "glossary_hit"}


def _ensure(path: str) -> str:
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def data_dir(sub: str = "") -> str:
    """AMCL 数据子目录(如 models/runtime/online/chat_archive/languages)。自动创建。"""
    if sub:
        return _ensure(os.path.join(CONFIG_DIR, sub))
    return _ensure(CONFIG_DIR)


def cache_dir(sub: str = "") -> str:
    """缓存子目录(ex: cache/icons / cache/translations)。自动创建。"""
    base = os.path.join(CONFIG_DIR, "cache")
    if sub:
        return _ensure(os.path.join(base, sub))
    return _ensure(base)


def model_dir() -> str:
    """本地模型文件目录(AMCL/models)。"""
    return data_dir("models")


def runtime_llama_dir() -> str:
    """llama.cpp runtime(AMCL/runtime/llama-cpp)。"""
    return _ensure(os.path.join(CONFIG_DIR, "runtime", "llama-cpp"))


# 兼容旧引用:image_cache 用 CACHE_ROOT;mc_names 等用 cache/xxx
CACHE_ROOT = cache_dir()
