# -*- coding: utf-8 -*-
"""
bridge-mod 自动拉取(分发模块,灵感 #12):
- 版本表:各平台 × MC 版本的 jar 下载地址与校验
- download_bridge_mod():按实例的加载器+基础版本拉取 jar 装到 mods 目录
- 发布流:本地编译 → 传 GitHub Releases → 更新本文件版本表(见 bridge-mod/RELEASE.md)
- 发布仓库:github.com/erfanyo/Agent_Minecraft_Launcher(bridge-mod 子目录)
"""
import hashlib
import os

from downloader import download_with_mirror

BRIDGE_MOD_VERSION = "0.1.0"

# 版本表:loader -> mc_version -> {version, url, sha1}
# 当前支持:Fabric 1.21.1 / NeoForge 1.21.1(均已编译);Forge(1.19 及以前)晚点再做
BRIDGE_MOD_RELEASES = {
    "fabric": {
        "1.21.1": {
            "version": BRIDGE_MOD_VERSION,
            "url": ("https://github.com/erfanyo/Agent_Minecraft_Launcher/releases/download/"
                    "v0.1.0/agentmc-bridge-fabric-1.21.1-0.1.0.jar"),
            "sha1": "fdfb15ba1982d073411fb7c3d439d85d746182ac",
        },
    },
    "neoforge": {
        "1.21.1": {
            "version": BRIDGE_MOD_VERSION,
            "url": ("https://github.com/erfanyo/Agent_Minecraft_Launcher/releases/download/"
                    "v0.1.0/agentmc-bridge-neoforge-1.21.1-0.1.0.jar"),
            "sha1": "9c98674546ed408c50c71e36d1503c108e051705",
        },
    },
}


def bridge_mod_info(loader: str, mc_version: str) -> dict | None:
    """查版本表:该 加载器+MC版本 有没有可用的桥 mod"""
    return BRIDGE_MOD_RELEASES.get(loader, {}).get(mc_version)


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
    - outdated: 已装但版本旧(sha1 与版本表不符,需更新)
    - up_to_date: 已装且是最新
    版本表没有该组合时,已装的算 up_to_date(无从比较)。"""
    jar = _installed_bridge_jar(inst_dir)
    if jar is None:
        return "not_installed"
    info = bridge_mod_info(loader, mc_version)
    if info is None or not info.get("sha1"):
        return "up_to_date"
    return "up_to_date" if verify_sha1(jar, info["sha1"]) else "outdated"


def download_bridge_mod(inst_dir: str, loader: str, mc_version: str,
                        progress_callback=None) -> str:
    """下载 bridge-mod 到实例 mods 目录,返回文件名。
    查不到版本表 → 抛 ValueError(给出提示)。
    优先内置离线通道:PyInstaller 打包时 jar 随 exe 内置(_MEIPASS/bridge-mod/),
    命中直接复制,零联网(灵感 #12 离线通道)。"""
    # 内置 jar 优先(离线通道)
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        import shutil
        bundled = os.path.join(meipass, "bridge-mod")
        want = "neoforge" if loader == "neoforge" else "fabric"
        if os.path.isdir(bundled):
            for f in sorted(os.listdir(bundled)):
                low = f.lower()
                if low.endswith(".jar") and want in low and mc_version in low:
                    mods_dir = os.path.join(inst_dir, "mods")
                    os.makedirs(mods_dir, exist_ok=True)
                    dest = os.path.join(mods_dir, f)
                    if not os.path.exists(dest) or not _installed_bridge_jar(inst_dir):
                        shutil.copy2(os.path.join(bundled, f), dest)
                    return f
    info = bridge_mod_info(loader, mc_version)
    if info is None:
        raise ValueError(
            f"桥 mod 暂不支持 {mc_version}+{loader}(当前支持 Fabric 1.21.1)。\n"
            "或先手动从 GitHub Releases 下载 jar 放进实例 mods 目录。")
    mods_dir = os.path.join(inst_dir, "mods")
    os.makedirs(mods_dir, exist_ok=True)
    filename = info["url"].rsplit("/", 1)[-1]
    dest = os.path.join(mods_dir, filename)
    download_with_mirror(info["url"], dest,
                         sha1=info.get("sha1"), progress_callback=progress_callback)
    return filename


def verify_sha1(path: str, expected: str) -> bool:
    """校验文件 sha1(下载后安全检查)"""
    if not expected:
        return True
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected.lower()
