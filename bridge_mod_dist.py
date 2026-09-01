# -*- coding: utf-8 -*-
"""
bridge-mod 自动拉取(分发模块,灵感 #12 + 自动发现):
- 版本表 = 兜底/固定 sha1(离线可校验);但首选【按文件名自动发现】,
  这样以后发布新的 bridge-mod(新版本 / 新加载器 / 新 MC 版本)无需改启动器。
- jar 命名约定:agentmc-bridge-{loader}-{mc}-{version}.jar
  (如 agentmc-bridge-forge-1.20.1-0.1.0.jar)
- 发现顺序:
  ① 内置离线通道(_MEIPASS/bridge-mod/,PyInstaller 打包时随 exe 内嵌)
  ② 本地编译产物(bridge-mod/dist/,开发者/源码运行)
  ③ GitHub Releases(在线,按文件名模式匹配)
  ④ 版本表兜底(BRIDGE_MOD_RELEASES,带 sha1 可校验)
- download_bridge_mod():按实例加载器+基础版本拉 jar 装到 mods 目录
- 发布流:本地编译 → 传 GitHub Releases(附全部 agentmc-bridge-*.jar 资产)→
  之后启动器自动按名字发现,无需改本文件(版本表仅作陈旧兜底)。
"""
import hashlib
import os
import re
import sys

import requests

from downloader import download_with_mirror

# bridge-mod 兜底版本(当自动发现拿不到 jar 版本号时用);也用于版本表。
# 注意:2026-08-30 bridge-mod 升 0.2.0:新增 server_type 上报,供游戏内 AI 按游戏类型判权限。
BRIDGE_MOD_VERSION = "0.2.0"

# 兜底版本表:loader -> mc_version -> {version, url, sha1}
# 仅用于【离线 + 无法访问 GitHub】时的 sha1 校验兜底;正常优先自动发现。
BRIDGE_MOD_RELEASES = {
    "fabric": {
        "1.20.1": {
            "version": BRIDGE_MOD_VERSION,
            "url": ("https://github.com/erfanyo/Agent_Minecraft_Launcher/releases/download/"
                    "v0.1.0/agentmc-bridge-fabric-1.20.1-0.1.0.jar"),
            "sha1": "a014570661f3b5b07a272759960461e42dbbd9bf",
        },
        "1.21.1": {
            "version": BRIDGE_MOD_VERSION,
            "url": ("https://github.com/erfanyo/Agent_Minecraft_Launcher/releases/download/"
                    "v0.1.0/agentmc-bridge-fabric-1.21.1-0.1.0.jar"),
            "sha1": "65fa0a51c7691aea1b42648d3b6f8119550c243b",
        },
    },
    "forge": {
        "1.20.1": {
            "version": BRIDGE_MOD_VERSION,
            "url": ("https://github.com/erfanyo/Agent_Minecraft_Launcher/releases/download/"
                    "v0.1.0/agentmc-bridge-forge-1.20.1-0.1.0.jar"),
            "sha1": "402dc735cf8bc37c7f7701c7d1aed87e587e9174",
        },
    },
    "neoforge": {
        "1.21.1": {
            "version": BRIDGE_MOD_VERSION,
            "url": ("https://github.com/erfanyo/Agent_Minecraft_Launcher/releases/download/"
                    "v0.1.0/agentmc-bridge-neoforge-1.21.1-0.1.0.jar"),
            "sha1": "227d01ffba887eb76a1ce13e36c1685b5e67dc2f",
        },
    },
}

# GitHub 仓库(与 updater 一致),用于在线自动发现 jar 资产
_GITHUB_RELEASES_API = "https://api.github.com/repos/erfanyo/Agent_Minecraft_Launcher/releases"
_GITHUB_HEADERS = {"User-Agent": "AgentMinecraftLauncher-BridgeMod/{}".format(BRIDGE_MOD_VERSION)}


# ---------------------------------------------------------------------------
# 文件名模式 与 版本比较
# ---------------------------------------------------------------------------
_JAR_RE = re.compile(
    r"^agentmc-bridge-(?P<loader>fabric|forge|neoforge)-"
    r"(?P<mc>[\d.]+)-(?P<ver>[\d.]+)\.jar$", re.IGNORECASE)


def _parse_jar_name(name: str) -> dict | None:
    """解析 bridge-mod jar 文件名,返回 {loader, mc, version} 或 None(不匹配)。"""
    m = _JAR_RE.match(os.path.basename(name))
    if not m:
        return None
    return {"loader": m.group("loader").lower(),
            "mc": m.group("mc"),
            "version": m.group("ver")}


