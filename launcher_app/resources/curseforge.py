# -*- coding: utf-8 -*-
"""CurseForge 官方 API 的极小适配层。

元数据使用官方 REST API；整合包文件支持 CDN 与 MCIM 回退。
不抓取网页。获批发行版可在构建时注入应用 Key；公开源码不含 Key。
资源中心支持 Mod、整合包、光影、数据包和资源包。
"""
import os
import re
import sys

import requests

from launcher_app.resources.downloader import download_file
from settings import load_settings
from launcher_app.core.safe_paths import safe_child, safe_component
from launcher_app.core.task_context import checkpoint

BASE = "https://api.curseforge.com/v1"
MINECRAFT_GAME_ID = 432
MINECRAFT_MOD_CLASS_ID = 6
RESOURCE_CLASS_IDS = {"mod": 6, "modpack": 4471, "shader": 6552, "datapack": 6945, "resourcepack": 12}


class CurseForgeError(RuntimeError):
    pass


def api_key() -> str:
    custom = str(load_settings().get("curseforge_api_key", "") or "").strip()
    if custom:
        return custom
    if getattr(sys, 'frozen', False):
        from launcher_app.runtime.bundled_credentials import curseforge_key
        return curseforge_key()
    return ''


def configured() -> bool:
    return bool(api_key())


def _headers() -> dict:
    key = api_key()
    if not key:
        raise CurseForgeError("未配置 CurseForge API Key（设置 → 系统 → CurseForge 资源）")
    return {"Accept": "application/json", "x-api-key": key}


def _get_payload(path: str, params=None):
    checkpoint()
    response = requests.get(BASE + path, params=params, headers=_headers(), timeout=25,
                            allow_redirects=False)
    if 300 <= response.status_code < 400:
        raise CurseForgeError('CurseForge API 返回重定向，未向其他地址转发应用 Key')
    if response.status_code in (401, 403):
        raise CurseForgeError("CurseForge API Key 无效、未获授权或没有访问权限")
    response.raise_for_status()
    return response.json()


def _batch(path: str, field: str, ids: list[int]) -> dict:
    """Fetch metadata for this operation only; no persistent API cache."""
    records = {}
    values = list(dict.fromkeys(int(value) for value in ids))
    for start in range(0, len(values), 50):
        checkpoint()
        with requests.post(BASE + path, json={field: values[start:start + 50]},
                           headers=_headers(), timeout=25, allow_redirects=False) as response:
            if 300 <= response.status_code < 400:
                raise CurseForgeError('CurseForge API 返回重定向，未向其他地址转发应用 Key')
            if response.status_code in (401, 403):
                raise CurseForgeError('CurseForge API Key 无效、未获授权或没有访问权限')
            response.raise_for_status()
            for record in response.json().get('data') or []:
                records[int(record['id'])] = record
    return records


def get_pack_metadata(entries: list[dict]) -> tuple[dict, dict]:
    return (_batch('/mods/files', 'fileIds', [entry['fileID'] for entry in entries]),
            _batch('/mods', 'modIds', [entry['projectID'] for entry in entries]))


def download_pack_file(entry: dict, file: dict, project: dict, instance_dir: str,
                       *, target_dir: str | None = None, progress_callback=None) -> str:
    """Install the exact manifest file, with CDN/mirror fallback and SHA1 checks."""
    checkpoint()
    project_id, file_id = int(entry['projectID']), int(entry['fileID'])
    if int(file.get('id', -1)) != file_id or int(file.get('modId', -1)) != project_id:
        raise CurseForgeError(f'CF 文件与清单不匹配：{project_id}/{file_id}')
    folder = {6: 'mods', 12: 'resourcepacks', 6552: 'shaderpacks',
              6945: 'datapacks', 4471: 'downloads'}.get(project.get('classId'))
    if not folder:
        raise CurseForgeError(f'不支持的 CF 资源类型：{project.get("classId")}（项目 {project_id}）')
    filename = str(file.get('fileName') or '')
    safe_component(filename)
    destination = safe_child(target_dir, filename) if target_dir else safe_child(instance_dir, folder + '/' + filename)
    sha1 = next((value.get('value') for value in file.get('hashes') or [] if value.get('algo') == 1), None)
    if not sha1:
        raise CurseForgeError(f'CF 文件缺少 SHA1 校验值：{project_id}/{file_id}')
    from launcher_app.resources.downloader import sha1_of_file
    if os.path.isfile(destination) and sha1_of_file(destination).lower() == sha1.lower():
        return filename
    if project.get('allowModDistribution') is False:
        website = (project.get('links') or {}).get('websiteUrl') or f'https://www.curseforge.com/projects/{project_id}'
        raise CurseForgeError(f'作者限制第三方分发，请手动下载 {filename} 放入 {folder}/ 后重试：'
                              f'{website.rstrip("/")}/files/{file_id}')
    from urllib.parse import urlparse, quote
    url = file.get('downloadUrl')
    if not url and project.get('allowModDistribution') is not False:
        try:
            url = _get(f'/mods/{project_id}/files/{file_id}/download-url')
        except requests.RequestException:
            url = None
    if url:
        parsed = urlparse(str(url))
        if parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.forgecdn.net'):
            raise CurseForgeError('CF 返回了不受支持的下载域名，未发送 API Key')
    else:
        # CF file IDs encode the CDN directory; preserve exact manifest version.
        url = f'https://edge.forgecdn.net/files/{file_id // 1000}/{file_id % 1000}/{quote(filename, safe="")}'
    candidates = list(dict.fromkeys([
        str(url), str(url).replace('://edge.', '://mediafilez.').replace('://media.', '://mediafilez.'),
        str(url).replace('://mediafilez.', '://edge.').replace('://media.', '://edge.'),
        f'https://mod.mcimirror.top/files/{file_id // 1000}/{file_id % 1000}/{quote(filename, safe="")}',
    ]))
    errors = []
    for candidate in candidates:
        checkpoint()
        try:
            # The API key must never be sent to a mirror.
            download_file(candidate, destination, sha1=sha1.lower(), headers={}, timeout=(5, 12),
                          progress_callback=progress_callback)
            return filename
        except (requests.RequestException, ValueError, OSError) as error:
            response = getattr(error, 'response', None)
            errors.append(str(response.status_code) if response is not None else type(error).__name__)
    website = (project.get('links') or {}).get('websiteUrl') or f'https://www.curseforge.com/projects/{project_id}'
    raise CurseForgeError(f'自动下载未成功，请手动下载 {filename} 放入 {folder}/ 后重试：'
                         f'{website.rstrip("/")}/files/{file_id}（候选源：{", ".join(errors)}）')


