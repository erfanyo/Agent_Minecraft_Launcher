# -*- coding: utf-8 -*-
"""
加载器安装:Fabric / Forge。

两种加载器的版本 JSON 都"继承"原版(inheritsFrom 字段),
所以装完加载器后,启动时把继承链合并成完整数据即可(见 launcher.resolve_inherited_json)。

- Fabric:meta.fabricmc.net 直接提供 profile JSON,一步到位
- Forge :maven 仓库只发 installer jar,版本 JSON 藏在 jar 里的 install_profile.json
         和 version.json 中,需要下载 jar 后解压提取

NeoForge 的接口暂未探明,以后补(框架完全通用)。
"""
import json
import os
import re
import shutil
import subprocess
import zipfile

import requests

from downloader import download_with_mirror
from game_files import _maven_path, install_version_files
from launcher import resolve_inherited_json

FABRIC_META = "https://meta.fabricmc.net/v2/versions/loader/{mc}"
FABRIC_PROFILE = "https://meta.fabricmc.net/v2/versions/loader/{mc}/{loader}/profile/json"
FORGE_META = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
FORGE_INSTALLER = "https://maven.minecraftforge.net/net/minecraftforge/forge/{ver}/forge-{ver}-installer.jar"
NEOFORGE_META = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
NEOFORGE_INSTALLER = "https://maven.neoforged.net/releases/net/neoforged/neoforge/{ver}/neoforge-{ver}-installer.jar"


def list_fabric_loaders(mc: str) -> list:
    """Fabric 可用的加载器版本列表(新的在前)"""
    resp = requests.get(FABRIC_META.format(mc=mc), timeout=20)
    resp.raise_for_status()
    return [i["loader"]["version"] for i in resp.json()]


def list_forge_versions(mc: str) -> list:
    """Forge 可用于 mc 的版本列表(新的在前,如 26.2-65.1.2)"""
    resp = requests.get(FORGE_META, timeout=20)
    resp.raise_for_status()
    versions = re.findall(r"<version>([^<]+)</version>", resp.text)
    prefix = mc + "-"
    matches = [v for v in versions if v.startswith(prefix)]
    return list(reversed(matches))


def _latest_fabric_loader(mc: str) -> str:
    """查 Fabric 元数据,返回 mc 可用的最新稳定 loader 版本号"""
    resp = requests.get(FABRIC_META.format(mc=mc), timeout=20)
    resp.raise_for_status()
    for item in resp.json():
        if item.get("loader", {}).get("stable"):
            return item["loader"]["version"]
    raise RuntimeError(f"Fabric 没有可用的 {mc} 加载器")


def _latest_forge_version(mc: str) -> str:
    """解析 Forge maven 元数据,返回 26.2 最新的完整版本号(如 26.2-65.1.2)"""
    resp = requests.get(FORGE_META, timeout=20)
    resp.raise_for_status()
    versions = re.findall(r"<version>([^<]+)</version>", resp.text)
    prefix = mc + "-"
    matches = [v for v in versions if v.startswith(prefix)]
    if not matches:
        raise RuntimeError(f"Forge 没有可用的 {mc} 版本")
    return matches[-1]  # maven 元数据按顺序排列,取最后一个


def list_neoforge_versions(mc: str) -> list:
    """NeoForge 可用于 mc 的版本列表(新的在前,如 1.21.1 → 21.1.248)。
    版本规则:1.21.1 → 21.1.*;26.2 → 26.2.*"""
    resp = requests.get(NEOFORGE_META, timeout=20)
    resp.raise_for_status()
    versions = re.findall(r"<version>([^<]+)</version>", resp.text)
    prefix = (mc[2:] + ".") if mc.startswith("1.") else (mc + ".")
    matches = [v for v in versions if v.startswith(prefix)]
    return list(reversed(matches))


def _latest_neoforge_version(mc: str) -> str:
    versions = list_neoforge_versions(mc)
    if not versions:
        raise RuntimeError(f"NeoForge 没有可用的 {mc} 版本")
    return versions[0]


