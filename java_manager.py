# -*- coding: utf-8 -*-
"""
Java 管理:检测系统里有没有合适的 Java,没有就自动下载 Temurin JRE。

Minecraft 不同版本要求的 Java 不同(老版本要 Java 8,新版本要 21)。
启动器的工作:看版本 JSON 里写的"需要 Java 几",然后
1) 在系统里找(自带运行时 / JAVA_HOME / PATH)
2) 找不到 → 从 Adoptium(开源 OpenJDK 发行版)下载对应 JRE 并解压

Adoptium API 用法:https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/...
会自动 302 跳转到 GitHub 上的 zip 文件。
"""
import os
import platform
import re
import shutil
import subprocess
import tempfile
import zipfile

from downloader import download_file

# Adoptium 免登录下载地址模板
ADOPTIUM_API = ("https://api.adoptium.net/v3/binary/latest/{major}/ga/"
                "{os_name}/{arch}/jre/hotspot/normal/eclipse")

MAX_DOWNLOAD_ATTEMPTS = 3  # 下载/解压失败重试次数(网络不稳时自动重下)


def parse_java_major(output: str) -> int:
    """从 java -version 的输出里解析出大版本号。
    'java version "1.8.0_491"'  → 8
    'openjdk version "21.0.6"'  → 21
    """
    m = re.search(r'version "([^"]+)"', output)
    if not m:
        return 0
    ver = m.group(1)
    parts = ver.split(".")
    if parts[0] == "1":  # 老式编号:1.8.x → 8
        return int(parts[1]) if len(parts) > 1 else 0
    return int(parts[0])


def minecraft_java_range(mc_version: str) -> tuple[int, int | None]:
    """返回 Java 版的可用范围 ``(最低, 最高或 None)``。

    这是启动器的保守兼容表，主要用于旧 Forge 的防秒退提示；没有覆盖到的
    快照/实验版本只给出最低版本，不把用户锁死在某个小版本上。
    """
    try:
        parts = tuple(int(x) for x in re.findall(r"\d+", mc_version or "")[:3])
        major, minor, patch = (parts + (0, 0, 0))[:3]
    except Exception:
        return 8, None
    if (major, minor, patch) <= (1, 16, 5):
        return 8, 8
    if (major, minor) == (1, 17):
        return 16, 16
    if (major, minor, patch) <= (1, 20, 4):
        return 17, 17
    return 21, None


def minecraft_java_warning(mc_version: str, java_major_version: int) -> str:
    """给实例设置显示的 Java 兼容说明；空字符串代表在保守范围内。"""
    low, high = minecraft_java_range(mc_version)
    if java_major_version <= 0:
        return "无法读取该 Java 的版本；启动时很可能失败。"
    if java_major_version < low:
        return f"Minecraft {mc_version} 至少需要 Java {low}；当前 Java {java_major_version} 很可能启动失败。"
    if high is not None and java_major_version > high:
        return (f"Minecraft {mc_version}（尤其 Forge/旧 Mod）建议固定 Java {high}；"
                f"当前 Java {java_major_version} 很可能秒退或崩溃。")
    return ""


def java_major(java_exe: str) -> int:
    """运行 java -version 并解析大版本;失败返回 0。
    检测时不弹控制台黑窗口(CREATE_NO_WINDOW)。"""
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        ver_file = os.path.join(tempfile.gettempdir(), "aml_java_ver.txt")
        with open(ver_file, "wb") as f:
            subprocess.run([java_exe, "-version"], stdout=f,
                           stderr=subprocess.STDOUT, timeout=15,
                           creationflags=creationflags)
        with open(ver_file, "rb") as f:
            text = f.read().decode("utf-8", "replace")
        os.remove(ver_file)
        return parse_java_major(text)
    except Exception:
        return 0


def find_java(runtime_dir: str, min_major: int,
              max_major: int | None = None,
              managed_only: bool = False) -> str | None:
    """查找兼容 Java，优先选择最接近目标大版本的运行时。

    ``min_major`` 不能单独代表兼容性：Forge 1.16.x 需要 Java 8，不能因为
    Java 17/21“更高”就被选中。``max_major`` 用于这类有明确上限的旧版本。
    """
    candidates = []

    # 1) 启动器自带的运行时(我们下载解压的)
    if os.path.isdir(runtime_dir):
        for root, _dirs, files in os.walk(runtime_dir):
            if "java.exe" in files:
                candidates.append(os.path.join(root, "java.exe"))

    if managed_only:
        return _pick_compatible_java(candidates, min_major, max_major)

    # 2) JAVA_HOME 环境变量
    jh = os.environ.get("JAVA_HOME")
    if jh:
        candidates.append(os.path.join(jh, "bin", "java.exe"))

    # 3) PATH 里的 java
    for p in os.environ.get("PATH", "").split(os.pathsep):
        exe = os.path.join(p, "java.exe")
        if os.path.isfile(exe):
            candidates.append(exe)

    # 4) Windows 常见安装位置。许多 Temurin 安装不会把 java 加入 PATH，
    #    只靠 JAVA_HOME/PATH 会漏掉用户已经安装好的 Java 8。
    program_files = [os.environ.get("ProgramFiles", ""),
                     os.environ.get("ProgramW6432", ""),
                     os.environ.get("ProgramFiles(x86)", "")]
    for root in dict.fromkeys(p for p in program_files if p):
        for vendor in ("Eclipse Adoptium", "Java", "Microsoft"):
            base = os.path.join(root, vendor)
            try:
                for name in os.listdir(base):
                    candidates.append(os.path.join(base, name, "bin", "java.exe"))
            except OSError:
                pass

    return _pick_compatible_java(candidates, min_major, max_major)


