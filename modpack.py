# -*- coding: utf-8 -*-
"""
整合包导入(Modrinth .mrpack 格式)。

.mrpack 其实就是一个 zip,里面:
- modrinth.index.json —— 清单(名字、mc 版本、依赖的加载器、文件列表)
- overrides/ 或 client-overrides/ —— 直接覆盖进实例的附加文件(配置、资源包等)

导入流程:
1. 确保原版本体已装(JSON + 客户端 jar + 依赖库/资源)
2. 按清单里的依赖安装加载器(能指定版本)
3. 创建实例目录,下载清单里的每个 Mod 文件
4. 把 overrides 解压进实例目录

CurseForge 的 .zip(manifest.json)需要 CurseForge API 密钥,暂不支持,会明确报错。
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


def import_modpack(path: str, game_dir: str,
                   status_callback=None, progress_callback=None) -> str:
    """导入 Modrinth 整合包(.mrpack),返回实例 ID。"""
    if not os.path.isfile(path):
        raise ValueError("文件不存在")

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "modrinth.index.json" in names:
            index = json.loads(z.read("modrinth.index.json"))
        elif "manifest.json" in names:
            raise ValueError(
                "这是 CurseForge 整合包,暂不支持(需要 CurseForge API 密钥)。"
                "请转用 Modrinth 格式的 .mrpack")
        else:
            raise ValueError("无法识别的整合包格式")

    name = index.get("name") or os.path.splitext(os.path.basename(path))[0]
    mc = (index.get("dependencies") or {}).get("minecraft", "")
    if not mc:
        raise ValueError("整合包清单里缺少 minecraft 版本")
    instance_id = _safe_name(name)

    inst_dir = os.path.join(game_dir, "versions", instance_id)
    if os.path.exists(inst_dir):
        raise ValueError(f"已存在同名实例:{instance_id}")

    if status_callback:
        status_callback(f"开始导入整合包:{name}(mc {mc})...")

    # 1) 原版本体
    _ensure_base(mc, game_dir, status_callback, progress_callback)

    # 2) 加载器(清单里有依赖就装)
    base_instance = _install_loader_from_deps(index.get("dependencies") or {}, mc,
                                              game_dir, status_callback, progress_callback)

    # 3) 创建实例目录,放好版本 JSON 和客户端 jar
    os.makedirs(inst_dir, exist_ok=True)
    if base_instance:
        # 复用加载器版本的 JSON 和 jar,保证启动/扫描都正常
        src_json = os.path.join(game_dir, "versions", base_instance, base_instance + ".json")
        src_jar = os.path.join(game_dir, "versions", base_instance, base_instance + ".jar")
        if os.path.exists(src_json):
            shutil.copyfile(src_json, os.path.join(inst_dir, instance_id + ".json"))
        if os.path.exists(src_jar):
            shutil.copyfile(src_jar, os.path.join(inst_dir, instance_id + ".jar"))
    else:
        src_json = os.path.join(game_dir, "versions", mc, mc + ".json")
        src_jar = os.path.join(game_dir, "versions", mc, mc + ".jar")
        shutil.copyfile(src_json, os.path.join(inst_dir, instance_id + ".json"))
        shutil.copyfile(src_jar, os.path.join(inst_dir, instance_id + ".jar"))

    # 4) 下载整合包里的 Mod 文件(带 sha1 校验,已存在跳过)
    files = index.get("files", [])
    for i, f in enumerate(files, 1):
        rel = f.get("path", "")
        if not rel or rel.startswith("../"):
            continue
        dest = os.path.join(inst_dir, rel.replace("/", os.sep))
        downloads = f.get("downloads") or []
        if not downloads:
            continue
        if os.path.exists(dest):
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

    # 5) overrides / client-overrides 解压进实例目录
    with zipfile.ZipFile(path) as z:
        for prefix in ("overrides/", "client-overrides/"):
            for member in z.namelist():
                if not member.startswith(prefix) or member.endswith("/"):
                    continue
                rel = member[len(prefix):]
                dest = os.path.join(inst_dir, rel.replace("/", os.sep))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(member) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    return instance_id
