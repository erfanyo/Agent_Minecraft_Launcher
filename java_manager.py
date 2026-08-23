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


def find_java(runtime_dir: str, min_major: int) -> str | None:
    """在三个地方找满足版本的 java.exe:自带运行时、JAVA_HOME、PATH。"""
    candidates = []

    # 1) 启动器自带的运行时(我们下载解压的)
    if os.path.isdir(runtime_dir):
        for root, _dirs, files in os.walk(runtime_dir):
            if "java.exe" in files:
                candidates.append(os.path.join(root, "java.exe"))

    # 2) JAVA_HOME 环境变量
    jh = os.environ.get("JAVA_HOME")
    if jh:
        candidates.append(os.path.join(jh, "bin", "java.exe"))

    # 3) PATH 里的 java
    for p in os.environ.get("PATH", "").split(os.pathsep):
        exe = os.path.join(p, "java.exe")
        if os.path.isfile(exe):
            candidates.append(exe)

    seen = set()
    for exe in candidates:
        if exe in seen:
            continue
        seen.add(exe)
        if os.path.isfile(exe) and java_major(exe) >= min_major:
            return exe
    return None


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
                progress_callback=None, status_callback=None) -> str:
    """保证有一个大版本 >= required_major 的 Java,返回 java.exe 路径。
    找不到就下载并解压 Temurin JRE(约 50MB,只装一次)。

    下载可能因网络中断留下半截 zip / 解压可能留下半截目录——这里做:
    残留损坏包自动重下、解压前校验完整性、解压前清旧残留、解压后验证 java 可用,
    最多重试 MAX_DOWNLOAD_ATTEMPTS 次。"""
    found = find_java(runtime_dir, required_major)
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
