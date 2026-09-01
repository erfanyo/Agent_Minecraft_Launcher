# -*- coding: utf-8 -*-
"""
下载工具:带进度回调 + sha1 完整性校验的文件下载。

sha1 是文件的"指纹"。Mojang 数据里会给每个文件标好期望的 sha1,
下载完比对指纹:不一致就说明文件坏了(或被人动过手脚),删除并报错。
这是"下载"这件事的安全底线,以后下载 libraries、资源文件都会复用这个函数。
"""
import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import requests

CHUNK_SIZE = 1024 * 256  # 每次读写 256KB
PARALLEL_WORKERS = 4     # 并行下载线程数(网络下载瓶颈在延迟,4 个足够且不触发限流)


def sha1_of_file(path: str) -> str:
    """计算一个文件的 sha1 指纹"""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest: str, sha1: str | None = None,
                  progress_callback=None, timeout=30) -> None:
    """把 url 下载到 dest。

    参数:
      url    —— 文件地址
      dest   —— 保存路径(自动创建上级目录)
      sha1   —— 期望的指纹;给出则下载后校验,不一致删除并报错
      progress_callback(done, total) —— 进度回调,total 为 0 表示总量未知
      timeout —— 超时(秒);可传 (连接超时, 读超时) 元组,用于"官方源缓慢就换源"
    """
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        resp = requests.get(url, stream=True, timeout=timeout)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        done = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                f.write(chunk)
                done += len(chunk)
                if progress_callback:
                    progress_callback(done, total)
    except Exception:
        # 下载中断/失败:删掉半截文件,避免下次被"文件已存在"骗过
        if os.path.exists(dest):
            try:
                os.remove(dest)
            except OSError:
                pass
        raise

    if sha1 and sha1_of_file(dest) != sha1:
        os.remove(dest)
        raise ValueError(f"sha1 校验失败:{os.path.basename(dest)} 文件可能损坏或被篡改")


# ---------------------------------------------------------------------------
# 镜像站:预设 + 自定义(自定义镜像存 config.json 的 custom_mirrors,见 settings.py)。
# 换源统一规则:把官方地址按路径映射到镜像站的 libraries/ assets/ version/ 等目录,
# 自定义镜像与 BMCLAPI 同构,填入 base 地址即可。
# 注意:这里只登记"镜像站","要不要用官方"由下载策略 MIRROR_STRATEGIES 决定。
# ---------------------------------------------------------------------------
MIRROR_SOURCES = {
    "bmclapi": {
        "name": "BMCLAPI(推荐,国内加速)",
        "base": "https://bmclapi2.bangbang93.com",
        "desc": "国内社区维护的老牌镜像站,内容与官方一致,下载速度快",
    },
}

# 下载策略:决定"官方源"和"镜像站"谁先用、谁兜底、用不用
MIRROR_STRATEGIES = {
    "smart_official": {
        "name": "官方优先(官方慢或失败时换镜像)",
        "desc": "先直连 Mojang 官方;官方连不上或太慢时,自动改用你选的镜像站。",
    },
    "mirror_first": {
        "name": "镜像优先(镜像失败才回官方)",
        "desc": "先用你选的镜像站(国内通常更快);镜像失败才回 Mojang 官方。",
    },
    "official_only": {
        "name": "只用官方源",
        "desc": "完全不使用镜像站,只从 Mojang 官方下载(慢也要等)。",
    },
    "mirror_only": {
        "name": "只用镜像源",
        "desc": "只用你选的镜像站,失败也不回官方。",
    },
}


def _active_mirror() -> str:
    """当前设置里选中的镜像站 key(每次读 config.json,改设置立即生效)"""
    try:
        from settings import load_settings
        return load_settings().get("mirror_source", "bmclapi") or "bmclapi"
    except Exception:
        return "bmclapi"


def _active_strategy() -> str:
    """当前设置里的下载策略 key(见 MIRROR_STRATEGIES)"""
    try:
        from settings import load_settings
        return load_settings().get("mirror_strategy", "smart_official") or "smart_official"
    except Exception:
        return "smart_official"


def _mirror_base(mirror: str | None) -> str:
    """镜像站 key → base 地址;未知 key 返回空串(表示没有可用镜像)"""
    key = mirror or _active_mirror()
    info = MIRROR_SOURCES.get(key)
    if info:
        return info.get("base", "")
    if key.startswith("custom:"):
        cid = key.split(":", 1)[1]
        try:
            from settings import load_settings
            customs = load_settings().get("custom_mirrors", []) or []
        except Exception:
            customs = []
        for cm in customs:
            if cm.get("id") == cid:
                return (cm.get("url") or "").rstrip("/")
    return ""


