# -*- coding: utf-8 -*-
"""
版本文件安装:按版本 JSON 的"清单"下载全部所需文件。

版本 JSON(d)里已经写好了需要哪些文件:
- libraries   —— 依赖库(每个可能带系统规则,比如只给 Windows 用)
- assetIndex  —— 资源文件索引(先下索引,再从索引里读出几百个资源文件逐个下载)

新学的思路:清单驱动下载 —— 把"要下载什么"整理成一张任务清单,
再统一执行。以后加 Mod、加整合包都是这个套路。
"""
import json
import os
import platform
import sys

from downloader import download_many, download_maven, download_with_mirror

# 当前操作系统名(用于 libraries 的系统规则判断)
OS_NAME = (
    "windows" if sys.platform.startswith("win")
    else "osx" if sys.platform == "darwin"
    else "linux"
)

ARCH = platform.machine().lower().replace("amd64", "x86_64")

# 资源文件的下载地址模板:Minecraft 资源按 hash 的前两位分文件夹存放。
# 做成常量有两个好处:一眼看懂规则;测试时可以替换成本地服务器。
RESOURCE_URL = "https://resources.download.minecraft.net/{hash2}/{hash}"

# 版本 JSON 的"规则"里,除了 os(系统)条件,还有 features(功能开关)条件。
# 我们暂不支持演示模式/自定义分辨率/快速开始,所以这些开关全部关闭。
DEFAULT_FEATURES = {
    "is_demo_user": False,
    "has_custom_resolution": False,
    "has_quick_plays_support": False,
    "is_quick_play_singleplayer": False,
    "is_quick_play_multiplayer": False,
    "is_quick_play_realms": False,
    "is_quick_play_path": False,
}


def rule_matches(rule: dict, features: dict) -> bool:
    """一条规则是否"命中":os 条件全部满足 且 features 条件全部满足。"""
    os_cond = rule.get("os")
    if os_cond:
        if "name" in os_cond and os_cond["name"] != OS_NAME:
            return False
        if "arch" in os_cond and os_cond["arch"] != ARCH:
            return False
    feat_cond = rule.get("features")
    if feat_cond:
        for key, value in feat_cond.items():
            if features.get(key) != value:
                return False
    return True


def rules_allow(rules: list | None, features: dict | None = None) -> bool:
    """判断一组规则是否放行。
    没有规则 → 放行;有规则 → 逐条判断,最后一条"命中"的规则说了算。"""
    if not rules:
        return True
    if features is None:
        features = DEFAULT_FEATURES
    allowed = False
    for rule in rules:
        if rule_matches(rule, features):
            allowed = rule.get("action") == "allow"
    return allowed


def _maven_path(name: str) -> str:
    """把 Maven 坐标 group:artifact:version[:classifier] 转成仓库相对路径。
    例:"net.fabricmc:fabric-loader:0.19.3" →
        "net/fabricmc/fabric-loader/0.19.3/fabric-loader-0.19.3.jar"
      带分类器(如 Forge 的 :client):文件名变成 artifact-version-classifier.jar
    """
    parts = name.split(":")
    if len(parts) < 3:
        return ""
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = f"-{parts[3]}" if len(parts) >= 4 else ""
    return f"{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}{classifier}.jar"


def library_entries(d: dict) -> list:
    """当前系统需要下载/加载的依赖库文件:[(相对路径, url或None, sha1, 大小), ...]
    安装文件(game_files)和拼启动命令(launcher)都用这一份清单,避免逻辑写两遍。

    注意:部分加载器(Fabric/Forge)的版本 JSON 里 libraries 没有下载地址,
    url 记为 None,下载时按 Maven 路径轮流试几个仓库(download_maven)。
    """
    entries = []
    for lib in d.get("libraries", []):
        if not rules_allow(lib.get("rules")):
            continue  # 当前系统用不上的库,不下载
        dl = lib.get("downloads", {})

        artifact = dl.get("artifact")
        if artifact and artifact.get("path"):
            url = artifact.get("url") or None  # url 可能为空串 → 交给 maven 轮询
            entries.append((artifact["path"], url, artifact.get("sha1"),
                            artifact.get("size", 0)))
        elif "name" in lib:
            # 没有下载地址的库:按 Maven 坐标拼路径
            path = _maven_path(lib["name"])
            if path:
                entries.append((path, None, None, 0))

        # 原生库(natives):旧版本用 natives 字段,新版本用 classifiers 字段
        classifiers = dl.get("classifiers", {})
        natives = lib.get("natives", {})
        key = natives.get(OS_NAME) or f"natives-{OS_NAME}"
        if key in classifiers:
            c = classifiers[key]
            url = c.get("url") or f"https://libraries.minecraft.net/{c['path']}"
            entries.append((c["path"], url, c.get("sha1"), c.get("size", 0)))

    return entries


