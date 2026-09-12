# -*- coding: utf-8 -*-
"""正式打包前检查依赖和会被嵌入 exe 的本地资源。"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from os_platform.system import current_os_name  # noqa: E402
from paths import runtime_llama_dir  # noqa: E402
from tools import fetch_bridge_mod_jars, fetch_llamacpp  # noqa: E402


REQUIRED_MODULES = ("PySide6", "requests", "psutil", "cryptography", "webview", "PyInstaller")


def main() -> int:
    errors = []
    if sys.version_info[:2] != (3, 12):
        errors.append(
            f"正式 Windows 构建必须使用 Python 3.12.x；当前是 "
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    missing_modules = [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]
    if missing_modules:
        errors.append("缺少正式构建依赖：" + "、".join(missing_modules))

    try:
        fetch_llamacpp.verify_runtime(runtime_llama_dir(), current_os_name(), execute=True)
    except Exception as exc:
        errors.append(str(exc))

    bridge_dir = os.path.join(ROOT, "bridge-mod", "dist")
    for _loader, _mc, name, _url, sha1 in fetch_bridge_mod_jars._JARS:
        path = os.path.join(bridge_dir, name)
        if not os.path.isfile(path):
            errors.append(f"缺少已发布 bridge-mod：{name}")
        elif fetch_bridge_mod_jars._sha1(path) != sha1:
            errors.append(f"bridge-mod 校验失败：{name}")

    for relative in (os.path.join("icons", "grass_block.png"),
                     os.path.join("icons", "grass_block.ico"),
                     "THIRD_PARTY_NOTICES.md"):
        if not os.path.isfile(os.path.join(ROOT, relative)):
            errors.append(f"缺少打包资源：{relative}")

    if errors:
        print("RELEASE INPUTS FAIL", file=sys.stderr)
        for error in errors:
            print("- " + error, file=sys.stderr)
        return 1
    print("RELEASE INPUTS OK: dependencies, llama.cpp, bridge-mod and notices verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
