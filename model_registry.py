# -*- coding: utf-8 -*-
"""
本地 AI 资源清单(model registry):统一管理可下载/可更新的模型资源(规划 §6)。

- 所有可更新资源(模型/规则集/术语表/引导)走同一套清单 + 下载 + 校验机制,
  避免维护多套更新逻辑。
- 资源清单 manifest.json 存 AMCL/models/manifest.json(便携原则,数据跟 exe 走)。
- 下载:镜像优先(hf-mirror.com,国内快) → 官方兜底(huggingface.co)。
- 校验:sha256 钉住版本(规划 §7.5),防止损坏/中间人替换;下载完立即校验,
  不一致删除报错;已存在且校验通过则跳过(断点续传的简化形态)。
- 模型文件懒加载(规划 §2):清单常驻,大文件等第一次真正用到 AI 功能时才拉。

当前登记的资源(2026-08-23,模型验证用):
  1. qwen3.5-0.8b-general-q4km —— Qwen3.5-0.8B 通用版 GGUF,量化 Q4_K_M(规划 §8.1 候选 A)
  2. qwen3.5-0.8b-xlam-q4km   —— Qwen3.5-0.8B Function-Calling(xLAM)微调版 GGUF,Q4_K_M(候选 B)

TODO(未完成,标记待办):
  - 本地 AI 模型的"下载/管理界面"尚未接入启动器设置页,目前只有本模块的命令行/代码调用入口。
  - 接入时:下载源策略直接复用本文件的 _hf_candidates()(已跟随启动器"设置 → 镜像源"
    的 mirror_strategy,与 Minecraft 下载同一套策略),界面部分参考 settings_dialog 的镜像源页。
"""
import hashlib
import json
import os
import threading

import requests

from paths import CONFIG_DIR  # AMCL 目录(与配置同根,便携)

MODELS_DIR = os.path.join(CONFIG_DIR, "models")
MANIFEST_PATH = os.path.join(MODELS_DIR, "manifest.json")
CHUNK_SIZE = 1024 * 256

# 官方源 = huggingface.co,国内镜像 = hf-mirror.com(国内快)。
# 下载顺序跟随启动器"设置 → 镜像源"的下载策略(见 downloader.MIRROR_STRATEGIES):
#   smart_official 官方优先 / mirror_first 镜像优先 / official_only 仅官方 / mirror_only 仅镜像
HF_OFFICIAL = "https://huggingface.co/{repo}/resolve/main/{file}"
HF_MIRROR = "https://hf-mirror.com/{repo}/resolve/main/{file}"


def _hf_candidates(repo: str, file: str) -> list:
    """按启动器"下载策略"生成模型下载候选地址(官方 = huggingface,镜像 = hf-mirror)"""
    try:
        from downloader import _active_strategy
        strat = _active_strategy()
    except Exception:
        strat = "mirror_first"   # 读不到设置时,模型默认镜像优先(hf-mirror 国内快)
    official = HF_OFFICIAL.format(repo=repo, file=file)
    mirror = HF_MIRROR.format(repo=repo, file=file)
    if strat == "official_only":
        return [official]
    if strat == "mirror_only":
        return [mirror]
    if strat == "smart_official":
        return [official, mirror]
    return [mirror, official]   # mirror_first

# 资源定义(新模型/新资源加在这里,下载与校验逻辑不用动)
RESOURCES = {
    "qwen3.5-0.8b-general-q4km": {
        "id": "qwen3.5-0.8b-general-q4km",
        "name": "Qwen3.5-0.8B 通用版 (Q4_K_M)",
        "type": "model",
        "repo": "Mungert/Qwen3.5-0.8B-GGUF",
        "file": "Qwen3.5-0.8B-q4_k_m.gguf",
        "size": 533614976,
        "sha256": "8bd70fa4eb6015c7b28a60d8f16322c5313cbcddd11f2dac20fff72d70a4c8a8",
        "model_version": "Qwen3.5-0.8B",
        "quant": "Q4_K_M",
        "variant": "general",
    },
    "qwen3.5-0.8b-xlam-q4km": {
        "id": "qwen3.5-0.8b-xlam-q4km",
        "name": "Qwen3.5-0.8B Function-Calling(xLAM) (Q4_K_M)",
        "type": "model",
        "repo": "ermiaazarkhalili/Qwen3.5-0.8B-Function-Calling-xLAM-GGUF",
        "file": "qwen3.5-0.8b-function-calling-xlam.q4_k_m.gguf",
        "size": 529296960,
        "sha256": "0b7c71b865ba6a194f42e369548c405e152ffbaf3c807506d4d718b29ad3f205",
        "model_version": "Qwen3.5-0.8B-Function-Calling-xLAM",
        "quant": "Q4_K_M",
        "variant": "xlam-fc",
    },
}