def _collect_tasks(d: dict, game_dir: str) -> list:
    """把"要下载的依赖库"整理成任务清单(资源对象另在 install 里整理)。
    任务 = (url, 保存路径, sha1, 大小)。依赖库统一放在 game_dir/libraries 下。"""
    return [(url, os.path.join(game_dir, "libraries", path), sha1, size)
            for path, url, sha1, size in library_entries(d)]


def _need_download(task: tuple) -> bool:
    """文件已存在且(已知大小下)大小一致 → 跳过。
    资源文件是只读的,存在即认为没问题;大小未知的文件存在也跳过。"""
    _, dest, _, size = task
    if os.path.exists(dest):
        if size and os.path.getsize(dest) != size:
            return True  # 大小不对 = 文件坏了/没下完,重下
        return False
    return True


def install_version_files(d: dict, game_dir: str,
                          progress_callback=None, status_callback=None) -> tuple:
    """按版本 JSON(d)下载全部文件到 game_dir。

    - progress_callback(done, total):整体字节进度
    - status_callback(text):阶段说明(如"正在下载依赖库...")
    返回 (成功下载数, 失败列表)。单个文件失败不会中断整体——
    失败会记进列表,装完提示用户重试补齐(重跑会自动跳过已存在的)。

    顺序很重要:
    1) 先下资源索引(资源对象的清单就藏在索引里)
    2) 读完索引,才能整理出"资源对象"的下载任务
    3) 依赖库 + 资源对象一起按清单下载
    """
    ai = d.get("assetIndex") or {}
    idx_dest = (os.path.join(game_dir, "assets", "indexes", ai["id"] + ".json")
                if ai.get("id") else None)
    idx_task = ((ai["url"], idx_dest, ai.get("sha1"), ai.get("size", 0))
                if ai.get("url") and idx_dest else None)

    downloaded = 0
    failures = []

    # 1) 资源索引(必须先下,后面的清单从它里面读)
    if idx_task and _need_download(idx_task):
        if status_callback:
            status_callback("下载资源索引...")
        try:
            # 注意:不能 *idx_task 展开传参——位置会对错(sha1 会跑到 version_id 上)
            download_with_mirror(idx_task[0], idx_task[1], sha1=idx_task[2],
                                 progress_callback=progress_callback)
            downloaded += 1
        except Exception as e:
            failures.append((os.path.basename(idx_task[1]), str(e)[:80]))

    # 2) 整理完整任务清单:依赖库 + 资源对象(索引此时已在磁盘上)
    tasks = _collect_tasks(d, game_dir)
    if idx_dest and os.path.exists(idx_dest):
        with open(idx_dest, encoding="utf-8") as f:
            index = json.load(f)
        for name, obj in (index.get("objects") or {}).items():
            h = obj["hash"]
            tasks.append((
                RESOURCE_URL.format(hash2=h[:2], hash=h),
                os.path.join(game_dir, "assets", "objects", h[:2], h),
                h, obj.get("size", 0),
            ))

    tasks = [t for t in tasks if _need_download(t)]
    if not tasks:
        if status_callback:
            status_callback("所有文件已存在,无需下载")
        return downloaded, failures

    if status_callback:
        status_callback(f"并行下载依赖库与资源文件(共 {len(tasks)} 个)...")

    # 并行下载:文件间无依赖,4 线程同时下,进度按总字节聚合
    jobs = []
    for url, dest, sha1, size in tasks:
        name = os.path.basename(dest)
        if url:
            jobs.append((name, size, lambda cb, u=url, de=dest, s=sha1:
                         download_with_mirror(u, de, sha1=s, progress_callback=cb)))
        else:
            # 没有地址的库:从 dest 还原 Maven 相对路径,轮流试仓库
            rel = dest.replace("\\", "/")
            path = rel.split("/libraries/", 1)[1]
            jobs.append((name, size, lambda cb, p=path, de=dest, s=sha1:
                         download_maven(p, de, sha1=s, progress_callback=cb)))
    d2, failures = download_many(jobs, progress_callback=progress_callback)
    downloaded += d2

    if failures and status_callback:
        status_callback(f"{len(failures)} 个文件下载失败(重跑安装会自动补齐)")
    return downloaded, failures