def _fabric_profile(mc: str, loader: str) -> dict:
    """下载 Fabric 的版本 JSON"""
    resp = requests.get(FABRIC_PROFILE.format(mc=mc, loader=loader), timeout=20)
    resp.raise_for_status()
    return resp.json()


def _forge_profile(ver: str, dest_dir: str) -> dict:
    """下载 Forge installer jar,解压出 install_profile.json 里的版本 JSON。
    返回版本 JSON;installer jar 只下载一次,提取后删除。"""
    jar_path = os.path.join(dest_dir, "_forge_installer.jar")
    try:
        download_with_mirror(FORGE_INSTALLER.format(ver=ver), jar_path)
        with zipfile.ZipFile(jar_path) as z:
            profile = json.loads(z.read("install_profile.json"))
            json_path = profile["json"]
            if not isinstance(json_path, str):
                raise RuntimeError("Forge install_profile.json 里没有版本 JSON 路径")
            return json.loads(z.read(json_path.lstrip("/")))
    finally:
        if os.path.exists(jar_path):
            os.remove(jar_path)


def _installer_download(installer_url: str, ver: str, game_dir: str,
                        progress_callback=None) -> tuple:
    """下载 loader installer jar,返回 (版本JSON, 安装profile, installer路径, 临时目录)。

    Forge/NeoForge 的 installer 里有两个 JSON,各管一件事:
    - version.json           —— 版本 JSON(继承原版,给启动用)
    - install_profile.json   —— 安装配置(processors 补丁步骤,给安装用)"""
    tmp = os.path.join(game_dir, "versions", "_installer_tmp")
    os.makedirs(tmp, exist_ok=True)
    jar_path = os.path.join(tmp, f"installer-{ver}.jar")
    download_with_mirror(installer_url, jar_path, progress_callback=progress_callback)
    with zipfile.ZipFile(jar_path) as z:
        installer_profile = json.loads(z.read("install_profile.json"))
        # 版本 JSON 在 jar 里由 install_profile 的 json 字段指路
        json_path = installer_profile["json"]
        if not isinstance(json_path, str):
            raise RuntimeError("install_profile.json 里没有版本 JSON 路径")
        version_profile = json.loads(z.read(json_path.lstrip("/")))
        # 把补丁文件从 installer 里解出来
        binpatch = (installer_profile.get("data") or {}).get("BINPATCH", {}).get("client", "")
        if binpatch:
            with z.open(binpatch.lstrip("/")) as src, open(os.path.join(tmp, "client.lzma"), "wb") as dst:
                shutil.copyfileobj(src, dst)
    return version_profile, installer_profile, jar_path, tmp


def _forge_installer(ver: str, game_dir: str, progress_callback=None) -> tuple:
    return _installer_download(FORGE_INSTALLER.format(ver=ver), ver, game_dir,
                               progress_callback=progress_callback)


def _neoforge_installer(ver: str, game_dir: str, progress_callback=None) -> tuple:
    return _installer_download(NEOFORGE_INSTALLER.format(ver=ver), ver, game_dir,
                               progress_callback=progress_callback)