def _load_manifest() -> dict:
    """读 manifest.json;没有/坏了就重建默认(只登记资源元信息,不含下载状态)"""
    if os.path.exists(MANIFEST_PATH):
        try:
            with open(MANIFEST_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "resources" in data:
                return data
        except Exception:
            pass
    data = {"version": 1, "resources": {}}
    for rid, res in RESOURCES.items():
        data["resources"][rid] = {
            "name": res["name"],
            "type": res["type"],
            "repo": res["repo"],
            "file": res["file"],
            "size": res["size"],
            "sha256": res["sha256"],
            "model_version": res.get("model_version", ""),
            "quant": res.get("quant", ""),
            "variant": res.get("variant", ""),
            "downloaded": False,
            "local_path": "",
            "downloaded_at": "",
        }
    _save_manifest(data)
    return data


def _save_manifest(data: dict) -> None:
    os.makedirs(MODELS_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_resources() -> dict:
    """全部资源及其下载状态(供界面/评测脚本用)"""
    return _load_manifest()["resources"]


def local_path(resource_id: str) -> str:
    """资源本地保存路径(未下载也存在,只是文件可能不存在)"""
    res = RESOURCES.get(resource_id)
    if not res:
        raise KeyError(f"未知资源 {resource_id}")
    return os.path.join(MODELS_DIR, res["file"])


def is_downloaded(resource_id: str) -> bool:
    """文件存在 且 sha256 校验通过 = 已下载。校验失败视为未下载(下次重下)"""
    path = local_path(resource_id)
    if not os.path.exists(path):
        return False
    try:
        return sha256_of_file(path) == RESOURCES[resource_id]["sha256"]
    except Exception:
        return False


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def download(resource_id: str, progress_callback=None) -> str:
    """下载一个资源(按下载策略:官方/镜像谁优先),sha256 校验,返回本地路径。

    progress_callback(done, total):total 为 0 表示总量未知(单线程顺序下载)。
    已下载且校验通过 → 直接返回,不重复下载。
    """
    if resource_id not in RESOURCES:
        raise KeyError(f"未知资源 {resource_id}")
    res = RESOURCES[resource_id]
    dest = local_path(resource_id)

    if is_downloaded(resource_id):
        return dest

    os.makedirs(MODELS_DIR, exist_ok=True)
    last_err = None
    for url in _hf_candidates(res["repo"], res["file"]):
        try:
            _download_file(url, dest, progress_callback=progress_callback)
            actual = sha256_of_file(dest)
            if actual != res["sha256"]:
                os.remove(dest)
                raise ValueError(
                    f"sha256 校验失败:{res['file']}\n期望 {res['sha256']}\n实际 {actual}")
            manifest = _load_manifest()
            manifest["resources"][resource_id].update(
                downloaded=True, local_path=dest, downloaded_at=_now())
            _save_manifest(manifest)
            return dest
        except Exception as e:
            last_err = e
    raise RuntimeError(f"下载 {res['name']} 失败(镜像与官方源都试过):{last_err}")


def _download_file(url: str, dest: str, progress_callback=None) -> None:
    """单文件流式下载;中断/失败删除半截文件,避免下次被'文件已存在'骗过"""
    try:
        resp = requests.get(url, stream=True, timeout=30)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        done = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                f.write(chunk)
                done += len(chunk)
                if progress_callback:
                    progress_callback(done, total)
    except Exception:
        if os.path.exists(dest):
            try:
                os.remove(dest)
            except OSError:
                pass
        raise


def _now() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    # 手动运行:python model_registry.py 列出资源状态
    for rid, info in list_resources().items():
        state = "已下载 ✓" if is_downloaded(rid) else "未下载"
        print(f"[{state}] {rid} — {info['name']} ({info['size']/1024/1024:.1f} MB)")