def _version_key(v: str) -> tuple:
    """'0.1.0' → (0,1,0);用于取最新版本。"""
    try:
        return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)
    except Exception:
        return (0,)


def _jar_urls_by_pattern(loader: str, mc: str) -> list:
    """按 loader+mc 计算期望的文件名前缀,用于本地/GitHub 匹配。
    返回 (前缀, 匹配函数)。前缀如 'agentmc-bridge-forge-1.20.1-'。"""
    prefix = f"agentmc-bridge-{loader}-{mc}-"
    return prefix, (lambda name: name.lower().startswith(prefix) and name.lower().endswith(".jar"))


# ---------------------------------------------------------------------------
# 发现候选(源码/打包/在线)
# ---------------------------------------------------------------------------
def _offline_candidates(loader: str, mc: str) -> list:
    """返回离线可用 jar 的绝对路径列表(内置 _MEIPASS + 本地 dist),按版本从新到旧。"""
    prefix, match = _jar_urls_by_pattern(loader, mc)
    seen = set()
    out = []
    dirs = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        dirs.append(os.path.join(meipass, "bridge-mod"))
    # 源码/开发者:项目根 bridge-mod/dist
    proj = os.path.dirname(os.path.abspath(__file__))
    dirs.append(os.path.join(proj, "bridge-mod", "dist"))
    for d in dirs:
        if not os.path.isdir(d):
            continue
        try:
            for fn in sorted(os.listdir(d)):
                if match(fn) and fn not in seen:
                    seen.add(fn)
                    parse = _parse_jar_name(fn)
                    out.append({"file": os.path.join(d, fn), "name": fn,
                                "version": parse["version"] if parse else BRIDGE_MOD_VERSION,
                                "source": "offline"})
        except OSError:
            pass
    out.sort(key=lambda c: _version_key(c["version"]), reverse=True)
    return out


def _github_candidates(loader: str, mc: str) -> list:
    """从 GitHub Releases 找匹配 {loader}-{mc} 的 jar 资产(按版本从新到旧)。"""
    prefix, match = _jar_urls_by_pattern(loader, mc)
    try:
        resp = requests.get(_GITHUB_RELEASES_API, params={"per_page": 15},
                            headers=_GITHUB_HEADERS, timeout=15)
        if resp.status_code != 200:
            return []
        out = []
        for rel in resp.json():
            tag = rel.get("tag_name", "")
            for a in rel.get("assets", []):
                name = a.get("name", "")
                if not match(name):
                    continue
                parse = _parse_jar_name(name)
                out.append({"url": a.get("browser_download_url", ""),
                            "name": name,
                            "version": (parse["version"] if parse else tag.lstrip("v")),
                            "source": "github",
                            "tag": tag})
        out.sort(key=lambda c: _version_key(c["version"]), reverse=True)
        return out
    except Exception:
        return []


def bridge_mod_info(loader: str, mc_version: str) -> dict | None:
    """查该 加载器+MC版本 是否有可用的 bridge-mod(自动发现优先,版本表兜底)。
    返回 {version, url?, sha1?, source, name?} 或 None(该组合不支持)。"""
    # ① 自动发现:本地/在线
    for cand in _offline_candidates(loader, mc_version) + _github_candidates(loader, mc_version):
        return {"version": cand["version"], "source": cand["source"]}
    # ② 版本表兜底(仅当自动发现拿不到,但表里有这个组合)
    info = BRIDGE_MOD_RELEASES.get(loader, {}).get(mc_version)
    if info:
        return {"version": info.get("version", BRIDGE_MOD_VERSION), "source": "table"}
    return None


def has_bridge_mod(inst_dir: str) -> bool:
    """实例 mods 目录是否已装 bridge-mod"""
    mods_dir = os.path.join(inst_dir, "mods")
    if not os.path.isdir(mods_dir):
        return False
    try:
        low = " ".join(f.lower() for f in os.listdir(mods_dir))
    except OSError:
        return False
    return "agentmc_bridge" in low or "agentmc-bridge" in low or "bridge" in low and "jar" in low


def _installed_bridge_jar(inst_dir: str) -> str | None:
    """实例 mods 目录里已装的 bridge-mod jar 完整路径(没有返回 None)"""
    mods_dir = os.path.join(inst_dir, "mods")
    if not os.path.isdir(mods_dir):
        return None
    try:
        for f in os.listdir(mods_dir):
            low = f.lower()
            if "agentmc_bridge" in low or "agentmc-bridge" in low:
                return os.path.join(mods_dir, f)
    except OSError:
        pass
    return None


