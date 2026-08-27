# -*- coding: utf-8 -*-
"""下载 bridge-mod 的预编译 jar 到 bridge-mod/dist/(供 PyInstaller datas 打包、源码运行)。

**为什么需要**:spec datas 引用 `bridge-mod/dist/*.jar`,但这些 jar 是编译产物、不在 git,
CI checkout 后缺失会导致 PyInstaller 报 `Unable to find ...`. 本脚本从 GitHub Releases
下载全部已知 jar(见 bridge_mod_dist 的版本表),校验 sha1 后放到 bridge-mod/dist/。

用法:
    python tools/fetch_bridge_mod_jars.py            # 下载缺失的 jar
    python tools/fetch_bridge_mod_jars.py --force    # 强制重下
"""
import argparse
import hashlib
import os
import sys

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 与 bridge_mod_dist 版本表一致(单一来源入口;这里列出 URL+sha1 兜底)
_JARS = [
    # (loader, mc, 文件名, 下载URL, sha1)
    ("fabric", "1.20.1", "agentmc-bridge-fabric-1.20.1-0.1.0.jar",
     "https://github.com/erfanyo/Agent_Minecraft_Launcher/releases/download/v0.1.0/agentmc-bridge-fabric-1.20.1-0.1.0.jar",
     "a014570661f3b5b07a272759960461e42dbbd9bf"),
    ("fabric", "1.21.1", "agentmc-bridge-fabric-1.21.1-0.1.0.jar",
     "https://github.com/erfanyo/Agent_Minecraft_Launcher/releases/download/v0.1.0/agentmc-bridge-fabric-1.21.1-0.1.0.jar",
     "65fa0a51c7691aea1b42648d3b6f8119550c243b"),
    ("forge", "1.20.1", "agentmc-bridge-forge-1.20.1-0.1.0.jar",
     "https://github.com/erfanyo/Agent_Minecraft_Launcher/releases/download/v0.1.0/agentmc-bridge-forge-1.20.1-0.1.0.jar",
     "402dc735cf8bc37c7f7701c7d1aed87e587e9174"),
    ("neoforge", "1.21.1", "agentmc-bridge-neoforge-1.21.1-0.1.0.jar",
     "https://github.com/erfanyo/Agent_Minecraft_Launcher/releases/download/v0.1.0/agentmc-bridge-neoforge-1.21.1-0.1.0.jar",
     "227d01ffba887eb76a1ce13e36c1685b5e67dc2f"),
]


def _sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist = os.path.join(root, "bridge-mod", "dist")
    os.makedirs(dist, exist_ok=True)
    ok = 0
    for loader, mc, name, url, sha in _JARS:
        dest = os.path.join(dist, name)
        if os.path.exists(dest) and not args.force and _sha1(dest) == sha:
            print(f"已存在(sha1 校验过): {name}")
            ok += 1
            continue
        print(f"下载 {name} ...")
        try:
            r = requests.get(url, stream=True, timeout=120)
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        except Exception as e:
            print(f"!! 下载失败 {name}: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        if _sha1(dest) != sha:
            print(f"!! sha1 校验失败 {name}", file=sys.stderr)
            return 1
        print(f"  OK {name} ({os.path.getsize(dest)} 字节)")
        ok += 1
    print(f"完成: {ok}/{len(_JARS)} 个 jar 就绪 -> {dist}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
