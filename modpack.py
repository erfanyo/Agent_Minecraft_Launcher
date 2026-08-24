# -*- coding: utf-8 -*-
"""
整合包导入(支持多种格式,自动识别 .zip 内部是哪种整合包)。

支持的格式:
- **Modrinth `.mrpack`**(modrinth.index.json):清单式,下载清单里的每个文件(Modrinth 链接)。
- **CurseForge `.zip`**(manifest.json):读 manifest 拿 MC 版本 + 加载器(自动装),并解压 overrides/;
  清单里用 CurseForge fileID 列出的文件需 CurseForge API 密钥,无法自动下载 → 会明确提示"已装基础+配置/覆盖文件,列表文件需手动或用工具导入"。
- **扁平整合包 `.zip`**(无清单,就是一个实例文件夹的压缩包):内含 mods/ config/ shaderpacks/ saves/ kubejs/ 等,
  可能是 FTB / 手工 / 旧式整合包。导入时需提供 MC 版本(可选加载器),直接把 zip 内容解压成新实例。

用法:
  from modpack import import_modpack, detect_modpack_format
  fmt = detect_modpack_format(path)  # 'modrinth'/'curseforge'/'flat'/None
  import_modpack(path, game_dir, mc_version='1.20.1', loader='fabric')
"""
import json
import os
import re
import shutil
import zipfile

from downloader import download_with_mirror
from game_files import install_version_files
from loaders import install_loader

# 只去掉对文件系统不友好的字符,中文包名保留
VALID_ID = re.compile(r'[\\/:*?"<>|\r\n]+')

# 扁平整合包/实例文件夹常见根目录(根部出现这些即判定为"实例文件夹 zip")
_FLAT_ROOT_HINTS = ("mods/", "config/", "shaderpacks/", "resourcepacks/", "saves/", "kubejs/",
                    "defaultconfigs/", "scripts/")


def _safe_name(name: str) -> str:
    """把整合包名变成安全的目录名"""
    clean = VALID_ID.sub("-", name).strip("-")
    return clean or "modpack"