def _pick_compatible_java(candidates: list[str], min_major: int,
                          max_major: int | None) -> str | None:
    """从候选 Java 中挑满足范围且最接近目标版本的一项。"""
    compatible = []
    seen = set()
    for exe in candidates:
        if exe in seen:
            continue
        seen.add(exe)
        major = java_major(exe) if os.path.isfile(exe) else 0
        if major >= min_major and (max_major is None or major <= max_major):
            compatible.append((abs(major - min_major), major, exe))
    return min(compatible)[2] if compatible else None


def _find_java_exe(directory: str) -> str | None:
    """在解压后的目录树里找 java.exe"""
    for root, _dirs, files in os.walk(directory):
        if "java.exe" in files:
            return os.path.join(root, "java.exe")
    return None


def valid_zip(path: str) -> bool:
    """校验 zip 完整性:能打开且所有文件 CRC 通过才算好(避免下载了一半的残包)"""
    try:
        with zipfile.ZipFile(path) as z:
            return z.testzip() is None
    except (zipfile.BadZipFile, OSError, EOFError):
        return False


def ensure_java(runtime_dir: str, required_major: int,
                progress_callback=None, status_callback=None,
                max_major: int | None = None,
                prefer_managed: bool = False) -> str:
    """保证有一个大版本 >= required_major 的 Java,返回 java.exe 路径。
    找不到就下载并解压 Temurin JRE(约 50MB,只装一次)。

    下载可能因网络中断留下半截 zip / 解压可能留下半截目录——这里做:
    残留损坏包自动重下、解压前校验完整性、解压前清旧残留、解压后验证 java 可用,
    最多重试 MAX_DOWNLOAD_ATTEMPTS 次。"""
    # 旧 Forge 等对 Java 很挑剔的版本优先使用启动器管理的干净 JRE，避免
    # 用户系统 PATH/JAVA_HOME 指向了不兼容或被其它软件改造过的运行时。
    found = find_java(runtime_dir, required_major, max_major=max_major,
                      managed_only=prefer_managed)
    if found:
        return found

    os.makedirs(runtime_dir, exist_ok=True)
    arch = "x64" if platform.machine().lower() in ("amd64", "x86_64") else "aarch64"
    url = ADOPTIUM_API.format(major=required_major, os_name="windows", arch=arch)

    zip_path = os.path.join(runtime_dir, f"jre-{required_major}.zip")
    dest_dir = os.path.join(runtime_dir, f"jre-{required_major}")

    for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
        # 1) 下载:残留的损坏 zip 先删掉,别让它骗过"已存在"检查
        if os.path.exists(zip_path) and not valid_zip(zip_path):
            if status_callback:
                status_callback(f"发现 Java 压缩包损坏,删除后重新下载(第 {attempt} 次)")
            os.remove(zip_path)
        if not os.path.exists(zip_path):
            if status_callback:
                status_callback(f"下载 Java {required_major}(约 50MB,第 {attempt} 次)...")
            try:
                download_file(url, zip_path, progress_callback=progress_callback)
            except Exception as e:
                if os.path.exists(zip_path):
                    os.remove(zip_path)  # 下载中断:清掉半截文件
                if attempt >= MAX_DOWNLOAD_ATTEMPTS:
                    raise RuntimeError(f"Java 下载失败(已重试 {attempt} 次):{e}")
                continue

        # 2) 解压前再校验一次完整性(下载中断可能留下能打开但 CRC 错的包)
        if not valid_zip(zip_path):
            os.remove(zip_path)
            if attempt >= MAX_DOWNLOAD_ATTEMPTS:
                raise RuntimeError("Java 压缩包损坏(多次下载仍失败),请检查网络后重试")
            continue

        # 3) 解压:先清掉上次可能残留的半截目录
        if os.path.isdir(dest_dir):
            shutil.rmtree(dest_dir, ignore_errors=True)
        if status_callback:
            status_callback(f"解压 Java {required_major}...")
        try:
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(dest_dir)
        except Exception:
            shutil.rmtree(dest_dir, ignore_errors=True)
            if os.path.exists(zip_path):
                os.remove(zip_path)
            if attempt >= MAX_DOWNLOAD_ATTEMPTS:
                raise RuntimeError("Java 解压失败(已重试多次),请清理后重试")
            continue

        # 4) 验证解压结果:找到 java.exe 且版本达标,否则整目录作废重来
        java_exe = _find_java_exe(dest_dir)
        if java_exe and java_major(java_exe) >= required_major:
            os.remove(zip_path)  # 解压成功就删掉压缩包,省空间
            return java_exe
        shutil.rmtree(dest_dir, ignore_errors=True)
        if os.path.exists(zip_path):
            os.remove(zip_path)

    raise RuntimeError(f"Java {required_major} 安装失败(已重试 {MAX_DOWNLOAD_ATTEMPTS} 次)")
