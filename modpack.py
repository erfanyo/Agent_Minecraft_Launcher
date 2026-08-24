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
import concurrent.futures
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
    """按整合包依赖安装加载器,返回实例的基础(loader 版本 id 或 None)。
    支持 Modrinth 清单里的 fabric-loader / forge / neoforge(quilt-loader 视为 fabric)。"""
    loader = None
    ver = None
    if deps.get("fabric-loader"):
        loader, ver = "fabric", deps["fabric-loader"]
    elif deps.get("neoforge"):
        loader, ver = "neoforge", deps["neoforge"]
    elif deps.get("forge"):
        loader, ver = "forge", deps["forge"]
    elif deps.get("quilt-loader"):
        loader, ver = "fabric", deps["quilt-loader"]
    if loader is None:
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


def _extract_zip_to(path: str, inst_dir: str, prefix: str,
                    status_callback=None, progress_callback=None):
    """把 zip 内容解压进实例目录(去掉 prefix);跳过目录项与路径穿越。
    prefix 非空时只解压该前缀下的成员(如 overrides/),其余(manifest.json 等)忽略。
    progress_callback(done, total):每解压一个文件上报一次,进度进下载指示器/详情。"""
    with zipfile.ZipFile(path) as z:
        members = [m for m in z.namelist() if m and not m.endswith("/")
                   and (not prefix or m.startswith(prefix))]
        total = len(members)
        for i, member in enumerate(members, 1):
            if prefix:
                rel = member[len(prefix):]
            else:
                rel = member
            if not rel or rel.startswith(("../", "/")) or ".." in rel.split("/"):
                continue
            dest = os.path.join(inst_dir, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(member) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if progress_callback:
                progress_callback(i, total)


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


def suggested_instance_id(path: str) -> str:
    """按格式给出默认实例 id(名字来自 manifest/包名;识别失败用文件名)。供导入前预检同名。"""
    try:
        fmt = detect_modpack_format(path)
        with zipfile.ZipFile(path) as z:
            if fmt == "modrinth":
                idx = json.loads(z.read("modrinth.index.json"))
                name = idx.get("name")
            elif fmt == "curseforge":
                mf = json.loads(z.read("manifest.json"))
                name = mf.get("name")
            else:
                name = None
            if name:
                return _safe_name(name)
    except Exception:
        pass
    return _safe_name(os.path.splitext(os.path.basename(path))[0])


def _tuck_framework_version(version_id: str, game_dir: str) -> None:
    """把导入时不再被引用的"加载器框架版本"移进 versions/_versions/ 版本仓库。

    导入整合包时,install_loader 会先生成一个加载器版本目录(如 neoforge-21.1.233),
    随后它的 json/jar 被复制成整合包实例本身(整合包 json 改写为包名 id)。
    这样原加载器版本目录就成了"没存档、没 mod、也没人引用"的空白框架 —— 它会被
    scan_instances 当做一个独立实例漏出来(表现为"文件目录里多了一个空白实例")。
    移进 _versions 仓库后,实例列表与磁盘目录都干净,也不影响继承链解析
    (整合包 json 的 inheritsFrom 指向的是基础原版,不是这个框架版本)。"""
    src = os.path.join(game_dir, "versions", version_id)
    repo = os.path.join(game_dir, "versions", "_versions")
    dest = os.path.join(repo, version_id)
    if not os.path.isdir(src):
        return
    try:
        os.makedirs(repo, exist_ok=True)
        if os.path.isdir(dest):
            # 仓库已有同名框架版本(罕见:又导入了同加载器的包)→ 删掉这份冗余
            shutil.rmtree(src, ignore_errors=True)
        else:
            shutil.move(src, dest)
    except OSError:
        pass


def heal_instance_json(instance_id: str, game_dir: str) -> bool:
    """自愈:若实例 json 的 id 与目录名不一致,把 id 改写为目录名。

    旧版本导入的整合包,版本 json 是从加载器版本复制来的,其 id 仍是加载器
    (如 neoforge-21.1.233),启动时 game_dir_for(d["id"]) 会解析到加载器的空白
    目录 → 白板启动、mod 全不加载。发现不一致就改写为实例目录名,让启动落到
    本实例自己的游戏目录。返回是否改过。

    ⚠️ 只在该实例"自包含"(自己的目录下有 <实例名>.jar)时才改写:改写后
    build_launch_command 会用 d["id"] 拼客户端 jar 路径(versions/<id>/<id>.jar)。
    导入的整合包会复制自己的 jar 到 <实例名>.jar,改写安全;而"改了目录名但 jar
    仍是旧 id"的实例没有 <实例名>.jar,改了反而指向不存在的 jar —— 不写。
    """
    try:
        inst_dir = os.path.join(game_dir, "versions", instance_id)
        path = os.path.join(inst_dir, instance_id + ".json")
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
        if j.get("id") == instance_id:
            return False
        if not os.path.isfile(os.path.join(inst_dir, instance_id + ".jar")):
            return False   # 目录下没有对应的 <实例名>.jar:不自包含,不该改 id
        j["id"] = instance_id
        with open(path, "w", encoding="utf-8") as f:
            json.dump(j, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# 并行下载整合包 mod 文件的工作线程数(单个文件失败不中断其它)
_MOD_DL_WORKERS = 6


def _download_mods_parallel(files: list, inst_dir: str,
                            status_callback=None, progress_callback=None) -> None:
    """并行下载整合包清单里的文件(Modrinth .mrpack)。逐个文件会慢,这里 6 线程并行。

    - 每个文件一个任务(下载+sha1 校验);单个失败只提示跳过,不中断整体。
    - progress_callback(done, total)= 按【文件数】的完成进度(每下完一个报一次),直接驱动下载指示器。
    - status_callback 报"整合包文件 x/N:文件名",让用户看得到在下哪个。
    """
    jobs = []
    for f in files:
        rel = f.get("path", "")
        if not rel or rel.startswith("../"):
            continue
        dest = os.path.join(inst_dir, rel.replace("/", os.sep))
        downloads = f.get("downloads") or []
        if not downloads or os.path.exists(dest):
            continue
        jobs.append((f, rel, downloads[0], dest, (f.get("hashes") or {}).get("sha1")))
    if not jobs:
        return
    total = len(jobs)

    def one(job):
        _f, _rel, url, dest, sha1 = job
        try:
            download_with_mirror(url, dest, sha1=sha1)
            return True, os.path.basename(_rel)
        except Exception as e:
            return False, f"{os.path.basename(_rel)} {e}"

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=_MOD_DL_WORKERS) as ex:
        futs = {ex.submit(one, j): j for j in jobs}
        for fut in concurrent.futures.as_completed(futs):
            ok, msg = fut.result()
            done += 1
            if status_callback:
                status_callback(("✅ " if ok else "⚠️ ") + f"整合包文件 {done}/{total}:{msg}")
            if progress_callback:
                progress_callback(done, total)


def import_modpack(path: str, game_dir: str,
                   mc_version: str | None = None,
                   loader: str | None = None,
                   loader_version: str | None = None,
                   instance_id: str | None = None,
                   status_callback=None, progress_callback=None) -> str:
    """导入整合包(自动识别格式),返回实例 ID。

    - Modrinth .mrpack:mc/加载器从清单读(无需参数)。
    - CurseForge .zip:mc/加载器从 manifest 读(无需参数);只装基础+加载器+解压 overrides,
      清单里的文件列表需 CurseForge API(跳过),会附加提示。
    - 扁平 .zip(实例文件夹):需 mc_version(否则报错);可选 loader/loader_version;
      直接把 zip 内容解压成新实例。
    - instance_id:指定实例 ID(默认按包名生成);已存在且未指定 → 抛错,让调用方改用自定义名。
    - 若包声明了加载器(CurseForge/Modrinth/用户指定)但安装失败 → 抛错回滚,不静默生成"原版半成品"。
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
    instance_id = instance_id or _safe_name(name)
    inst_dir = os.path.join(game_dir, "versions", instance_id)
    if os.path.exists(inst_dir):
        raise ValueError(f"已存在同名实例:{instance_id}(可在导入时自定义实例名)")
    # 一开始就创建实例目录:让用户立刻看到(下载/解压都在里面进行;导入失败会回滚删除,不留半成品)
    os.makedirs(inst_dir, exist_ok=True)
    if status_callback:
        status_callback(f"开始导入整合包:{name}(mc {mc})...")

    try:
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
                # 包需要这个加载器(CurseForge/Modrinth 声明,或用户手动选了非原版)却装不上
                # → 不能静默生成一个"原版半成品"(否则 mods 跑不了,基础版本也不会被收进 _versions)。
                msg = f"加载器 {loader} 安装失败,已取消导入:{e}"
                if status_callback:
                    status_callback(msg)
                raise RuntimeError(msg) from e

        # 3) 放好版本 JSON 和客户端 jar
        src_id = base_instance or mc
        src_json = os.path.join(game_dir, "versions", src_id, src_id + ".json")
        src_jar = os.path.join(game_dir, "versions", src_id, src_id + ".jar")
        if os.path.exists(src_json):
            dst_json = os.path.join(inst_dir, instance_id + ".json")
            shutil.copyfile(src_json, dst_json)
            # 复制自加载器版本(json 的 id 仍是加载器,如 neoforge-21.1.233)。
            # 不改会让启动把游戏目录解析到源版本(空白实例),mod 全都不加载
            # (启动时 game_dir_for(d["id"]) 指向的是加载器目录,不是本整合包目录)。
            # → 强制把 id 改写成本整合包实例 id。
            try:
                with open(dst_json, encoding="utf-8") as f:
                    jd = json.load(f)
                jd["id"] = instance_id
                with open(dst_json, "w", encoding="utf-8") as f:
                    json.dump(jd, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        if os.path.exists(src_jar):
            shutil.copyfile(src_jar, os.path.join(inst_dir, instance_id + ".jar"))

        # 4) 按格式放内容
        if index is not None:
            # Modrinth:并行下载清单里的文件(6 线程,逐文件报进度)
            _download_mods_parallel(index.get("files", []), inst_dir, status_callback, progress_callback)

        # Modrinth + CurseForge 都解压 overrides / client-overrides(直接覆盖进实例的文件)
        if index is not None or cf:
            _extract_zip_to(path, inst_dir, "overrides/", status_callback, progress_callback)
            _extract_zip_to(path, inst_dir, "client-overrides/", status_callback, progress_callback)

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
            _extract_zip_to(path, inst_dir, prefix or "", status_callback, progress_callback)

        # 收好导入时不再被引用的加载器框架版本(非原版本体的加载器目录),
        # 避免它在实例列表里变成"多出来的空白实例"。
        if base_instance and base_instance != mc:
            _tuck_framework_version(base_instance, game_dir)

        return instance_id
    except Exception as e:
        # 导入失败:回滚删掉本次新建的实例目录(不留原版半成品)
        try:
            shutil.rmtree(inst_dir, ignore_errors=True)
        except Exception:
            pass
        raise
