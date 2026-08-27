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
import io
import os
import sys
import tarfile
import zipfile

import requests

# 让脚本能 import 项目(os_platform)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from os_platform.system import current_arch, current_os_name  # noqa: E402
from paths import runtime_llama_dir  # noqa: E402

DEFAULT_VERSION = "b10590"


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


def _extract(archive: str, dest_dir: str) -> list[str]:
    """解压 zip/tar.gz,返回解出的可执行文件名(只保留 llama-server/llama-cli)。"""
    print(f"解压 {os.path.basename(archive)} -> {dest_dir}")
    wanted = {"llama-server", "llama-server.exe", "llama-cli", "llama-cli.exe", "llama-gguf"}
    got = []
    os.makedirs(dest_dir, exist_ok=True)
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                base = os.path.basename(name)
                if base in wanted:
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
                    if base in wanted:
                        data = tf.extractfile(m).read()
                        target = os.path.join(dest_dir, base)
                        with open(target, "wb") as f:
                            f.write(data)
                        got.append(base)
                        print("  解出:", base)
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=DEFAULT_VERSION)
    ap.add_argument("--force", action="store_true", help="已有也强制重下")
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
    if os.path.exists(exe) and not args.force:
        print("llama-server 已存在,跳过(--force 可重下)")
        return 0

    url = f"https://github.com/ggml-org/llama.cpp/releases/download/{args.version}/{asset}"
    archive = os.path.join(dest_dir, asset)
    try:
        _download(url, archive)
        _extract(archive, dest_dir)
    finally:
        try:
            os.remove(archive)
        except OSError:
            pass
    print(f"完成 -> {dest_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
