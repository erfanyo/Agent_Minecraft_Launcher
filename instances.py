# -*- coding: utf-8 -*-
"""实例扫描:读取 versions 目录,识别每个实例的加载器与基础版本。
独立成轻量模块,让 CLI / AI 工具 / GUI 都能用,不依赖 Qt。

识别依据(由强到弱):
1. 目录名 / JSON id / inheritsFrom 里的关键词(fabric/neoforge/forge)
2. libraries 里的 artifact 名(整合包常不写 inheritsFrom,但依赖里带加载器:
   net.neoforged.fancymodloader → neoforge;net.minecraftforge:eventbus → forge;
   net.fabricmc:fabric-loader → fabric)
3. mainClass(如 net.fabricmc.loader.impl.launch.knot.KnotClient / cpw.mods.bootstraplauncher)
4. 都没有 → 检查 mods 目录:有 jar 算"modded",否则原版
"""
import json
import os

import paths


def _detect_loader(name: str, data: dict) -> str | None:
    """综合判断加载器,返回 fabric/neoforge/forge/None(认不出)"""
    # 1) 名称关键词(注意 neoforge 含子串 forge,必须先匹配长的)
    low = (str(name) + " " + str(data.get("id", ""))
           + " " + str(data.get("inheritsFrom", ""))).lower()
    for l in ("fabric", "neoforge", "forge"):
        if l in low:
            return l
    # 2) libraries 里的 artifact 名(整合包常见:不写 inheritsFrom,但带加载器依赖)
    for lib in data.get("libraries", []) or []:
        n = str(lib.get("name", "")).lower()
        if "fabricmc" in n or "fabric-loader" in n:
            return "fabric"
        if "neoforged" in n or "neoforge" in n:
            return "neoforge"
        if "minecraftforge" in n:
            return "forge"
    # 3) mainClass
    mc = str(data.get("mainClass", "")).lower()
    if "fabricmc" in mc:
        return "fabric"
    if "neoforge" in mc:
        return "neoforge"
    if "cpw.mods" in mc or "fml" in mc or "forge" in mc:
        return "forge"
    return None


def scan_instances(game_dir: str = None) -> list:
    """扫描已安装的实例:versions/<id>/<id>.json。
    返回 [{id, base, loader, label}],loader 为 fabric/forge/neoforge/'modded'/None(原版)
    game_dir 缺省时用当前生效的游戏目录(paths.GAME_DIR,设置里可改)。"""
    if game_dir is None:
        game_dir = paths.GAME_DIR
    instances = []
    versions_dir = os.path.join(game_dir, "versions")
    if not os.path.isdir(versions_dir):
        return instances
    for name in sorted(os.listdir(versions_dir)):
        if name.startswith("_"):
            continue   # 版本仓库(_versions/ 等),不是实例
        vjson = os.path.join(versions_dir, name, name + ".json")
        if not os.path.exists(vjson):
            continue
        try:
            with open(vjson, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        base = data.get("inheritsFrom")
        has_base = bool(base)
        loader = _detect_loader(name, data)
        if not base:
            base = name
        if loader is None:
            if has_base:
                # 有继承链但认不出具体加载器:至少不是原版(原版 json 没有 inheritsFrom)
                loader = "modded"
            else:
                # 认不出加载器:有 mods 目录且含 jar → 至少算 modded,不算原版
                mods_dir = os.path.join(versions_dir, name, "mods")
                if os.path.isdir(mods_dir):
                    try:
                        if any(f.endswith(".jar") for f in os.listdir(mods_dir)):
                            loader = "modded"
                    except OSError:
                        pass
        label = f"{name}  ({loader or '原版'} ← {base})"
        instances.append({"id": name, "base": base, "loader": loader, "label": label})
    return instances
