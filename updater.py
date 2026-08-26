# -*- coding: utf-8 -*-
"""
自动更新(从 GitHub 仓库拉取新版本):
- 检查 AMCL 启动器:对比 GitHub Releases 最新 tag 与当前 VERSION
- 检查 bridge-mod:在 Releases 里找含 agentmc-bridge jar 资产的版本
- 下载新 exe 到 AMCL/update/,生成替换脚本(旧 exe 退出后自动替换并重启)

发版规范(与 updater 配合):
- AMCL:打 vX.Y.Z tag + 同名 Release,附 AgentMinecraftLauncher.exe 资产
- bridge-mod:单独 tag(如 v0.1.0),附 agentmc-bridge-fabric/neoforge-*.jar 资产
"""
import os
import re
import subprocess

import requests

REPO = "erfanyo/Agent_Minecraft_Launcher"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases"
LAUNCHER_ASSET = "AgentMinecraftLauncher.exe"

# 当前启动器版本(发版时改这里 + 打同版本 tag)
VERSION = "0.4.0"

_HEADERS = {"User-Agent": "AgentMinecraftLauncher-Updater/{}".format(VERSION)}


def parse_version(tag: str) -> tuple:
    """'v0.2.0' → (0, 2, 0);解析不了返回 (0,)"""
    m = re.findall(r"\d+", (tag or "").strip().lstrip("vV"))
    return tuple(int(x) for x in m[:3]) or (0,)


def _latest_release() -> dict | None:
    """GitHub 最新 release(取不到返回 None)"""
    resp = requests.get(RELEASES_API + "/latest", headers=_HEADERS, timeout=15)
    if resp.status_code != 200:
        return None
    return resp.json()


def check_launcher_update() -> dict | None:
    """检查 AMCL 更新:返回 {version, url, size} 或 None(无更新/失败)。
    version 是 'v0.2.0' 这样的 tag 名。"""
    rel = _latest_release()
    if not rel or not rel.get("tag_name"):
        return None
    asset = next((a for a in rel.get("assets", [])
                  if a.get("name") == LAUNCHER_ASSET), None)
    if asset is None:
        return None
    return {"version": rel["tag_name"],
            "url": asset.get("browser_download_url", ""),
            "size": asset.get("size", 0)}


def check_bridge_mod_update() -> dict | None:
    """检查 bridge-mod 更新:在最近 Releases 里找含 agentmc-bridge jar 的,
    返回 {version, fabric, neoforge}(下载地址,可能只有其一)或 None。"""
    resp = requests.get(RELEASES_API, params={"per_page": 10},
                        headers=_HEADERS, timeout=15)
    if resp.status_code != 200:
        return None
    for rel in resp.json():
        bridge = [a for a in rel.get("assets", [])
                  if "agentmc-bridge" in (a.get("name") or "")]
        if not bridge:
            continue
        info = {"version": rel.get("tag_name", "")}
        for a in bridge:
            name = a.get("name", "")
            if "fabric" in name:
                info["fabric"] = a.get("browser_download_url", "")
            elif "neoforge" in name:
                info["neoforge"] = a.get("browser_download_url", "")
        return info
    return None


def download_to(url: str, dest: str, progress_callback=None) -> str:
    """下载 url 到 dest,返回 dest;失败抛异常。"""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    resp = requests.get(url, stream=True, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    done = 0
    try:
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                f.write(chunk)
                done += len(chunk)
                if progress_callback:
                    progress_callback(done, total)
    except Exception:
        if os.path.exists(dest):
            try:
                os.remove(dest)
            except OSError:
                pass
        raise
    return dest


def make_update_bat(exe_path: str, new_exe: str, bat_path: str) -> str:
    """生成替换脚本:等旧 exe 退出 → 用新 exe 覆盖 → 重启 → 删脚本。
    返回 bat_path(Windows 运行中的 exe 无法覆盖自己,必须经脚本中转)。

    重启方式说明:PyInstaller 6.x 单文件 bootloader 启动时会做「父进程安全校验」
    (走进程快照解析父进程可执行路径,抗进程注入/旁路)。若新 exe 由本脚本的瞬态 cmd
    (`start "" exe`)拉起,父进程是一条转瞬即逝的 cmd → 等不到它拍快照时已退出 →
    bootloader 报 "Security validation failure: failed to obtain executable path for
    parent process",重启后的应用起不来(更新"看起来失败")。
    因此这里改用 Windows shell `explorer.exe` 拉起新 exe:它的父进程是常驻的 shell
    (explorer.exe),永远存活且可解析,父进程链绝不落在死进程上,校验必通过。"""
    lines = [
        "@echo off",
        "timeout /t 2 /nobreak >nul",
        f'taskkill /f /im {os.path.basename(exe_path)} >nul 2>&1',
        f'copy /y "{new_exe}" "{exe_path}" >nul',
        f'del "{new_exe}" >nul',
        # 用常驻 shell 拉起新 exe(父进程稳定可解析),避免瞬态 cmd 触发 PyInstaller 父进程校验失败
        f'start "" explorer.exe "{exe_path}"',
        'del "%~f0"',
    ]
    with open(bat_path, "w", encoding="ascii", errors="replace") as f:
        f.write("\r\n".join(lines))
    return bat_path


def run_update_bat(bat_path: str):
    """启动替换脚本(脚本会等本进程退出后替换并重启)"""
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(["cmd", "/c", bat_path],
                     creationflags=creationflags,
                     close_fds=True)
