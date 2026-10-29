# -*- coding: utf-8 -*-
"""本地模型镜像服务器(测试/开发用,随项目虚拟环境启动)。

用途:测试时模型文件从**本地**下载,不走公网(hf-mirror / huggingface 慢或受限)。
- 服务目录:开发机 `AMCL/models/`(manifest.json + GGUF 文件)
- URL 兼容 HuggingFace 结构:`/resolve/main/<file>`;也支持 `/models/<file>`
- 用法:
    .venv\\Scripts\\python.exe dev_model_server.py [端口]     # 默认 8765
- 配合:model_registry 读环境变量 `AML_MODEL_MIRROR` 作为**唯一**候选(设了就不走公网):
    $env:AML_MODEL_MIRROR = "http://127.0.0.1:8765"
  然后启动器/测试代码里 model_registry.download(...) 即从本地服务器拉模型(秒下,带进度)。

比"本地服务器"更省事的替代(推荐日常用):直接把开发机 `AMCL/models/` 整个拷到
测试环境同路径(模型 + manifest.json),sha256 校验通过后 download() 直接跳过,零下载。
服务器适合:反复测下载链路(进度/校验/失败重试)或 Sandbox 里不方便拷大文件的场景。
"""
import argparse
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from paths import model_dir

MODELS_DIR = model_dir()


class ModelHandler(SimpleHTTPRequestHandler):
    """把 /resolve/main/<file> 与 /models/<file> 映射到 AMCL/models/<file>"""

    def translate_path(self, path):
        p = path.split("?", 1)[0]
        for prefix in ("/resolve/main/", "/models/"):
            if p.startswith(prefix):
                rel = p[len(prefix):]
                # 只允许单文件名(防目录穿越);HF 结构下 file 就是文件名
                name = os.path.basename(rel)
                if ".." in rel:
                    return ""
                return os.path.join(MODELS_DIR, name)
        return super().translate_path(path)  # 其他路径(如 / )→ 列目录(方便查看)

    def log_message(self, fmt, *args):
        sys.stderr.write("[model-server] %s\n" % (fmt % args))


def main():
    # Windows 控制台可能是 GBK,先切 UTF-8 避免打印中文/符号崩(UnicodeEncodeError)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="本地模型镜像服务器(测试用)")
    ap.add_argument("port", nargs="?", type=int, default=8765)
    args = ap.parse_args()

    if not os.path.isdir(MODELS_DIR):
        print(f"[错误] 模型目录不存在:{MODELS_DIR}\n(先确认开发机 AMCL/models/ 里有模型,或设置 AML_DATA_DIR 指向带模型的目录)")
        return 1
    files = [f for f in os.listdir(MODELS_DIR) if f.endswith(".gguf")]
    print(f"[模型镜像服务器] 服务目录:{MODELS_DIR}")
    print(f"  模型文件: {len(files)} 个 GGUF({', '.join(files) if files else '无'})")
    print(f"  地址: http://127.0.0.1:{args.port}")
    print(f"  模型下载路径: http://127.0.0.1:{args.port}/resolve/main/<文件>")
    print(f"  配合使用: 设置环境变量 AML_MODEL_MIRROR=http://127.0.0.1:{args.port} 后,"
          f"启动器模型下载走本地(不再走公网)")
    ThreadingHTTPServer(("127.0.0.1", args.port), ModelHandler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
