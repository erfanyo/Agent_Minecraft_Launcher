# -*- coding: utf-8 -*-
"""
阶段 1 · 第 1 步:从 Mojang 官方 API 拉取 Minecraft 版本清单,打印出来。

这一小段代码教你三件事:
1. HTTP 请求 —— 用 requests 库向一个网址"要数据"
2. JSON —— 网站返回数据的通用格式,json 就是"嵌套的字典"
3. 异常处理 —— 网络失败时自动换镜像源重试
"""
import sys

import requests

# Windows 老式控制台默认用 GBK 编码,会导致中文乱码;强制用 UTF-8 输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 版本清单的来源:官方源 + 国内镜像源(BMCLAPI)。
# 国内直连官方源经常很慢甚至失败,所以"失败就换下一个源"。
# 顺序由设置 → 镜像源里的"下载策略"决定(见 downloader.MIRROR_STRATEGIES)。
SOURCES = [
    "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json",
    "https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json",
]


def _manifest_candidates() -> list:
    """按当前下载策略生成版本清单候选地址(官方地址 + 所选镜像地址,去重)"""
    from downloader import _active_mirror, _active_strategy, mirror_manifest_url
    mirror = _active_mirror()
    strat = _active_strategy()
    murl = mirror_manifest_url(mirror)   # 无可用镜像时为 None
    official = SOURCES[0]
    if strat == "official_only":
        return [official]
    if strat == "mirror_only":
        return [murl] if murl else []
    if strat == "mirror_first":
        return list(dict.fromkeys(u for u in [murl, official] if u))
    return list(dict.fromkeys(u for u in [official, murl] if u))   # smart_official


def fetch_version_manifest() -> dict:
    """依次尝试各个源,返回版本清单(一个嵌套的 dict)"""
    last_error = None
    for url in _manifest_candidates():
        try:
            print(f"正在请求: {url}")
            resp = requests.get(url, timeout=15)  # 15 秒内没响应就放弃
            resp.raise_for_status()               # 状态码不是 200 就抛异常
            return resp.json()                    # 把响应体解析成 dict
        except Exception as e:                    # 这个源失败了
            print(f"  这个源失败: {e}")
            last_error = e
    raise last_error                              # 所有源都失败,把最后一个错误抛出去


def fetch_version_detail(version_url: str) -> dict:
    """获取某个版本的详细信息(版本 JSON)。

    版本清单里每个版本都有一个 url 指向它自己的详细数据,
    里面写着:客户端 jar 下载地址、大小、所需 Java 版本、资源索引、主类等。
    下载和启动游戏都靠这份数据。
    地址顺序同样由"下载策略"决定(官方地址 / 镜像地址谁先用)。
    """
    from downloader import _active_mirror, _active_strategy, mirror_version_json_url
    mirror = _active_mirror()
    strat = _active_strategy()
    m = mirror_version_json_url(version_url, mirror)
    official = version_url
    if strat == "official_only":
        candidates = [official]
    elif strat == "mirror_only":
        candidates = [m]
    elif strat == "mirror_first":
        candidates = [m, official]
    else:                                        # smart_official
        candidates = [official, m]
    last_error = None
    for u in dict.fromkeys(candidates):
        try:
            resp = requests.get(u, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_error = e
    raise last_error


def main():
    manifest = fetch_version_manifest()

    print(f"\n最新正式版: {manifest['latest']['release']}")
    print(f"最新快照版: {manifest['latest']['snapshot']}")

    print("\n最近的版本列表(前 15 个):")
    for v in manifest["versions"][:15]:
        print(f"  {v['id']:<12} {v['type']}")


if __name__ == "__main__":
    main()
