# -*- coding: utf-8 -*-
"""CurseForge 官方 API 的极小适配层。

只使用官方 REST API，不抓取网页，也不内置或共享 API Key。
资源中心当前接入 Minecraft Mod（classId=6）。
"""
import os

import requests

from downloader import download_file
from settings import load_settings

BASE = "https://api.curseforge.com/v1"
MINECRAFT_GAME_ID = 432
MINECRAFT_MOD_CLASS_ID = 6


class CurseForgeError(RuntimeError):
    pass


def api_key() -> str:
    return str(load_settings().get("curseforge_api_key", "") or "").strip()


def configured() -> bool:
    return bool(api_key())


def _headers() -> dict:
    key = api_key()
    if not key:
        raise CurseForgeError("未配置 CurseForge API Key（设置 → 系统 → CurseForge 资源）")
    return {"Accept": "application/json", "x-api-key": key}


def _get(path: str, params=None):
    response = requests.get(BASE + path, params=params, headers=_headers(), timeout=25)
    if response.status_code in (401, 403):
        raise CurseForgeError("CurseForge API Key 无效、未获授权或没有访问权限")
    response.raise_for_status()
    return response.json().get("data")


def _normalise(project: dict) -> dict:
    logo = project.get("logo") or {}
    authors = project.get("authors") or []
    categories = [c.get("name", "") for c in (project.get("categories") or []) if c.get("name")]
    project_id = project.get("id")
    return {
        "source": "curseforge", "curseforge_id": project_id,
        "slug": f"curseforge-{project_id}",
        "title": project.get("name") or str(project_id),
        "description": project.get("summary") or "",
        "downloads": int(project.get("downloadCount") or 0),
        "author": (authors[0].get("name") if authors else ""),
        "categories": categories,
        "icon_url": logo.get("thumbnailUrl") or logo.get("url") or "",
        "loaders": [], "website_url": (project.get("links") or {}).get("websiteUrl") or "",
    }


def search_mods(query: str, game_version: str | None = None, order_by: str = "downloads",
                offset: int = 0, limit: int = 30) -> list[dict]:
    sort_map = {"downloads": 6, "relevance": 1, "updated": 3}
    params = {"gameId": MINECRAFT_GAME_ID, "classId": MINECRAFT_MOD_CLASS_ID,
              "index": offset, "pageSize": limit, "sortField": sort_map.get(order_by, 6),
              "sortOrder": "desc"}
    if query:
        params["searchFilter"] = query
    if game_version:
        params["gameVersion"] = game_version
    return [_normalise(p) for p in (_get("/mods/search", params) or [])]


def get_mod(project_id: int) -> dict:
    return _normalise(_get(f"/mods/{int(project_id)}") or {})


def list_mod_files(project_id: int, game_version: str | None = None) -> list[dict]:
    files = _get(f"/mods/{int(project_id)}/files", {"pageSize": 50}) or []
    out = []
    for file in files:
        versions = file.get("gameVersions") or []
        if game_version and game_version not in versions:
            continue
        filename = file.get("fileName") or f"curseforge-{file.get('id')}.jar"
        out.append({"file_id": file.get("id"), "filename": filename,
                    "label": file.get("displayName") or filename})
    return out


def download_mod(project_id: int, file_id: int, target_dir: str, progress_callback=None) -> str:
    file = _get(f"/mods/{int(project_id)}/files/{int(file_id)}") or {}
    url = _get(f"/mods/{int(project_id)}/files/{int(file_id)}/download-url")
    if not url:
        raise CurseForgeError("该文件未提供 API 下载地址，可能受作者下载分发设置限制")
    hashes = file.get("hashes") or []
    sha1 = next((x.get("value") for x in hashes if x.get("algo") == 1), None)
    filename = file.get("fileName") or f"curseforge-{file_id}.jar"
    # CurseForge CDN 自 2026-07 起要求下载请求同样携带 Key，不能只在 API
    # 查询阶段认证；放 Header 避免 Key 出现在 URL、浏览器历史或下载日志中。
    download_file(str(url), os.path.join(target_dir, filename), sha1=sha1,
                  progress_callback=progress_callback, headers=_headers())
    return filename
