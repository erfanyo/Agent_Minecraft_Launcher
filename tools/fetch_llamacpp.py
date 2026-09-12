# -*- coding: utf-8 -*-
"""下载并解压 llama.cpp server 二进制到 AMCL/runtime/llama-cpp/——跨平台。

**为什么需要**:llama.cpp 的预编译二进制是分平台的(Windows 用 .exe 且不同资产名、
macOS/Linux 用 tar.gz 且可执行无 .exe 后缀)。之前 fetch 脚本硬编码 win-cpu-x64,
导致 mac/Linux 打包/分发缺对应二进制。本脚本按【当前平台 + 架构】选对应官方资产,
下载并解压出需要的可执行文件。

用法:
    python tools/fetch_llamacpp.py                 # 按当前平台下载(须在有网环境)
    python tools/fetch_llamacpp.py --version b10590  # 指定版本(默认 b10590)

产物:AMCL/runtime/llama-cpp/ 下放入 llama-server(win 为 .exe)等。
注意:llama.cpp 官方 release 资产命名:llama-<ver>-bin-<os>-<variant>-<arch>.zip|tar.gz
"""
import argparse
import hashlib
import os
import stat
import subprocess
import sys
import tarfile
import zipfile

import requests

# Windows 默认控制台可能非 UTF-8,print 中文会 UnicodeEncodeError;强制 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 让脚本能 import 项目(os_platform)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from os_platform.system import current_arch, current_os_name  # noqa: E402
from paths import runtime_llama_dir  # noqa: E402

DEFAULT_VERSION = "b10590"

# GitHub release API 提供的官方 SHA256。固定版本和摘要，避免同名资产被替换后
# 悄悄进入正式发行包。
ASSET_SHA256 = {
    "llama-b10590-bin-macos-arm64.tar.gz": "6bd011f97a27eb27e296fa17867948d97988857ddde98159fca925e2d73a1362",
    "llama-b10590-bin-macos-x64.tar.gz": "ba08608c77cd28f81cd27a98c4829b2513eaf053b1168bf32ca63ffc991f88a3",
    "llama-b10590-bin-ubuntu-arm64.tar.gz": "12999190e14133086dd4a6be57ab23484edb29b79e1d15677b3fb09d78cf3e2f",
    "llama-b10590-bin-ubuntu-x64.tar.gz": "4efbac3e8a647c49cc4856248fa295937b94921e31cdb2c964bf8c5772473559",
    "llama-b10590-bin-win-cpu-arm64.zip": "a88a3b3d6e89569c7b1c8e97212e9f56d1895e92f2cf8b7e4b075a1a6fffab8a",
    "llama-b10590-bin-win-cpu-x64.zip": "98d942240a61a5c628c16d7951c041095e63a741916c74110e785129e10c2eaa",
}


def _asset_name(version: str, os_name: str, arch: str) -> str | None:
    """按平台+架构返回 llama.cpp release 资产文件名。未知组合返回 None。"""
    a = arch
    # llama.cpp 用 x64/arm64(不同习惯名映射)
    a = "arm64" if a in ("arm64", "aarch64") else ("x64" if a in ("x86_64", "amd64") else a)
    if os_name == "windows":
        # llama.cpp win 资源用 zip
        if a in ("x64", "arm64"):
            return f"llama-{version}-bin-win-cpu-{a}.zip"
    elif os_name == "osx":
        if a in ("x64", "arm64"):
            return f"llama-{version}-bin-macos-{a}.tar.gz"
    elif os_name == "linux":
        # ubuntu 资产(通用 linux 用这个;ARM 用 ubuntu-arm64)
        if a == "x64":
            return f"llama-{version}-bin-ubuntu-x64.tar.gz"
        if a == "arm64":
            return f"llama-{version}-bin-ubuntu-arm64.tar.gz"
    return None


def _download(url: str, dest: str) -> None:
    print(f"下载 {url} ...")
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 256):
            if chunk:
                f.write(chunk)


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_server_runtime_file(name: str, os_name: str) -> bool:
    """只挑出 llama-server 及其动态库，避免把所有命令行工具打进 exe。"""
    base = os.path.basename(name)
    low = base.lower()
    if low in ("llama-server", "llama-server.exe"):
        return True
    if os_name == "windows":
        return low.endswith(".dll")
    return low.endswith(".dylib") or ".so" in low


