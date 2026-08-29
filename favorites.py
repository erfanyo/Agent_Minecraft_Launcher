# -*- coding: utf-8 -*-
"""
收藏数据存储(favorites):按资源名称(slug)记录收藏,可附带指定版本。

结构(存 AMCL/favorites.json):
    {
      "默认收藏夹": {"sodium": {"name": "Sodium", "version": "mc1.21.1-0.6.0"}, ...},
      "我的整合包": {...},
      ...
    }

纯数据层,不 import UI;UI(resource_center 收藏页 / 资源卡片)调用这些函数读写。
"""
import json
import os

from paths import data_dir

DEFAULT_FOLDER = "默认收藏夹"


def _path() -> str:
    return os.path.join(data_dir(), "favorites.json")


def load() -> dict:
    """读全部收藏(文件夹 → {slug: {name, version}});文件缺失/损坏返回 {}。"""
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save(data: dict) -> None:
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def folders(data: dict | None = None) -> list:
    data = data if data is not None else load()
    return list(data.keys())


def items(data: dict | None, folder: str) -> dict:
    """某收藏夹的全部条目 {slug: {name, version}}。"""
    data = data if data is not None else load()
    return dict((data.get(folder) or {}))


def get(data: dict, folder: str, slug: str) -> dict | None:
    return (data.get(folder) or {}).get(slug)


def is_favorited(data: dict, folder: str, slug: str) -> bool:
    return slug in (data.get(folder) or {})


def add(data: dict, folder: str, slug: str, name: str, version: str = "") -> None:
    """收藏一个资源到某收藏夹(按 slug;name 显示名,version 指定版本可空)。"""
    data.setdefault(folder, {})[slug] = {"name": name, "version": version or ""}


def remove(data: dict, folder: str, slug: str) -> None:
    (data.get(folder) or {}).pop(slug, None)


def copy(data: dict, from_folder: str, to_folder: str, slug: str) -> bool:
    """把某收藏从 from_folder 复制到 to_folder(跨文件夹复制用)。"""
    src = (data.get(from_folder) or {}).get(slug)
    if src is None:
        return False
    data.setdefault(to_folder, {})[slug] = dict(src)
    return True
