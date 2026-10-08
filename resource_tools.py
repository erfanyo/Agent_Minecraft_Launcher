# -*- coding: utf-8 -*-
"""其他资源工具：光影包/资源包/数据包的搜索与安装。

这些项目类型在 Modrinth 上不属于 mod/modpack，但用户常会单独下载：
- resourcepack: 资源包/材质包
- shader: 光影包（光影加载器如 iris/oculus/optifine）
"""
from __future__ import annotations

import os
import re

import paths
from downloader import download_with_mirror
from modrinth import get_mod_version, search_mods_cn


def _resolve_resource_ref(ref: str) -> str:
    """从 Modrinth 链接或 slug 里提取项目的 slug。"""
    ref = (ref or "").strip()
    if not ref:
        return ""
    # 优先按明确的项目类型路径解析
    m = re.search(r"/(?:shader|resourcepack|shaderpack|datapack)/([^/?#\s]+)", ref)
    if m:
        return m.group(1)
    # 通用 Modrinth 项目链接
    m = re.search(r"modrinth\.com/[^/#?\s]+/([^/?#\s]+)", ref)
    if m:
        return m.group(1)
    return ref.split("?")[0].strip("/").split("/")[-1]


def _pack_dir(instance: str, subdir: str, game_dir: str | None = None) -> str:
    """返回实例下 resourcepacks/shaderpacks 等目录，不存在时自动创建。"""
    d = os.path.join(paths.instance_dir(instance, game_dir), subdir)
    os.makedirs(d, exist_ok=True)
    return d


def _format_file_list(files: list[str], directory: str = "") -> str:
    """列文件名;顺带给出实际查找目录,便于排查「有文件夹却没找到」。"""
    listing = ("\n".join(os.path.basename(p) for p in sorted(files))
               if files else "(暂无)")
    return f"{listing}\n目录:{directory}" if directory else listing


def search_resource_packs(query: str, game_version: str = "", loader: str = "") -> str:
    """搜索资源包/材质包(Modrinth project_type=resourcepack)，支持中文名。"""
    hits = search_mods_cn(query, game_version or None, loader or None, limit=15,
                          project_type="resourcepack")
    if not hits:
        return f"(没有找到资源包{'：' + query if query else ''})"
    lines = []
    for h in hits:
        loaders = ", ".join(h.get("loaders") or [])
        lines.append(f"{h['title']}  slug={h['slug']}  ⬇{h.get('downloads', 0):,}"
                     f"  加载器:{loaders or 'minecraft'}")
    return "\n".join(lines)


def search_shaders(query: str, game_version: str = "", loader: str = "") -> str:
    """搜索光影包(Modrinth project_type=shader)，支持中文名。

    loader 可选：iris/oculus/optifine 等。
    """
    hits = search_mods_cn(query, game_version or None, loader or None, limit=15,
                          project_type="shader")
    if not hits:
        return f"(没有找到光影包{'：' + query if query else ''})"
    lines = []
    for h in hits:
        loaders = ", ".join(h.get("loaders") or [])
        lines.append(f"{h['title']}  slug={h['slug']}  ⬇{h.get('downloads', 0):,}"
                     f"  加载器:{loaders or '不限'}")
    return "\n".join(lines)


def list_resource_packs(instance: str, game_dir: str | None = None) -> str:
    """列出某实例 resourcepacks/ 目录下已下载的资源包。"""
    d = _pack_dir(instance, "resourcepacks", game_dir)
    files = [os.path.join(d, f) for f in os.listdir(d) if not f.startswith(".")]
    files = [p for p in files if os.path.isfile(p)]
    return _format_file_list(files, d)


def list_shaders(instance: str, game_dir: str | None = None) -> str:
    """列出某实例 shaderpacks/ 目录下已下载的光影包。"""
    d = _pack_dir(instance, "shaderpacks", game_dir)
    files = [os.path.join(d, f) for f in os.listdir(d) if not f.startswith(".")]
    files = [p for p in files if os.path.isfile(p)]
    return _format_file_list(files, d)


def install_resource_pack(slug_or_url: str, instance: str,
                          game_version: str = "", loader: str = "",
                          game_dir: str | None = None,
                          status=print,
                          progress_callback=None) -> str:
    """给指定实例下载并安装一个资源包(Modrinth project_type=resourcepack)。

    - slug_or_url: 资源包 slug 或 Modrinth 链接。
    - instance: 实例 id。
    - game_version/loader: 可选过滤；资源包通常 loader='minecraft'，留空则自动找最新。
    """
    slug = _resolve_resource_ref(slug_or_url)
    if not slug:
        return "错误：无法识别资源包引用(需要 Modrinth 链接或 slug)"
    info = get_mod_version(slug, game_version or None, loader or None)
    if not info or not info.get("url"):
        # 资源包通常不标加载器，回退忽略加载器过滤
        info = get_mod_version(slug, game_version or None, None)
    if not info or not info.get("url"):
        return (f"错误：在 Modrinth 上找不到资源包 {slug} 的可用文件"
                f"(版本 {game_version or '任意'}, 加载器 {loader or '不限'})")
    target_dir = _pack_dir(instance, "resourcepacks", game_dir)
    dest = os.path.join(target_dir, info["filename"])
    try:
        download_with_mirror(info["url"], dest, sha1=info.get("sha1"),
                             progress_callback=progress_callback)
    except Exception as e:
        return f"下载失败：{type(e).__name__}: {e}"
    if status:
        status(f"资源包已下载：{info['filename']}")
    return (f"成功：资源包 {slug} ({info['version_number']}) 已安装到"
            f"实例 {instance} 的 resourcepacks/ 目录")


def install_shader(slug_or_url: str, instance: str,
                   game_version: str = "", loader: str = "",
                   game_dir: str | None = None,
                   status=print,
                   progress_callback=None) -> str:
    """给指定实例下载并安装一个光影包(Modrinth project_type=shader)。

    - slug_or_url: 光影包 slug 或 Modrinth 链接。
    - instance: 实例 id。
    - game_version/loader: 可选过滤；常见光影加载器：iris/oculus/optifine。
    """
    slug = _resolve_resource_ref(slug_or_url)
    if not slug:
        return "错误：无法识别光影包引用(需要 Modrinth 链接或 slug)"
    info = get_mod_version(slug, game_version or None, loader or None)
    if not info or not info.get("url"):
        # 光影包加载器标记可能不一致，回退忽略加载器过滤
        info = get_mod_version(slug, game_version or None, None)
    if not info or not info.get("url"):
        return (f"错误：在 Modrinth 上找不到光影包 {slug} 的可用文件"
                f"(版本 {game_version or '任意'}, 加载器 {loader or '不限'})")
    target_dir = _pack_dir(instance, "shaderpacks", game_dir)
    dest = os.path.join(target_dir, info["filename"])
    try:
        download_with_mirror(info["url"], dest, sha1=info.get("sha1"),
                             progress_callback=progress_callback)
    except Exception as e:
        return f"下载失败：{type(e).__name__}: {e}"
    if status:
        status(f"光影包已下载：{info['filename']}")
    return (f"成功：光影包 {slug} ({info['version_number']}) 已安装到"
            f"实例 {instance} 的 shaderpacks/ 目录")