def _extract(archive: str, dest_dir: str, os_name: str) -> list[str]:
    """扁平解压 server 与其动态库；返回写入的文件名。"""
    print(f"解压 {os.path.basename(archive)} -> {dest_dir}")
    got = []
    os.makedirs(dest_dir, exist_ok=True)
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                base = os.path.basename(name)
                if base and _is_server_runtime_file(base, os_name):
                    data = z.read(name)
                    target = os.path.join(dest_dir, base)
                    with open(target, "wb") as f:
                        f.write(data)
                    got.append(base)
                    print("  解出:", base)
    else:
        with tarfile.open(archive, "r:gz") as tf:
            for m in tf.getmembers():
                if m.isfile():
                    base = os.path.basename(m.name)
                    if base and _is_server_runtime_file(base, os_name):
                        data = tf.extractfile(m).read()
                        target = os.path.join(dest_dir, base)
                        with open(target, "wb") as f:
                            f.write(data)
                        if base == "llama-server":
                            os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR)
                        got.append(base)
                        print("  解出:", base)
    return got


def verify_runtime(dest_dir: str, os_name: str, *, execute: bool = False) -> list[str]:
    """验证 server 和关键依赖存在；可选实际运行一次 ``--version``。"""
    suffix = ".exe" if os_name == "windows" else ""
    server = os.path.join(dest_dir, "llama-server" + suffix)
    missing = []
    if not os.path.isfile(server) or os.path.getsize(server) == 0:
        missing.append(os.path.basename(server))
    names = {name.lower() for name in os.listdir(dest_dir)} if os.path.isdir(dest_dir) else set()
    if os_name == "windows":
        for required in ("llama-server-impl.dll", "llama.dll", "ggml.dll"):
            if required not in names:
                missing.append(required)
    elif not any(name.endswith(".dylib") or ".so" in name for name in names):
        missing.append("llama/ggml 动态库")
    if missing:
        raise RuntimeError("llama.cpp 运行时不完整，缺少：" + "、".join(missing))
    if execute:
        result = subprocess.run([server, "--version"], capture_output=True, text=True,
                                timeout=30, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "无输出").strip()
            raise RuntimeError(f"llama-server --version 失败({result.returncode})：{detail}")
    return sorted(names)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=DEFAULT_VERSION)
    ap.add_argument("--force", action="store_true", help="已有也强制重下")
    ap.add_argument("--verify-only", action="store_true", help="不下载，只验证现有运行时")
    args = ap.parse_args()

    os_name = current_os_name()
    arch = current_arch()
    asset = _asset_name(args.version, os_name, arch)
    if asset is None:
        print(f"!! 不支持的平台/架构组合: {os_name}/{arch}(llama.cpp 无对应资产)", file=sys.stderr)
        return 1
    print(f"平台: {os_name}/{arch} -> 资产 {asset}")

    dest_dir = runtime_llama_dir()
    exe = os.path.join(dest_dir, "llama-server" + (".exe" if os_name == "windows" else ""))
    if args.verify_only:
        verify_runtime(dest_dir, os_name, execute=True)
        print("llama.cpp 运行时验证通过")
        return 0
    if os.path.exists(exe) and not args.force:
        try:
            verify_runtime(dest_dir, os_name, execute=True)
            print("llama-server 及依赖已存在并可运行，跳过(--force 可重下)")
            return 0
        except RuntimeError as exc:
            print(f"现有运行时不完整，将重新下载：{exc}")

    url = f"https://github.com/ggml-org/llama.cpp/releases/download/{args.version}/{asset}"
    archive = os.path.join(dest_dir, asset)
    try:
        _download(url, archive)
        expected = ASSET_SHA256.get(asset)
        if not expected:
            raise RuntimeError(f"没有登记 {asset} 的 SHA256，拒绝用于打包")
        actual = _sha256(archive)
        if actual != expected:
            raise RuntimeError(f"SHA256 不匹配：期望 {expected}，实际 {actual}")
        _extract(archive, dest_dir, os_name)
        verify_runtime(dest_dir, os_name, execute=True)
    finally:
        try:
            os.remove(archive)
        except OSError:
            pass
    print(f"完成 -> {dest_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
