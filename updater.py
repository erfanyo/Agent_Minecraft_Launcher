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
import json
import re
import subprocess
import uuid

import requests

REPO = "erfanyo/Agent_Minecraft_Launcher"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases"
LAUNCHER_ASSET = "AgentMinecraftLauncher.exe"

# 当前启动器版本(发版时改这里 + 打同版本 tag)
VERSION = "1.0.0"

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


def download_to(url: str, dest: str, progress_callback=None, expected_size: int = 0) -> str:
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
        if expected_size and done != expected_size:
            raise ValueError(f"下载文件大小不完整（应为 {expected_size} 字节，实际 {done} 字节）")
        # 更新资产必须至少像一个 Windows 可执行文件，避免错误页被当成新版覆盖旧版。
        with open(dest, "rb") as f:
            if f.read(2) != b"MZ":
                raise ValueError("下载到的文件不是有效的 Windows 程序")
    except Exception:
        if os.path.exists(dest):
            try:
                os.remove(dest)
            except OSError:
                pass
        raise
    return dest


def _update_paths(update_dir: str) -> dict:
    return {
        "pending": os.path.join(update_dir, "pending-update.json"),
        "staged_pending": os.path.join(update_dir, "pending-update.staged.json"),
        "notice": os.path.join(update_dir, "rollback.notice"),
    }


def make_update_bat(exe_path: str, new_exe: str, bat_path: str,
                    current_pid: int | None = None) -> str:
    """生成带启动确认的事务式替换脚本。

    旧版先备份；新版显示主窗口后会写确认标记。限定时间内没有确认，脚本自动
    结束失败的新版本、恢复旧 EXE 并重新打开。用户数据始终不在替换范围内。
    返回 bat_path(Windows 运行中的 exe 无法覆盖自己,必须经脚本中转)。

    重启方式说明(PyInstaller 6.22+ 父进程安全校验):
    单文件 bootloader 启动时会解析【父进程】的可执行路径做安全校验;若父进程是
    瞬态的(cmd / start 的临时进程),拍快照时父进程已退出 → 报
    "Security validation failure: failed to obtain executable path for parent process",
    重启后的应用起不来(更新"看起来失败")。
    这里改用常驻的 **explorer.exe(shell)** 拉起新 exe:父进程是 explorer(常驻、可解析),
    父进程链绝不落在死进程上,校验必通过。
    (注:曾试过 schtasks 任务计划拉起,但部分环境需管理员权限/沙箱受限,故用 explorer。)"""
    update_dir = os.path.dirname(os.path.abspath(bat_path))
    os.makedirs(update_dir, exist_ok=True)
    paths = _update_paths(update_dir)
    marker_name = f"startup-ok-{uuid.uuid4().hex}.marker"
    marker_path = os.path.join(update_dir, marker_name)
    backup_path = exe_path + ".update-backup"
    with open(paths["staged_pending"], "w", encoding="utf-8") as f:
        json.dump({"marker": marker_name}, f)

    pid = int(current_pid if current_pid is not None else os.getpid())
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "setlocal",
        "timeout /t 2 /nobreak >nul",
        f'taskkill /f /pid {pid} >nul 2>&1',
        'ping 127.0.0.1 -n 2 >nul',
        f'copy /y "{exe_path}" "{backup_path}" >nul',
        "if errorlevel 1 goto backup_failed",
        f'copy /y "{new_exe}" "{exe_path}" >nul',
        "if errorlevel 1 goto replace_failed",
        f'move /y "{paths["staged_pending"]}" "{paths["pending"]}" >nul',
        "if errorlevel 1 goto replace_failed",
        # 用常驻 shell 拉起新 exe(父进程稳定可解析),避免瞬态 cmd 触发 PyInstaller 父进程校验失败
        f'start "" explorer.exe "{exe_path}"',
        "for /l %%i in (1,1,90) do (",
        "  timeout /t 1 /nobreak >nul",
        f'  if exist "{marker_path}" goto update_ok',
        ")",
        # 新版没有确认可用：结束它，恢复旧版，再由 explorer 启动。
        f'taskkill /f /im "{os.path.basename(exe_path)}" >nul 2>&1',
        'ping 127.0.0.1 -n 2 >nul',
        f'copy /y "{backup_path}" "{exe_path}" >nul',
        "if errorlevel 1 goto restore_failed",
        f'>"{paths["notice"]}" echo startup_timeout',
        f'del /q "{paths["pending"]}" "{marker_path}" "{new_exe}" "{backup_path}" >nul 2>&1',
        f'start "" explorer.exe "{exe_path}"',
        "goto clean_script",
        ":replace_failed",
        f'copy /y "{backup_path}" "{exe_path}" >nul',
        "if errorlevel 1 goto restore_failed",
        f'>"{paths["notice"]}" echo replace_failed',
        f'del /q "{paths["pending"]}" "{paths["staged_pending"]}" "{marker_path}" "{new_exe}" "{backup_path}" >nul 2>&1',
        f'start "" explorer.exe "{exe_path}"',
        "goto clean_script",
        ":backup_failed",
        f'>"{paths["notice"]}" echo backup_failed',
        f'del /q "{paths["staged_pending"]}" "{new_exe}" >nul 2>&1',
        f'start "" explorer.exe "{exe_path}"',
        "goto clean_script",
        ":restore_failed",
        f'>"{paths["notice"]}" echo restore_failed',
        "goto clean_script",
        ":update_ok",
        f'del /q "{paths["pending"]}" "{marker_path}" "{new_exe}" "{backup_path}" "{paths["notice"]}" >nul 2>&1',
        ":clean_script",
        "endlocal",
        'del "%~f0"',
    ]
    # 第一行先切换 cmd 到 UTF-8，避免中文用户名或安装目录被写坏。
    with open(bat_path, "w", encoding="utf-8", errors="strict") as f:
        f.write("\r\n".join(lines))
    return bat_path


def confirm_pending_update(base_dir: str) -> bool:
    """主窗口可用后确认更新成功；只允许在固定更新目录创建随机标记。"""
    update_dir = os.path.join(os.path.abspath(base_dir), "AMCL", "update")
    pending = _update_paths(update_dir)["pending"]
    try:
        with open(pending, encoding="utf-8") as f:
            marker = json.load(f).get("marker", "")
        if not re.fullmatch(r"startup-ok-[0-9a-f]{32}\.marker", marker):
            return False
        marker_path = os.path.join(update_dir, marker)
        with open(marker_path, "x", encoding="ascii") as f:
            f.write("ok")
        return True
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def consume_rollback_notice(base_dir: str) -> str:
    """读取并清除一次性回退结果，返回适合界面展示的用户语言。"""
    notice = _update_paths(os.path.join(os.path.abspath(base_dir), "AMCL", "update"))["notice"]
    try:
        with open(notice, encoding="ascii", errors="replace") as f:
            code = f.read().strip()
        os.remove(notice)
    except OSError:
        return ""
    if code == "restore_failed":
        return "更新没有完成，而且旧版本未能自动恢复。请从发布页重新下载启动器；游戏和设置数据没有被删除。"
    return "新版本未能正常启动，已自动恢复到更新前的版本。你的游戏、存档和设置没有变化。"


def run_update_bat(bat_path: str):
    """启动替换脚本(脚本会等本进程退出后替换并重启)"""
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(["cmd", "/c", bat_path],
                     creationflags=creationflags,
                     close_fds=True)