def mirror_url(url: str, version_id: str | None = None, mirror: str | None = None) -> str:
    """把 Mojang 官方下载地址换成当前镜像源地址;换不了就原样返回。"""
    base = _mirror_base(mirror)
    if not base:
        return url
    if "libraries.minecraft.net" in url:
        return base + "/libraries/" + url.split("libraries.minecraft.net/")[-1]
    if "launcher.mojang.com/maven" in url:
        return base + "/maven/" + url.split("/maven/")[-1]
    if "resources.download.minecraft.net" in url:
        # 资源文件按 hash 存放:.../<前两位>/<完整hash>
        return base + "/assets/" + url.rstrip("/").rsplit("/", 1)[-1]
    if version_id and ("piston-data.mojang.com" in url or "launcher.mojang.com" in url):
        # 客户端/服务器 jar:镜像站按版本号提供
        if "client" in url:
            return f"{base}/version/{version_id}/client"
        if "server" in url:
            return f"{base}/version/{version_id}/server"
    return url


def mirror_manifest_url(mirror: str | None = None) -> str | None:
    """当前镜像站的版本清单地址(没有可用镜像时返回 None = 用官方地址)"""
    base = _mirror_base(mirror)
    if not base:
        return None
    return base + "/mc/game/version_manifest_v2.json"


def mirror_version_json_url(url: str, mirror: str | None = None) -> str:
    """把版本详情 JSON 的官方地址换成镜像地址(镜像站按版本 id 提供 /version/<id>/json)"""
    base = _mirror_base(mirror)
    if not base:
        return url
    if ("piston-meta.mojang.com" in url or "launchermeta.mojang.com" in url
            or "launcher.mojang.com" in url):
        vid = url.rstrip("/").rsplit("/", 1)[-1]
        if vid.endswith(".json"):
            vid = vid[:-5]
        return f"{base}/version/{vid}/json"
    return url


def _candidate_urls(url: str, version_id: str | None = None,
                    mirror: str | None = None, strategy: str | None = None) -> list:
    """按下载策略生成候选地址(去重),只含官方地址与所选镜像地址两个候选:
    smart_official  → 官方优先,镜像兜底
    mirror_first    → 镜像优先,官方兜底
    official_only   → 只有官方
    mirror_only     → 只有镜像
    """
    strat = strategy or _active_strategy()
    m = mirror_url(url, version_id, mirror)
    official = url
    if strat == "official_only":
        return [official]
    if strat == "mirror_only":
        return [m] if m != official else [official]
    if strat == "mirror_first":
        return list(dict.fromkeys([m, official]))
    return list(dict.fromkeys([official, m]))   # smart_official


def _is_mojang_url(url: str) -> bool:
    """判断是不是 Mojang 官方地址(只有官方地址才参与"官方慢就换镜像"的策略)"""
    hosts = ("libraries.minecraft.net", "launcher.mojang.com", "launchermeta.mojang.com",
             "piston-meta.mojang.com", "piston-data.mojang.com",
             "resources.download.minecraft.net")
    return any(h in url for h in hosts)


def download_with_mirror(url: str, dest: str, version_id: str | None = None,
                         sha1: str | None = None,
                         progress_callback=None, mirror: str | None = None,
                         strategy: str | None = None) -> None:
    """统一下载入口:按当前下载策略依次尝试候选地址(首个地址试 2 次,网络偶尔抖动),
    全失败就把最后一个错误抛出去。

    "官方优先"策略下,官方源用短超时(6 秒连不上 / 10 秒没有数据就算"慢"),
    快速切到镜像,实现"官方源缓慢时改用镜像源";兜底候选用完整 30 秒超时。
    短超时只对 Mojang 官方地址生效,其他来源(Modrinth 等)不受影响。"""
    strat = strategy or _active_strategy()
    last_err = None
    for i, u in enumerate(_candidate_urls(url, version_id, mirror, strat)):
        attempts = 2 if i == 0 else 1
        for _ in range(attempts):
            try:
                if strat == "smart_official" and i == 0 and u == url and _is_mojang_url(url):
                    # 官方源"缓慢检测":短连接/读超时,慢就抛错换镜像
                    download_file(u, dest, sha1=sha1, progress_callback=progress_callback,
                                  timeout=(6, 10))
                else:
                    download_file(u, dest, sha1=sha1, progress_callback=progress_callback)
                return
            except Exception as e:
                last_err = e
    raise last_err