def check_bridge_mod(inst_dir: str, loader: str, mc_version: str) -> str:
    """检查 bridge-mod 安装状态:
    - not_installed: 没装
    - outdated: 已装但版本旧(sha1 与表不符,或名字不是最新)
    - up_to_date: 已装且是最新
    自动发现拿不到期望值时,已装的算 up_to_date(无从比较)。"""
    jar = _installed_bridge_jar(inst_dir)
    if jar is None:
        return "not_installed"
    info = bridge_mod_info(loader, mc_version)
    if info is None:
        return "up_to_date"
    table = BRIDGE_MOD_RELEASES.get(loader, {}).get(mc_version)
    # 固定 sha1 只属于版本表的旧发布资产。若本地 dist 或 GitHub 自动发现到了
    # 更新的同版本 jar，继续拿旧 sha1 比较会把刚安装的新桥误报为“过期”。
    if info.get("source") == "table" and table and table.get("sha1"):
        return "up_to_date" if verify_sha1(jar, table["sha1"]) else "outdated"
    # 无 sha1 兜底时:比较文件名是否含最新版本号(自动发现结果)
    exp = info.get("version")
    if exp and _version_key(exp) > _version_key(_version_from_name(os.path.basename(jar))):
        return "outdated"
    return "up_to_date"


def _version_from_name(name: str) -> str:
    """从 jar 文件名提取版本号,拿不到返回空。"""
    parse = _parse_jar_name(name)
    return parse["version"] if parse else ""


def download_bridge_mod(inst_dir: str, loader: str, mc_version: str,
                        progress_callback=None) -> str:
    """下载 bridge-mod 到实例 mods 目录,返回文件名。
    自动发现(离线内置 / 本地 dist / GitHub)优先;版本表兜底(GitHub 固定 URL)。
    全部失败 → 抛 ValueError(给出提示)。"""
    mods_dir = os.path.join(inst_dir, "mods")
    os.makedirs(mods_dir, exist_ok=True)

    # ① 离线候选:直接复制(零联网)
    offline = _offline_candidates(loader, mc_version)
    if offline:
        cand = offline[0]
        dest = os.path.join(mods_dir, cand["name"])
        if not os.path.exists(dest) or not _installed_bridge_jar(inst_dir):
            import shutil
            shutil.copy2(cand["file"], dest)
        _remove_replaced_bridge_jars(mods_dir, cand["name"], loader, mc_version)
        return cand["name"]

    # ② GitHub 自动发现并下载
    gh = _github_candidates(loader, mc_version)
    if gh and gh[0].get("url"):
        cand = gh[0]
        dest = os.path.join(mods_dir, cand["name"])
        table = BRIDGE_MOD_RELEASES.get(loader, {}).get(mc_version)
        expected_sha1 = None
        if table and table.get("version") == cand.get("version"):
            expected_sha1 = table.get("sha1")
        download_with_mirror(cand["url"], dest, sha1=expected_sha1,
                             progress_callback=progress_callback)
        _remove_replaced_bridge_jars(mods_dir, cand["name"], loader, mc_version)
        return cand["name"]

    # ③ 版本表兜底(固定 URL)
    info = BRIDGE_MOD_RELEASES.get(loader, {}).get(mc_version)
    if info:
        filename = info["url"].rsplit("/", 1)[-1]
        dest = os.path.join(mods_dir, filename)
        download_with_mirror(info["url"], dest, sha1=info.get("sha1"),
                             progress_callback=progress_callback)
        _remove_replaced_bridge_jars(mods_dir, filename, loader, mc_version)
        return filename

    raise ValueError(
        f"桥 mod 暂不支持 {mc_version}+{loader}(请检查当前发布的 bridge-mod 资产)。\n"
        "或先手动从 GitHub Releases 下载对应 jar 放进实例 mods 目录。")


def _remove_replaced_bridge_jars(mods_dir: str, keep_name: str,
                                 loader: str, mc_version: str) -> None:
    """移除同一 loader + MC 版本的旧 bridge-mod，避免 Forge 同时加载两个副本。"""
    prefix, match = _jar_urls_by_pattern(loader, mc_version)
    try:
        for name in os.listdir(mods_dir):
            if name != keep_name and match(name):
                try:
                    os.remove(os.path.join(mods_dir, name))
                except OSError:
                    pass
    except OSError:
        pass


def verify_sha1(path: str, expected: str) -> bool:
    """校验文件 sha1(下载后安全检查)"""
    if not expected:
        return True
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected.lower()
