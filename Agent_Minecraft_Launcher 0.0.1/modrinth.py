# -*- coding: utf-8 -*-
"""
Modrinth API 封装:搜索 Mod、按"游戏版本 + 加载器"找对应文件、下载到 mods 目录。

Modrinth(https://modrinth.com)是开源的 Mod 平台,API 免费公开:
- 搜索:GET /v2/search?query=...&facets=[["versions:26.2"],["categories:fabric"]]
- 版本:GET /v2/project/<slug>/version?game_versions=["26.2"]&loaders=["fabric"]
"""
import json
import os

import requests

from downloader import download_with_mirror
from mod_cn import CN_NAMES, find_slugs_by_cn, has_cjk

BASE = "https://api.modrinth.com/v2"


def get_project(slug: str) -> dict:
    """按 slug 取 Mod 项目详情(含 game_versions / loaders,可用来过滤版本)"""
    resp = requests.get(BASE + f"/project/{slug}", timeout=20)
    resp.raise_for_status()
    d = resp.json()
    return {
        "slug": d.get("slug", slug),
        "title": d.get("title", slug),
        "description": d.get("description", ""),
        "downloads": d.get("downloads", 0),
        "categories": d.get("categories", []),
        "game_versions": d.get("game_versions", []),
        "loaders": d.get("loaders", []),
        "icon_url": d.get("icon_url", ""),
    }


def _facets(game_version: str, loader: str | None) -> str:
    """构造搜索过滤条件:版本 + (可选)加载器"""
    parts = [[f"versions:{game_version}"]]
    if loader:
        parts.append([f"categories:{loader}"])
    return json.dumps(parts)


def search_mods_cn(query: str, game_version: str, loader: str | None = None,
                   limit: int = 20) -> list:
    """中文增强搜索。

    - 关键词含中文 → 先查本地中文名库 → 命中 slug 就去 Modrinth 取详情(按版本/加载器过滤)
    - 查不到或关键词是英文 → 走 Modrinth 原生搜索
    - 返回的结果统一标注中文名(有库就用,没有就用原名)
    """
    if has_cjk(query):
        cn_hits = []
        for slug in find_slugs_by_cn(query):
            try:
                p = get_project(slug)
            except Exception:
                continue
            # 中文命中只按加载器过滤:版本是否支持留到下载时明确提示
            # (否则像 Jade 这种"支持 Forge 但某版本没发 Forge 版型"的 Mod 会搜不到)
            if loader and loader not in p["loaders"]:
                continue
            p["title"] = CN_NAMES.get(slug, p["title"])
            cn_hits.append(p)
            if len(cn_hits) >= limit:
                break
        if cn_hits:
            return cn_hits

        # 按加载器过滤后一个都没有(如"钠"在 Forge 下):放宽加载器过滤,
        # 让用户能看到该中文名对应的 Mod,自行判断(下载时会有明确提示)
        loose = []
        for slug in find_slugs_by_cn(query):
            try:
                p = get_project(slug)
            except Exception:
                continue
            p["title"] = CN_NAMES.get(slug, p["title"])
            loose.append(p)
            if len(loose) >= limit:
                break
        if loose:
            return loose

        # 中文没命中本地库:继续走原生搜索(用户可能搜的是英文或平台别名)

    hits = search_mods(query, game_version, loader, limit)
    for h in hits:
        cn = CN_NAMES.get(h["slug"])
        if cn:
            h["title"] = f"{cn}"
    return hits


def search_mods(query: str, game_version: str, loader: str | None = None,
                limit: int = 20) -> list:
    """搜索 Mod,返回 [{slug, title, description, downloads, categories}, ...]"""
    resp = requests.get(BASE + "/search", params={
        "query": query,
        "facets": _facets(game_version, loader),
        "limit": limit,
    }, timeout=20)
    resp.raise_for_status()
    hits = resp.json().get("hits", [])
    return [{
        "slug": h["slug"],
        "title": h.get("title", h["slug"]),
        "description": h.get("description", ""),
        "downloads": h.get("downloads", 0),
        "categories": h.get("categories", []),
        "icon_url": h.get("icon_url", ""),   # 封面小图,用来在列表/图标视图展示
    } for h in hits]


def list_mod_versions(slug: str, game_version: str, loader: str) -> list:
    """某 Mod 在指定"游戏版本+加载器"下可用的版本号列表(新的在前)"""
    resp = requests.get(BASE + f"/project/{slug}/version", params={
        "game_versions": json.dumps([game_version]),
        "loaders": json.dumps([loader]),
    }, timeout=20)
    resp.raise_for_status()
    return [v.get("version_number", "?") for v in resp.json()]


def get_mod_version(slug: str, game_version: str, loader: str,
                    version_number: str | None = None) -> dict | None:
    """找某个 Mod 在"指定游戏版本 + 加载器"下的文件信息。
    默认最新;version_number 指定时只在该版本里找。
    返回 {version_number, filename, url, size, dependencies};没有匹配返回 None。"""
    resp = requests.get(BASE + f"/project/{slug}/version", params={
        "game_versions": json.dumps([game_version]),
        "loaders": json.dumps([loader]),
    }, timeout=20)
    resp.raise_for_status()
    versions = resp.json()
    if version_number:
        versions = [v for v in versions if v.get("version_number") == version_number]
    if not versions:
        return None
    v = versions[0]
    primary = None
    for f in v.get("files", []):
        if f.get("primary"):
            primary = f
            break
    f = primary or (v.get("files") or [{}])[0]
    return {
        "version_number": v.get("version_number", "?"),
        "filename": f.get("filename", "mod.jar"),
        "url": f.get("url", ""),
        "size": f.get("size", 0),
        "dependencies": v.get("dependencies", []),
    }


def download_mod(slug: str, game_version: str, loader: str, mods_dir: str,
                 version_number: str | None = None,
                 progress_callback=None) -> str | None:
    """下载某 Mod 到 mods 目录,返回保存的文件名;失败返回 None。
    version_number 不传 → 最新;传了 → 指定版本(高级选项)。"""
    info = get_mod_version(slug, game_version, loader, version_number)
    if info is None or not info["url"]:
        return None
    os.makedirs(mods_dir, exist_ok=True)
    dest = os.path.join(mods_dir, info["filename"])
    download_with_mirror(info["url"], dest, progress_callback=progress_callback)
    return info["filename"]