# 依赖库没有下载地址时,按 Maven 路径轮流试这几个仓库
MAVEN_REPOS = [
    "https://maven.fabricmc.net/{path}",
    "https://maven.minecraftforge.net/{path}",
    "https://maven.neoforged.net/releases/{path}",
    "https://libraries.minecraft.net/{path}",
]


def download_maven(path: str, dest: str, sha1: str | None = None,
                   progress_callback=None, mirror: str | None = None,
                   strategy: str | None = None) -> None:
    """下载一个只有 Maven 坐标(路径)、没有明确地址的依赖库。
    按下载策略安排镜像 Maven 仓库的位置(镜像站一般也镜像了 Maven 仓库)。"""
    strat = strategy or _active_strategy()
    base = _mirror_base(mirror)
    mirror_repo = (base + "/maven/{path}") if base else None
    repos = list(MAVEN_REPOS)
    if strat == "official_only":
        pass                        # 只用官方仓库,顺序不变
    elif strat == "mirror_only":
        repos = [mirror_repo] if mirror_repo else []
    elif strat == "mirror_first":
        if mirror_repo:
            repos = [mirror_repo] + repos
    else:                           # smart_official:官方仓库优先,镜像兜底
        if mirror_repo:
            repos = repos + [mirror_repo]
    last_err = None
    errors = []
    for template in repos:
        url = template.format(path=path)
        try:
            download_file(url, dest, sha1=sha1, progress_callback=progress_callback)
            return
        except Exception as e:
            last_err = e
            # 不能只抛出最后一个镜像错误：那会掩盖官方仓库究竟是不存在、
            # 超时还是被网络拦截，用户也无法据此判断是否该换源。
            detail = str(e).replace("\n", " ").strip()
            errors.append(f"{url}（{type(e).__name__}: {detail}）")
    if not errors:
        raise RuntimeError("没有可用的 Maven 下载源，请检查下载源设置")
    raise RuntimeError(
        "Maven 依赖下载失败；已依次尝试：\n- " + "\n- ".join(errors)
    ) from last_err


def download_many(jobs: list, workers: int = PARALLEL_WORKERS,
                  progress_callback=None) -> tuple:
    """并行下载多个文件,单个失败不中断其余。

    jobs: [(名字, 大小, 任务函数)] — 任务函数签名 fn(progress_callback),
          成功正常返回,失败抛异常。
    进度:total = 已知大小之和(全未知时按任务数),回调 (已完成总字节, total)。
    每个并行文件都单独记录其实时字节数，最终向外报告所有文件之和；因此进度
    是一次下载任务的单调整体进度，不能因另一文件开始而回到 0。
    返回 (成功数, 失败列表[(名字, 原因)])。"""
    total = sum(int(s) for _n, s, _f in jobs) or len(jobs)
    completed = [0]
    current = [0] * len(jobs)
    last_reported = [0]
    lock = threading.Lock()

    def report(index, done, size):
        with lock:
            # 对未知大小任务，下载中无法可靠地换算字节进度，留到完成时计 1。
            # 已知大小则限制在该文件声明的大小内，避免镜像响应头异常造成超量。
            current[index] = min(max(int(done or 0), 0), int(size)) if size else 0
            now = completed[0] + sum(current)
            # 网络线程的回调先后不可预测；视觉进度只允许前进。
            last_reported[0] = max(last_reported[0], now)
            now = last_reported[0]
        if progress_callback:
            progress_callback(now, total)

    def run(index, name, size, fn):
        try:
            fn(lambda d, _t: report(index, d, size))
            with lock:
                completed[0] += int(size) if size else 1
                current[index] = 0
                last_reported[0] = max(last_reported[0], completed[0] + sum(current))
                now = last_reported[0]
            if progress_callback:
                progress_callback(now, total)
            return True, None
        except Exception as e:
            return False, (str(e) or type(e).__name__)[:120]

    ok = 0
    failures = []
    if len(jobs) <= 1 or workers <= 1:
        for index, (name, size, fn) in enumerate(jobs):
            good, err = run(index, name, size, fn)
            ok += good
            if err:
                failures.append((name, err))
        return ok, failures
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run, i, n, s, f): n
                for i, (n, s, f) in enumerate(jobs)}
        for fut in futs:
            try:
                good, err = fut.result()
            except Exception as e:
                good, err = False, (str(e) or type(e).__name__)[:120]
            ok += good
            if err:
                failures.append((futs[fut], err))
    return ok, failures
