# -*- coding: utf-8 -*-
"""CI 冒烟脚本:offscreen 下 import 核心模块,验证三平台(Windows/macOS/Linux)能加载。
用法:QT_QPA_PLATFORM=offscreen python ci_smoke.py
成功打印 SMOKE OK,任一 import 失败退出码非 0。
"""
import os
import sys


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
            print(f"SMOKE FAIL: import {m} -> {type(e).__name__}: {e}", file=sys.stderr)
            return 1
    print("SMOKE OK: all modules import")
    return 0


if __name__ == "__main__":
    sys.exit(main())