def _main_class(jar_path: str) -> str:
    """从 jar 的 manifest 里读 Main-Class"""
    with zipfile.ZipFile(jar_path) as z:
        manifest = z.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
    for line in manifest.splitlines():
        if line.startswith("Main-Class:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError(f"找不到 {os.path.basename(jar_path)} 的 Main-Class")


def _jar_is_bundler(jar_path: str) -> bool:
    """判断原版 jar 是不是 1.19+ 的 bundler 格式(manifiest 里有 Bundler-Format)。"""
    try:
        with zipfile.ZipFile(jar_path) as z:
            mf = z.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
            return "Bundler-Format" in mf
    except Exception:
        return False


def _coord_path(coord: str, lib_dir: str) -> str:
    """把 maven 坐标(如 [net.neoforged:neoform:1.21.1-20240808.144430:mappings@txt])
    解析成 libraries 下的真实路径。支持 classifier 和 @扩展名(默认 jar)。
    NeoForge 的 install_profile.data 里全是这种坐标。"""
    parts = coord.strip("[]'\"").split(":")
    if len(parts) < 3:
        return coord
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = parts[3] if len(parts) >= 4 else ""
    if "@" in version:
        version, ext = version.split("@", 1)
    else:
        ext = "jar"
    if "@" in classifier:
        classifier, ext = classifier.split("@", 1)
    name = f"{artifact}-{version}" + (f"-{classifier}" if classifier else "") + f".{ext}"
    return os.path.join(lib_dir, group.replace(".", "/"), artifact, version, name)


def _forge_run_processors(profile: dict, installer_jar: str, game_dir: str,
                          java_exe: str, maven_ver: str,
                          status_callback=None, progress_callback=None) -> None:
    """跑 installer 的 processors:把补丁打到原版 jar 上,生成 loader 的 client jar。

    Forge/NeoForge 的 client jar 不在任何仓库里,是安装器现场用 BINARYPATCH 打出来的。
    这正是官方安装器做的事;HMCL/PCL 也都是这么装的。

    注意:
    - BUNDLER_EXTRACT(解包)步骤只适用于 1.19+ 的 bundler 格式原版 jar,否则跳过
    - NeoForge 的 MCP_DATA 等任务会现场生成 mappings/slim/srg 等中间文件,
      data 段里的 maven 坐标就是它们的输出路径(自动解析 + 预建目录)"""
    lib_dir = os.path.join(game_dir, "libraries")
    tmp = os.path.dirname(installer_jar)
    mc = profile["minecraft"]

    tokens = {
        "INSTALLER": installer_jar,
        "ROOT": game_dir,
        "MINECRAFT_JAR": os.path.join(game_dir, "versions", mc, mc + ".jar"),
        "LIBRARY_DIR": lib_dir,
        "MC_VERSION": mc,
        "FORGE_VERSION": profile["version"],
        "SIDE": "client",
        "BINPATCH": os.path.join(tmp, "client.lzma"),
    }

    # 把 install_profile.data 里的坐标/字符串全部解析进 tokens(NeoForge 必需)
    for key, entry in (profile.get("data") or {}).items():
        if not isinstance(entry, dict):
            continue
        client = entry.get("client")
        if not isinstance(client, str):
            continue
        if client.startswith("["):
            path = _coord_path(client, lib_dir)
            os.makedirs(os.path.dirname(path), exist_ok=True)  # 输出路径的父目录
            tokens[key] = path
        elif client.startswith("'") and client.endswith("'"):
            tokens[key] = client.strip("'")
        else:
            tokens[key] = client

    # data.BINPATCH 是 installer 内部的路径(/data/client.lzma),不是磁盘路径——
    # 补丁文件我们已解压到 tmp,必须用它覆盖回去
    tokens["BINPATCH"] = os.path.join(tmp, "client.lzma")

    def coord_path(coord: str) -> str:
        return _coord_path(coord, lib_dir)

    def substitute(arg: str) -> str:
        arg = re.sub(r"\{([^}]+)\}", lambda m: tokens.get(m.group(1), m.group(0)), arg)
        arg = re.sub(r"\[([^\]]+)\]", lambda m: coord_path(m.group(1)), arg)
        return arg

    # 1) 下载安装器自己的工具库(installertools、binarypatcher 等)
    for lib in profile.get("libraries", []):
        art = (lib.get("downloads") or {}).get("artifact") or {}
        path = art.get("path") or _maven_path(lib.get("name", ""))
        if not path:
            continue
        dest = os.path.join(lib_dir, path)
        if os.path.exists(dest):
            continue
        url = art.get("url")
        if url:
            download_with_mirror(url, dest, sha1=art.get("sha1"), progress_callback=progress_callback)
        else:
            _download_maven_path(path, dest, progress_callback)

    # 2) 过滤 + 逐个跑处理器
    is_bundler = _jar_is_bundler(tokens["MINECRAFT_JAR"])
    processors = []
    for proc in profile.get("processors", []):
        args_str = " ".join(str(a) for a in proc.get("args", []))
        if not is_bundler and ("BUNDLER_EXTRACT" in args_str or "{MC_UNPACKED}" in args_str):
            continue  # 非 bundler 格式:跳过解包步骤,只留直接打补丁的那步
        processors.append(proc)

    for i, proc in enumerate(processors):
        if status_callback:
            status_callback(f"Forge 补丁步骤 {i + 1}/{len(processors)}...")
        jar_path = coord_path(proc["jar"])
        main = _main_class(jar_path)
        cp = os.pathsep.join([jar_path] + [coord_path(c) for c in proc.get("classpath", [])])
        args = [substitute(a) for a in proc.get("args", [])]
        cmd = [java_exe, "-cp", cp, main] + args
        # errors="replace":Java 处理器在中文 Windows 下输出 GBK,UTF-8 严格解码会崩
        # CREATE_NO_WINDOW:补丁步骤跑 java 时不弹控制台黑框
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(cmd, cwd=game_dir, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=900,
                                creationflags=creationflags)
        if result.returncode != 0:
            tail = (result.stdout or "")[-400:] + (result.stderr or "")[-400:]
            raise RuntimeError(f"Forge 补丁步骤 {i + 1} 失败:\n{tail}")
        # 每跑完一个处理器报一次进度,让进度条在"打补丁"阶段也动(而不是卡着)
        if progress_callback:
            progress_callback(i + 1, len(processors))


def _download_maven_path(path: str, dest: str, progress_callback=None) -> None:
    """下载一个只有 Maven 路径的库(轮流试几个仓库)"""
    from downloader import download_maven
    download_maven(path, dest, progress_callback=progress_callback)


def install_loader(loader: str, mc: str, game_dir: str,
                   loader_version: str | None = None,
                   progress_callback=None, status_callback=None) -> str:
    """给原版 mc 安装加载器(loader: fabric / forge),返回安装后的版本 ID。

    loader_version 不传 → 自动选最新;传了 → 用指定版本(高级选项)。

    步骤:
    1. 查最新加载器版本,拿加载器的版本 JSON(继承原版)
    2. 确保原版 JSON + 客户端 jar 在磁盘上(继承链的根 + 补丁的原料)
    3. (forge) 跑安装器的补丁步骤,生成 forge client jar
    4. 保存加载器版本 JSON 到它的实例目录,拷贝原版 jar
    5. 按合并后的完整数据下载加载器新增的依赖库
    """
    if status_callback:
        status_callback(f"正在查询 {loader} 最新版本...")

    forge_installer = None
    forge_tmp = None
    try:
        if loader == "fabric":
            loader_ver = loader_version or _latest_fabric_loader(mc)
            profile = _fabric_profile(mc, loader_ver)
        elif loader == "forge":
            loader_ver = loader_version or _latest_forge_version(mc)
            # Forge 的 maven 版本号是 "mc-forge版本"(如 1.20.1-47.4.0);
            # CurseForge/Modrinth 常给裸 forge 版本(如 47.4.0),直接拼 URL 会 404,这里归一化。
            if loader_ver and mc and not loader_ver.startswith(mc + "-"):
                loader_ver = f"{mc}-{loader_ver}"
            if status_callback:
                status_callback(f"安装加载器 forge {loader_ver}...")
            profile, installer_profile, forge_installer, forge_tmp = _forge_installer(
                loader_ver, game_dir, progress_callback)
        elif loader == "neoforge":
            loader_ver = loader_version or _latest_neoforge_version(mc)
            profile, installer_profile, forge_installer, forge_tmp = _neoforge_installer(
                loader_ver, game_dir, progress_callback)
        else:
            raise ValueError(f"不支持的加载器:{loader}")

        version_id = profile.get("id") or f"{mc}-{loader}-{loader_ver}"
        parent_id = profile.get("inheritsFrom")
        if not parent_id:
            raise RuntimeError(f"{loader} 版本 JSON 缺少 inheritsFrom:{version_id}")

        if status_callback:
            status_callback(f"准备安装 {version_id} ...")

        # 2) 继承链的根(原版 JSON + 客户端 jar)必须在磁盘上
        #    基础原版收进 versions/_versions/ 版本仓库,versions 目录只留真实例
        base_dir = os.path.join(game_dir, "versions", "_versions", parent_id)
        base_path = os.path.join(base_dir, parent_id + ".json")
        base_jar = os.path.join(base_dir, parent_id + ".jar")
        # 优先复用:用户已装的原版实例(versions/<id>/)或仓库里已有的
        alt_json = os.path.join(game_dir, "versions", parent_id, parent_id + ".json")
        if not os.path.exists(base_path) and os.path.exists(alt_json):
            base_path = alt_json
            base_jar = os.path.join(game_dir, "versions", parent_id, parent_id + ".jar")
        if not os.path.exists(base_path):
            from fetch_versions import fetch_version_detail, fetch_version_manifest
            manifest = fetch_version_manifest()
            entry = next((v for v in manifest["versions"]
                          if v["id"] == parent_id and v["type"] == "release"), None)
            if entry is None:
                raise RuntimeError(f"清单里找不到原版 {parent_id}")
            base = fetch_version_detail(entry["url"])
            os.makedirs(os.path.dirname(base_path), exist_ok=True)
            with open(base_path, "w", encoding="utf-8") as f:
                json.dump(base, f, ensure_ascii=False, indent=2)
        else:
            with open(base_path, encoding="utf-8") as f:
                base = json.load(f)
        if not os.path.exists(base_jar):
            client = (base.get("downloads") or {}).get("client")
            if client:
                if status_callback:
                    status_callback(f"下载原版 {parent_id} 客户端...")
                download_with_mirror(client["url"], base_jar, version_id=parent_id,
                                     sha1=client.get("sha1"), progress_callback=progress_callback)

        # 3) (forge/neoforge) 跑补丁步骤,生成 loader 的 client jar
        if loader in ("forge", "neoforge"):
            java_exe = os.environ.get("FORGE_PROCESSOR_JAVA")
            if not java_exe:
                from java_manager import ensure_java
                java_exe = ensure_java(os.path.join(game_dir, "runtime"), 17,
                                       progress_callback=progress_callback,
                                       status_callback=status_callback)
            _forge_run_processors(installer_profile, forge_installer, game_dir, java_exe,
                                  maven_ver=loader_ver, status_callback=status_callback,
                                  progress_callback=progress_callback)

        # 4) 保存加载器版本 JSON + 拷贝原版 jar 到实例目录
        inst_dir = os.path.join(game_dir, "versions", version_id)
        os.makedirs(inst_dir, exist_ok=True)
        with open(os.path.join(inst_dir, version_id + ".json"), "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        inst_jar = os.path.join(inst_dir, version_id + ".jar")
        if os.path.exists(base_jar) and not os.path.exists(inst_jar):
            shutil.copyfile(base_jar, inst_jar)

        # 5) 下载加载器新增的依赖库(合并后的完整数据;已存在的自动跳过)
        merged = resolve_inherited_json(version_id, game_dir)
        if status_callback:
            status_callback(f"下载 {version_id} 的依赖库...")
        _n, failures = install_version_files(merged, game_dir,
                                             progress_callback=progress_callback,
                                             status_callback=status_callback)
        if failures:
            raise RuntimeError(f"{len(failures)} 个依赖库下载失败,如 {failures[0][0]}")

        return version_id
    finally:
        # 清理 Forge 临时目录(installer jar、补丁文件)
        if forge_tmp and os.path.isdir(forge_tmp):
            shutil.rmtree(forge_tmp, ignore_errors=True)
