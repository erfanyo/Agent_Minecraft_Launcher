# -*- coding: utf-8 -*-
"""实例扫描:读取 versions 目录,识别每个实例的加载器与基础版本。
独立成轻量模块,让 CLI / AI 工具 / GUI 都能用,不依赖 Qt。"""
import json
import os

from paths import GAME_DIR


def scan_instances(game_dir: str = GAME_DIR) -> list:
    """扫描已安装的实例:versions/<id>/<id>.json。
    返回 [{id, base, loader, label}],loader 为 fabric/forge/neoforge/None(原版)"""
    instances = []
    versions_dir = os.path.join(game_dir, "versions")
    if not os.path.isdir(versions_dir):
        return instances
    for name in sorted(os.listdir(versions_dir)):
        vjson = os.path.join(versions_dir, name, name + ".json")
        if not os.path.exists(vjson):
            continue
        try:
            with open(vjson, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        base = data.get("inheritsFrom")
        loader = None
        if base:
            # 加载器可能体现在目录名里(如 fabric-loader-...),也可能只在 JSON 的 id 里(整合包)。
            # 注意 neoforge 包含子串 forge,必须先匹配长的
            low = (name + " " + str(data.get("id", ""))).lower()
            for l in ("fabric", "neoforge", "forge"):
                if l in low:
                    loader = l
                    break
            if loader is None:
                loader = "modded"
        else:
            base = name
        label = f"{name}  ({loader or '原版'} ← {base})"
        instances.append({"id": name, "base": base, "loader": loader, "label": label})
    return instances
