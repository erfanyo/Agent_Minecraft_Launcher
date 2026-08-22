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
                  progress_callback=None) -> None:
    """把 url 下载到 dest。

    参数:
      url    —— 文件地址
      dest   —— 保存路径(自动创建上级目录)
      sha1   —— 期望的指纹;给出则下载后校验,不一致删除并报错
      progress_callback(done, total) —— 进度回调,total 为 0 表示总量未知
    """
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    resp = requests.get(url, stream=True, timeout=30)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    done = 0
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
            f.write(chunk)
            done += len(chunk)
            if progress_callback:
                progress_callback(done, total)

    if sha1 and sha1_of_file(dest) != sha1:
        os.remove(dest)
        raise ValueError(f"sha1 校验失败:{os.path.basename(dest)} 文件可能损坏或被篡改")


def mirror_url(url: str, version_id: str | None = None) -> str:
    """把 Mojang 官方下载地址换成 BMCLAPI 镜像地址;换不了就原样返回。
    BMCLAPI 是国内社区维护的下载加速站,和官方内容一致。"""
    if "libraries.minecraft.net" in url:
        return url.replace("https://libraries.minecraft.net/",
                           "https://bmclapi2.bangbang93.com/libraries/")
    if "launcher.mojang.com/maven" in url:
        return "https://bmclapi2.bangbang93.com/maven/" + url.split("/maven/")[-1]
    if "resources.download.minecraft.net" in url:
        # 资源文件按 hash 存放:.../<前两位>/<完整hash>
        return "https://bmclapi2.bangbang93.com/assets/" + url.rstrip("/").rsplit("/", 1)[-1]
    if version_id and ("piston-data.mojang.com" in url or "launcher.mojang.com" in url):
        # 客户端/服务器 jar:BMCLAPI 按版本号提供镜像
        if "client" in url:
            return f"https://bmclapi2.bangbang93.com/version/{version_id}/client"
    return url


def download_with_mirror(url: str, dest: str, version_id: str | None = None,
                         sha1: str | None = None,
                         progress_callback=None) -> None:
    """统一下载入口:官方源先试 2 次(网络偶尔抖动),仍失败换 BMCLAPI 镜像。
    都失败就把最后一个错误抛出去。"""
    last_err = None
    for _ in range(2):
        try:
            download_file(url, dest, sha1=sha1, progress_callback=progress_callback)
            return
        except Exception as e:
            last_err = e
    mirror = mirror_url(url, version_id)
    if mirror != url:
        try:
            download_file(mirror, dest, sha1=sha1, progress_callback=progress_callback)
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
                   progress_callback=None) -> None:
    """下载一个只有 Maven 坐标(路径)、没有明确地址的依赖库。"""
    last_err = None
    for template in MAVEN_REPOS:
        try:
            download_file(template.format(path=path), dest, sha1=sha1,
                          progress_callback=progress_callback)
            return
        except Exception as e:
            last_err = e
    raise last_err


def download_many(jobs: list, workers: int = PARALLEL_WORKERS,
                  progress_callback=None) -> tuple:
    """并行下载多个文件,单个失败不中断其余。

    jobs: [(名字, 大小, 任务函数)] — 任务函数签名 fn(progress_callback),
          成功正常返回,失败抛异常。
    进度:total = 已知大小之和(全未知时按任务数),回调 (已完成总字节, total),
    单调递增(每个任务完成时把其大小累加进已完成)。
    返回 (成功数, 失败列表[(名字, 原因)])。"""
    total = sum(int(s) for _n, s, _f in jobs) or len(jobs)
    completed = [0.0]
    lock = threading.Lock()

    def report(done, size):
        with lock:
            now = completed[0] + done
        if progress_callback:
            progress_callback(now, total)

    def run(name, size, fn):
        try:
            fn(lambda d, _t: report(d, size))
            with lock:
                completed[0] += size
            return True, None
        except Exception as e:
            return False, (str(e) or type(e).__name__)[:120]

    ok = 0
    failures = []
    if len(jobs) <= 1 or workers <= 1:
        for name, size, fn in jobs:
            good, err = run(name, size, fn)
            ok += good
            if err:
                failures.append((name, err))
        return ok, failures
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run, n, s, f): n for n, s, f in jobs}
        for fut in futs:
            try:
                good, err = fut.result()
            except Exception as e:
                good, err = False, (str(e) or type(e).__name__)[:120]
            ok += good
            if err:
                failures.append((futs[fut], err))
    return ok, failures
