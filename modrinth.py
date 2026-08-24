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


def _facets(game_version: str, loader: str | None,
            project_type: str | None = None, tags: str = "") -> str:
    """构造搜索过滤条件:版本 + (可选)加载器 + (可选)项目类型 + (可选)分类标签。
    版本为空 = 不过滤版本(放宽搜索用);tags 逗号分隔,按 Modrinth 分类过滤。"""
    parts = []
    if game_version:
        parts.append([f"versions:{game_version}"])
    if loader:
        parts.append([f"categories:{loader}"])
    if project_type:
        parts.append([f"project_type:{project_type}"])
    if tags:
        tag_list = [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()]
        if tag_list:
            parts.append([f"categories:{t}" for t in tag_list])
    return json.dumps(parts)


def search_mods_cn(query: str, game_version: str, loader: str | None = None,
                   limit: int = 20, project_type: str | None = None,
                   order_by: str = "downloads", tags: str = "") -> list:
    """中文增强搜索。

    - 关键词含中文 → 先查本地中文名库 → 命中 slug 就去 Modrinth 取详情(按版本/加载器过滤)
    - 查不到或关键词是英文 → 走 Modrinth 原生搜索
    - 返回的结果统一标注中文名(有库就用,没有就用原名)
    - project_type: 限定项目类型(mod / datapack / shader 等,数据包/光影下载用)
    - order_by / tags: 排序与分类标签过滤(透传给原生搜索)
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

    hits = search_mods(query, game_version, loader, limit, project_type,
                       order_by=order_by, tags=tags)
    for h in hits:
        cn = CN_NAMES.get(h["slug"])
        if cn:
            h["title"] = f"{cn}"
    return hits


def search_mods(query: str, game_version: str, loader: str | None = None,
                limit: int = 20, project_type: str | None = None,
                order_by: str = "downloads", tags: str = "") -> list:
    """搜索 Mod,返回 [{slug, title, description, downloads, author, categories}, ...]
    project_type: mod / datapack / shader 等(默认 None = 全部)。
    order_by: relevance(相关度) / downloads(下载量,默认) / updated(最近更新)。
    tags: 逗号分隔的分类标签(如 performance,utility),按 Modrinth 分类过滤。
    指定版本搜不到时,自动去掉版本过滤再试一次(很多项目只标了较新的版本,
    比如 lanserverproperties 没标 1.21.1,但实际能用)。"""
    params = {
        "query": query,
        "facets": _facets(game_version, loader, project_type, tags),
        "limit": limit,
        "index": order_by,
    }
    resp = requests.get(BASE + "/search", params=params, timeout=20)
    resp.raise_for_status()
    hits = resp.json().get("hits", [])
    if not hits and game_version:
        # 放宽:不按版本过滤重试
        try:
            resp2 = requests.get(BASE + "/search", params={
                "query": query,
                "facets": _facets("", loader, project_type, tags),
                "limit": limit,
                "index": order_by,
            }, timeout=20)
            hits = resp2.json().get("hits", [])
        except Exception:
            pass
    return [{
        "slug": h["slug"],
        "title": h.get("title", h["slug"]),
        "description": h.get("description", ""),
        "downloads": h.get("downloads", 0),
        "author": h.get("author", ""),
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


def _find_version(slug: str, game_version: str | None, loader: str | None,
                  version_number: str | None = None) -> dict | None:
    """按 (版本, 加载器) 查文件信息;game_version/loader 为 None 表示不过滤。"""
    params = {"game_versions": json.dumps([game_version] if game_version else []),
              "loaders": json.dumps([loader] if loader else [])}
    resp = requests.get(BASE + f"/project/{slug}/version", params=params, timeout=20)
    resp.raise_for_status()
    versions = resp.json()
    if version_number:
        versions = [v for v in versions if v.get("version_number") == version_number]
    if not versions:
        return None
    v = versions[0]
    primary = next((f for f in v.get("files", []) if f.get("primary")), None)
    f = primary or (v.get("files") or [{}])[0]
    return {
        "version_number": v.get("version_number", "?"),
        "filename": f.get("filename", "mod.jar"),
        "url": f.get("url", ""),
        "size": f.get("size", 0),
        "sha1": (f.get("hashes") or {}).get("sha1"),   # Modrinth 提供,下载后完整性校验
        "dependencies": v.get("dependencies", []),
    }


def get_mod_version(slug: str, game_version: str, loader: str | None,
                    version_number: str | None = None) -> dict | None:
    """找某个 Mod 在"指定游戏版本 + 加载器"下的文件信息。
    默认最新;version_number 指定时只在该版本里找。
    loader 传 None = 不按加载器过滤(数据包/光影包等无加载器的项目)。
    精确找不到时逐级放宽(不限版本 → 不限加载器),提高老版本/标记不全项目的成功率。
    返回 {version_number, filename, url, size, dependencies};没有匹配返回 None。"""
    for gv, ld in ((game_version, loader), (None, loader), (game_version, None), (None, None)):
        try:
            info = _find_version(slug, gv, ld, version_number)
        except Exception:
            info = None
        if info:
            return info
    return None


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
    download_with_mirror(info["url"], dest, sha1=info.get("sha1"),
                         progress_callback=progress_callback)
    return info["filename"]
