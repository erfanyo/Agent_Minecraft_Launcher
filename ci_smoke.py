# -*- coding: utf-8 -*-
"""CI 冒烟脚本:offscreen 下 import 核心模块,验证三平台(Windows/macOS/Linux)能加载。
用法:QT_QPA_PLATFORM=offscreen python ci_smoke.py
成功打印 SMOKE OK,任一 import 失败退出码非 0。
"""
import os
import sys


def _report(message: str, *, error: bool = False) -> None:
    print(message, file=sys.stderr if error else sys.stdout)
    report_path = os.environ.get("AMCL_CI_SMOKE_REPORT", "").strip()
    if report_path:
        with open(report_path, "a", encoding="utf-8") as stream:
            stream.write(message + "\n")


def packaged_file_errors() -> list[str]:
    """Return missing frozen-package resources without changing Qt import order."""
    if not getattr(sys, "frozen", False):
        return []
    bundle = getattr(sys, "_MEIPASS", "")
    required = [
        os.path.join("icons", "grass_block.png"),
        "THIRD_PARTY_NOTICES.md",
        os.path.join("runtime", "llama-cpp",
                     "llama-server.exe" if sys.platform == "win32" else "llama-server"),
    ]
    if sys.platform == "win32":
        required.extend([
            os.path.join("runtime", "llama-cpp", "llama-server-impl.dll"),
            os.path.join("runtime", "llama-cpp", "llama.dll"),
            os.path.join("runtime", "llama-cpp", "ggml.dll"),
        ])
    errors = [f"packaged file missing: {relative}" for relative in required
              if not os.path.isfile(os.path.join(bundle, relative))]
    bridge_dir = os.path.join(bundle, "bridge-mod")
    bridge_jars = [] if not os.path.isdir(bridge_dir) else [
        name for name in os.listdir(bridge_dir)
        if name.startswith("agentmc-bridge-") and name.endswith(".jar")
    ]
    if len(bridge_jars) < 4:
        errors.append(f"only {len(bridge_jars)} bridge-mod jars packaged")
    return errors


def main() -> int:
    # 无显示器环境用 offscreen 平台(CI 三平台都没有真实显示器)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # 项目根加入 path(脚本在根目录)
    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)

    mods = [
        "paths", "settings",
        "os_platform.system", "os_platform.openpath", "os_platform.temperature",
        "os_platform.notify",
        "game_command", "lan_tools", "instance_manager",
        "version_home", "online_center",
        "assistant_ui", "local_ai", "main",
    ]
    for m in mods:
        try:
            __import__(m)
        except Exception as e:
            _report(f"SMOKE FAIL: import {m} -> {type(e).__name__}: {e}", error=True)
            return 1
    for error in packaged_file_errors():
        _report("SMOKE FAIL: " + error, error=True)
        return 1
    _report("SMOKE OK: all modules import and packaged files are present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
