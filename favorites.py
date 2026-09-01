# -*- coding: utf-8 -*-
"""
收藏数据存储(favorites):按资源名称(slug)记录泛用收藏，并可附带多个指定版本。

结构(存 AMCL/favorites.json):
    {
      "默认收藏夹": {"sodium": {"name": "Sodium", "versions": ["mc1.21.1-0.6.0"]}, ...},
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
    """读全部收藏并确保默认收藏夹存在；兼容旧版单个 version 字段。"""
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    if _normalize(data):
        save(data)
    return data


def save(data: dict) -> None:
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def folders(data: dict | None = None) -> list:
    data = data if data is not None else load()
    _normalize(data)
    return list(data.keys())


def items(data: dict | None, folder: str) -> dict:
    """某收藏夹的全部条目 {slug: {name, versions:[...]}}。"""
    data = data if data is not None else load()
    _normalize(data)
    return dict((data.get(folder) or {}))


def get(data: dict, folder: str, slug: str) -> dict | None:
    return (data.get(folder) or {}).get(slug)


def is_favorited(data: dict, folder: str, slug: str) -> bool:
    return slug in (data.get(folder) or {})


def add(data: dict, folder: str, slug: str, name: str) -> None:
    """添加泛用收藏；已有的指定版本会被保留。"""
    _normalize(data)
    entry = data.setdefault(folder, {}).setdefault(slug, {"name": name, "versions": []})
    entry["name"] = name or entry.get("name") or slug
    entry.setdefault("versions", [])


def add_version(data: dict, folder: str, slug: str, name: str, version: str) -> bool:
    """把一个指定版本收进已有的泛用收藏；返回是否新增。"""
    add(data, folder, slug, name)
    version = (version or "").strip()
    if not version:
        return False
    versions = data[folder][slug]["versions"]
    if version in versions:
        return False
    versions.append(version)
    return True


def versions(data: dict, folder: str, slug: str) -> list[str]:
    entry = get(data, folder, slug) or {}
    return list(entry.get("versions") or [])


def remove(data: dict, folder: str, slug: str) -> None:
    (data.get(folder) or {}).pop(slug, None)


def copy(data: dict, from_folder: str, to_folder: str, slug: str) -> bool:
    """把某收藏从 from_folder 复制到 to_folder(跨文件夹复制用)。"""
    src = (data.get(from_folder) or {}).get(slug)
    if src is None:
        return False
    data.setdefault(to_folder, {})[slug] = {
        "name": src.get("name", slug), "versions": list(src.get("versions") or [])}
    return True


def _normalize(data: dict) -> bool:
    """就地迁移旧结构，并保证默认收藏夹永远存在。"""
    changed = False
    if DEFAULT_FOLDER not in data or not isinstance(data.get(DEFAULT_FOLDER), dict):
        data[DEFAULT_FOLDER] = {}
        changed = True
    for folder, entries in list(data.items()):
        if not isinstance(entries, dict):
            data[folder] = {}
            changed = True
            continue
        for slug, raw in list(entries.items()):
            if not isinstance(raw, dict):
                entries[slug] = {"name": slug, "versions": []}
                changed = True
                continue
            had_legacy_version = "version" in raw
            legacy_version = raw.pop("version", "")
            changed = changed or had_legacy_version
            versions_ = raw.get("versions")
            if not isinstance(versions_, list):
                versions_ = []
                raw["versions"] = versions_
                changed = True
            if legacy_version and legacy_version not in versions_:
                versions_.append(legacy_version)
                changed = True
            if not raw.get("name"):
                raw["name"] = slug
                changed = True
    return changed