def _get(path: str, params=None):
    return _get_payload(path, params).get("data")


def _normalise(project: dict) -> dict:
    logo = project.get("logo") or {}
    authors = project.get("authors") or []
    categories = [c.get("name", "") for c in (project.get("categories") or []) if c.get("name")]
    project_id = project.get("id")
    return {
        "source": "curseforge", "curseforge_id": project_id,
        "project_type": next((kind for kind, class_id in RESOURCE_CLASS_IDS.items() if class_id == project.get('classId')), 'mod'),
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
                offset: int = 0, limit: int = 30, project_type: str = "mod",
                loader: str | None = None) -> list[dict]:
    sort_map = {"downloads": 6, "relevance": 1, "updated": 3}
    params = {"gameId": MINECRAFT_GAME_ID, "classId": RESOURCE_CLASS_IDS[project_type],
              "index": offset, "pageSize": limit, "sortField": sort_map.get(order_by, 6),
              "sortOrder": "desc"}
    if query:
        params["searchFilter"] = query
    if game_version:
        params["gameVersion"] = game_version
    loader_type = {'forge': 1, 'liteloader': 3, 'fabric': 4, 'quilt': 5, 'neoforge': 6}.get(loader)
    if loader_type and project_type in ('mod', 'modpack'):
        params['modLoaderType'] = loader_type
    return [_normalise(p) for p in (_get("/mods/search", params) or [])]


def get_mod(project_id: int) -> dict:
    return _normalise(_get(f"/mods/{int(project_id)}") or {})


def list_mod_files(project_id: int, game_version: str | None = None,
                   max_files: int = 50, loader: str | None = None) -> list[dict]:
    files = []
    index = 0
    while index < max_files:
        page_size = min(50, max_files - index)
        params = {"index": index, "pageSize": page_size}
        if game_version:
            params['gameVersion'] = game_version
        loader_type = {'forge': 1, 'liteloader': 3, 'fabric': 4, 'quilt': 5, 'neoforge': 6}.get(loader)
        if loader_type:
            params['modLoaderType'] = loader_type
        page = _get(f"/mods/{int(project_id)}/files", params) or []
        files.extend(page)
        index += len(page)
        if len(page) < page_size:
            break
    out = []
    known_loaders = {'forge', 'neoforge', 'fabric', 'quilt', 'rift', 'liteloader'}
    minecraft_version = re.compile(r'^(?:\d+\.\d+(?:\.[\w-]+)*|\d{2}w\d{2}[a-z])$', re.I)
    for file in files:
        if file.get('isServerPack'):
            continue
        versions = [str(tag).strip() for tag in file.get("gameVersions") or []]
        if game_version and game_version not in versions:
            continue
        if loader and loader.lower() not in [tag.lower() for tag in versions]:
            continue
        filename = file.get("fileName") or f"curseforge-{file.get('id')}.jar"
        out.append({"file_id": file.get("id"), "filename": filename,
                    "label": file.get("displayName") or filename,
                    "game_versions": [tag for tag in versions if minecraft_version.fullmatch(tag)],
                    "loaders": [tag.lower() for tag in versions if tag.lower() in known_loaders]})
    return out


def list_mod_file_compatibility(project_id: int, max_files: int = 500) -> dict:
    """Read file tags across pages for the detail panel, without disk caching."""
    known_loaders = {'forge', 'neoforge', 'fabric', 'quilt', 'rift', 'liteloader'}
    minecraft_version = re.compile(r'^(?:\d+\.\d+(?:\.[\w-]+)*|\d{2}w\d{2}[a-z])$', re.I)
    records = []
    index = 0
    total = None
    page_size = 50
    while index < max_files:
        payload = _get_payload(f"/mods/{int(project_id)}/files",
                               {"index": index, "pageSize": page_size})
        files = payload.get('data') or []
        total = (payload.get('pagination') or {}).get('totalCount', total)
        for file in files:
            tags = [str(tag).strip() for tag in file.get('gameVersions') or []]
            loaders = [tag.lower() for tag in tags if tag.lower() in known_loaders]
            game_versions = [tag for tag in tags if minecraft_version.fullmatch(tag)]
            records.append({'loaders': loaders, 'game_versions': game_versions})
        index += len(files)
        if not files or (total is not None and index >= total) or len(files) < page_size:
            break
    return {'versions': records, 'partial': total is not None and index < total}


def download_mod(project_id: int, file_id: int, target_dir: str, progress_callback=None) -> str:
    file = _get(f"/mods/{int(project_id)}/files/{int(file_id)}") or {}
    project = _get(f"/mods/{int(project_id)}") or {}
    return download_pack_file({'projectID': int(project_id), 'fileID': int(file_id)},
                              file, project, target_dir, target_dir=target_dir,
                              progress_callback=progress_callback)