def _ensure_base(mc: str, game_dir: str,
                 status_callback=None, progress_callback=None) -> None:
    """确保原版 mc 已安装(JSON + 客户端 jar + 依赖库/资源),没装就装"""
    from fetch_versions import fetch_version_detail, fetch_version_manifest

    base_json = os.path.join(game_dir, "versions", mc, mc + ".json")
    base_jar = os.path.join(game_dir, "versions", mc, mc + ".jar")

    if not os.path.exists(base_json):
        if status_callback:
            status_callback(f"获取原版 {mc} 信息...")
        manifest = fetch_version_manifest()
        entry = next((v for v in manifest["versions"]
                      if v["id"] == mc and v["type"] == "release"), None)
        if entry is None:
            raise ValueError(f"清单里没有原版 {mc}")
        d = fetch_version_detail(entry["url"])
        os.makedirs(os.path.dirname(base_json), exist_ok=True)
        with open(base_json, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    else:
        with open(base_json, encoding="utf-8") as f:
            d = json.load(f)

    if not os.path.exists(base_jar):
        client = (d.get("downloads") or {}).get("client")
        if client:
            if status_callback:
                status_callback(f"下载原版 {mc} 客户端...")
            download_with_mirror(client["url"], base_jar, version_id=mc,
                                 sha1=client.get("sha1"),
                                 progress_callback=progress_callback)

    if status_callback:
        status_callback(f"检查 {mc} 的依赖库与资源...")
    _n, failures = install_version_files(d, game_dir,
                                         progress_callback=progress_callback,
                                         status_callback=status_callback)
    if failures:
        raise RuntimeError(f"{len(failures)} 个基础文件下载失败,如 {failures[0][0]}")


def _install_loader_from_deps(deps: dict, mc: str, game_dir: str,
                              status_callback=None, progress_callback=None) -> str | None:
    """按整合包依赖安装加载器,返回实例的基础(loader 版本 id 或 None)"""
    if deps.get("fabric-loader"):
        loader, ver = "fabric", deps["fabric-loader"]
    elif deps.get("forge"):
        loader, ver = "forge", deps["forge"]
    else:
        return None
    ver = None if ver in ("*", "") else ver
    if status_callback:
        status_callback(f"安装加载器 {loader}...")
    return install_loader(loader, mc, game_dir, loader_version=ver,
                          progress_callback=progress_callback,
                          status_callback=status_callback)


def _looks_like_instance_folder(names: list) -> bool:
    """zip 内容是否是"实例文件夹"式(路径段里含 mods/config/shaderpacks 等目录)。"""
    for n in names:
        if n.endswith("/"):
            continue   # 只看文件项
        parts = n.lower().split("/")
        for h in _FLAT_ROOT_HINTS:
            if h.rstrip("/") in parts:
                return True
    return False


def _flat_single_prefix(names: list) -> str | None:
    """若所有条目都在唯一一个顶层文件夹内,返回该前缀(如 'MyPack/'),否则 None。"""
    tops = {n.split("/", 1)[0] for n in names if n and not n.startswith("/")}
    if len(tops) != 1:
        return None
    the_one = next(iter(tops))
    # 该顶层确实是文件夹(至少有一个子项,不全是它自己)
    if any(n.startswith(the_one + "/") and not n.endswith("/") for n in names):
        return the_one + "/"
    return None


def _extract_zip_to(path: str, inst_dir: str, prefix: str, status_callback=None):
    """把 zip 内容解压进实例目录(去掉 prefix);跳过目录项。"""
    with zipfile.ZipFile(path) as z:
        for member in z.namelist():
            if not member or member.endswith("/"):
                continue
            if prefix and member.startswith(prefix):
                rel = member[len(prefix):]
            else:
                rel = member
            if not rel or rel.startswith(("../", "/")) or ".." in rel.split("/"):
                continue
            dest = os.path.join(inst_dir, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(member) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)


def _cf_loader(manifest: dict):
    """从 CurseForge manifest 取 (loader_type, loader_version)。modLoaders 里的 id 形如
    fabric-0.15.0 / forge-47.1.0 / neoforge-20.1.1 / quilt-0.22。"""
    ml = (manifest.get("minecraft") or {}).get("modLoaders") or []
    lid = ""
    for l in ml:
        if l.get("primary"):
            lid = l.get("id", "")
            break
    if not lid and ml:
        lid = ml[0].get("id", "")
    idx = lid.find("-")
    if idx <= 0:
        return None, None
    typ = lid[:idx].lower()
    typ = {"quilt": "fabric"}.get(typ, typ)
    return typ, lid[idx + 1:]


def detect_modpack_format(path: str) -> str | None:
    """识别 .zip/.mrpack 是哪种整合包:'modrinth'/'curseforge'/'flat'/None(无法识别)。"""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "modrinth.index.json" in names:
                return "modrinth"
            if "manifest.json" in names:
                return "curseforge"
            if _looks_like_instance_folder(names):
                return "flat"
    except Exception:
        pass
    return None


def import_modpack(path: str, game_dir: str,
                   mc_version: str | None = None,
                   loader: str | None = None,
                   loader_version: str | None = None,
                   status_callback=None, progress_callback=None) -> str:
    """导入整合包(自动识别格式),返回实例 ID。

    - Modrinth .mrpack:mc/加载器从清单读(无需参数)。
    - CurseForge .zip:mc/加载器从 manifest 读(无需参数);只装基础+加载器+解压 overrides,
      清单里的文件列表需 CurseForge API(跳过),会附加提示。
    - 扁平 .zip(实例文件夹):需 mc_version(否则报错);可选 loader/loader_version;
      直接把 zip 内容解压成新实例。
    """
    if not os.path.isfile(path):
        raise ValueError("文件不存在")
    fmt = detect_modpack_format(path)
    if fmt is None:
        raise ValueError("无法识别的整合包格式(既不是 Modrinth/CurseForge,也不像实例文件夹)")

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if fmt == "modrinth":
            index = json.loads(z.read("modrinth.index.json"))
            name = index.get("name") or os.path.splitext(os.path.basename(path))[0]
            mc = (index.get("dependencies") or {}).get("minecraft", "")
            if not mc:
                raise ValueError("整合包清单里缺少 minecraft 版本")
            deps = index.get("dependencies") or {}
            cf = None
        elif fmt == "curseforge":
            manifest = json.loads(z.read("manifest.json"))
            name = manifest.get("name") or os.path.splitext(os.path.basename(path))[0]
            mc = (manifest.get("minecraft") or {}).get("version", "")
            if not mc:
                raise ValueError("CurseForge 清单里缺少 minecraft 版本")
            if not mc_version:
                mc_version = mc
            ltype, lver = _cf_loader(manifest)
            loader = loader or ltype
            loader_version = loader_version or lver
            index = None
            deps = {}
            cf = True
        else:   # flat
            name = os.path.splitext(os.path.basename(path))[0]
            mc = mc_version or ""
            if not mc:
                raise ValueError("扁平整合包(实例文件夹 zip)需要指定游戏版本,如 1.20.1")
            index = None
            deps = {}
            cf = None

    if not mc:
        raise ValueError("整合包缺少 minecraft 版本")
    instance_id = _safe_name(name)
    inst_dir = os.path.join(game_dir, "versions", instance_id)
    if os.path.exists(inst_dir):
        raise ValueError(f"已存在同名实例:{instance_id}")
    if status_callback:
        status_callback(f"开始导入整合包:{name}(mc {mc})...")

    # 1) 原版本体
    _ensure_base(mc, game_dir, status_callback, progress_callback)

    # 2) 加载器:Modrinth 用依赖表;其它格式用传入/解析出的 loader
    base_instance = None
    if index is not None:
        base_instance = _install_loader_from_deps(index.get("dependencies") or {}, mc,
                                                  game_dir, status_callback, progress_callback)
    elif loader:
        if status_callback:
            status_callback(f"安装加载器 {loader}...")
        try:
            base_instance = install_loader(loader, mc, game_dir, loader_version=loader_version,
                                           progress_callback=progress_callback,
                                           status_callback=status_callback)
        except Exception as e:
            if status_callback:
                status_callback(f"加载器安装失败(跳过,仅原版):{e}")
            base_instance = None

    # 3) 创建实例目录,放好版本 JSON 和客户端 jar
    os.makedirs(inst_dir, exist_ok=True)
    src_id = base_instance or mc
    src_json = os.path.join(game_dir, "versions", src_id, src_id + ".json")
    src_jar = os.path.join(game_dir, "versions", src_id, src_id + ".jar")
    if os.path.exists(src_json):
        shutil.copyfile(src_json, os.path.join(inst_dir, instance_id + ".json"))
    if os.path.exists(src_jar):
        shutil.copyfile(src_jar, os.path.join(inst_dir, instance_id + ".jar"))

    # 4) 按格式放内容
    if index is not None:
        # Modrinth:下载清单里的文件
        files = index.get("files", [])
        for i, f in enumerate(files, 1):
            rel = f.get("path", "")
            if not rel or rel.startswith("../"):
                continue
            dest = os.path.join(inst_dir, rel.replace("/", os.sep))
            downloads = f.get("downloads") or []
            if not downloads or os.path.exists(dest):
                continue
            if status_callback:
                status_callback(f"下载整合包文件 {i}/{len(files)}:{os.path.basename(rel)}")
            try:
                download_with_mirror(downloads[0], dest,
                                     sha1=(f.get("hashes") or {}).get("sha1"),
                                     progress_callback=progress_callback)
            except Exception as e:
                if status_callback:
                    status_callback(f"文件下载失败(跳过):{os.path.basename(rel)} {e}")

    # Modrinth + CurseForge 都解压 overrides / client-overrides(直接覆盖进实例的文件)
    if index is not None or cf:
        _extract_zip_to(path, inst_dir, "overrides/", status_callback)
        _extract_zip_to(path, inst_dir, "client-overrides/", status_callback)

    if cf:
        listed = len((manifest.get("files") or []))
        if status_callback:
            if listed:
                status_callback(f"CurseForge 清单里还有 {listed} 个文件需 CurseForge API,已跳过;"
                                "已解压 overrides(配置/覆盖文件),mod 请用工具从 CurseForge 另行导入")
            else:
                status_callback("已解压 overrides(含 mods/配置/覆盖文件),无需 CurseForge 额外下载")

    if index is None and not cf:
        # 扁平:整个 zip 解压成实例(去掉可能存在的单一顶层文件夹)
        prefix = _flat_single_prefix(names)
        _extract_zip_to(path, inst_dir, prefix or "", status_callback)

    return instance_id
