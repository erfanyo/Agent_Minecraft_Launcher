# -*- coding: utf-8 -*-
"""
Mod 描述翻译(本地 AI 英→中):缓存 + 置信度标记 + 失败降级。

设计(任务书-本地AI翻译.md W2/W5):
- 复用 `local_ai.GrammarToolEngine.chat()`(无 grammar 的自由对话通道)做翻译,
  翻译专用 system prompt 注入 MC 标准译名术语表(MC_GLOSSARY,见 local_ai.py)。
- 缓存 `AMCL/cache/translations/translations.json`:
  * key = mod_slug + 字段 + 源文本短哈希(文本变了自然换 key,不吐旧译文)
  * 缓存整体绑定模型版本(manifest 版本号/资源 sha256 指纹)——版本变了整批作废
  * 幂等 + 线程安全(RLock;翻译在后台线程跑,多个线程可能同时读写)
- 置信度:短文本/术语表命中 = high;模型输出可疑(回显原文/无中文/过长)= low
  → 调用方据此标"机翻仅供参考"。
- 失败(模型未下载/引擎启动失败/超时/异常)→ 抛 TranslationUnavailable,
  `translate_text_safe()` 永不抛异常、直接返回原文(UI 降级用)。
- W5:`translate_text(text)` 是与 UI 解耦的纯函数,供"游戏内 AI 翻译"任务复用。

文件放置遵循 AI规划 §11:全部缓存落 AMCL/cache/translations/,不散落系统目录。
"""
import hashlib
import json
import os
import threading

from paths import CONFIG_DIR  # AMCL 目录

CACHE_DIR = os.path.join(CONFIG_DIR, "cache", "translations")
CACHE_FILE = os.path.join(CACHE_DIR, "translations.json")
MAX_ENTRIES = 2000            # 缓存条目上限,超出丢最旧的(防无限膨胀)
SHORT_TEXT_LEN = 240          # ≤ 此长度视为短文本 → 高置信度

_store_lock = threading.RLock()   # 缓存读写锁(线程安全)
_engine = None                    # 模块级懒加载引擎单例
_engine_lock = threading.Lock()


class TranslationUnavailable(Exception):
    """翻译不可用(模型未下载/启动失败/超时/异常):调用方应优雅显示原文。"""


# ---------------- 设置 / 模型版本 ----------------
def enabled() -> bool:
    """ai_mod_translate 开关(默认开)"""
    try:
        from settings import load_settings
        return bool(load_settings().get("ai_mod_translate", True))
    except Exception:
        return True


def _active_model_id() -> str:
    try:
        from settings import load_settings
        mid = (load_settings().get("ai_local_model") or "").strip()
        if mid:
            return mid
    except Exception:
        pass
    from local_ai import DEFAULT_MODEL_ID
    return DEFAULT_MODEL_ID


def model_cache_version() -> str:
    """当前模型指纹(缓存失效键):manifest 顶层版本 + 资源 model_version/quant/sha256 前 12 位。
    清单版本号变更 / 模型资源定义变更 → 指纹变 → 缓存整批作废。"""
    try:
        import model_registry
        mid = _active_model_id()
        res = model_registry.RESOURCES.get(mid, {})
        manifest_ver = "?"
        try:
            m = model_registry._load_manifest()
            manifest_ver = str(m.get("version", "?"))
        except Exception:
            pass
        return "|".join([
            str(manifest_ver),
            str(res.get("model_version", "")),
            str(res.get("quant", "")),
            str(res.get("sha256", ""))[:12],
        ]) or "unknown"
    except Exception:
        return "unknown"


# ---------------- 缓存 ----------------
def _load_store() -> dict:
    """读缓存 store;模型版本对不上/文件损坏 → 全新 store(整批作废)。"""
    ver = model_cache_version()
    fresh = {"model_version": ver, "entries": {}}
    if not os.path.exists(CACHE_FILE):
        return fresh
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("model_version") == ver:
            entries = data.get("entries")
            if isinstance(entries, dict):
                fresh["entries"] = entries
    except Exception:
        pass
    return fresh


def _save_store(store: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    entries = store.get("entries", {})
    if len(entries) > MAX_ENTRIES:
        # 丢最旧的:按 ts 排序截断
        oldest = sorted(entries.items(), key=lambda kv: kv[1].get("ts", 0))
        for k, _ in oldest[:len(entries) - MAX_ENTRIES]:
            entries.pop(k, None)
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=1)
    except OSError:
        pass  # 缓存写失败不影响功能(下次重新翻译)


def _cache_key(slug: str, field: str, text: str) -> str:
    """key = mod_slug + 字段 + 源文本短哈希(文本变更自然换 key,不吐旧译文)。
    纯文本调用(slug 空)= 文本哈希 key,供游戏内翻译复用。"""
    h = hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:12]
    if slug:
        return f"{slug}|{field}|{h}"
    return f"t|{h}"


# ---------------- 置信度 / 降级 ----------------
def _has_cjk(text: str) -> bool:
    try:
        from mod_cn import has_cjk
        return has_cjk(text)
    except Exception:
        return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _glossary_hit(source: str, glossary: dict) -> bool:
    """源文本是否命中 MC 术语(命中 → 标准译名生效概率高 → 高置信度)"""
    low = source.lower()
    return any(k.lower() in low for k in glossary)


def _suspicious(output: str, source: str) -> bool:
    """模型输出可疑判定:回显原文 / 译文无中文 / 过长(疑似废话)"""
    out = (output or "").strip()
    if not out:
        return True
    if out == (source or "").strip():
        return True                       # 原样回显 = 没在翻译
    if not _has_cjk(out):
        return True                       # 译文里没有中文
    if len(out) > max(400, len(source or "") * 4):
        return True                       # 异常膨胀
    return False


def _confidence(source: str, output: str, glossary_hit: bool) -> str:
    """置信度:短文本/术语表命中且输出正常 = high;可疑输出 = low。"""
    if _suspicious(output, source):
        return "low"
    if len(source) <= SHORT_TEXT_LEN or glossary_hit:
        return "high"
    return "high" if _has_cjk(output) else "low"


# ---------------- 引擎(懒加载单例,复用已有 llama-server) ----------------
def _model_downloaded() -> bool:
    try:
        import model_registry
        return model_registry.is_downloaded(_active_model_id())
    except Exception:
        return False


def get_translation_engine():
    """返回可用的 GrammarToolEngine(懒加载单例)。
    - 若 8090 端口已有健康 llama-server(如 AI 对话框已启动)→ 直接复用,不起新进程
    - 否则检查模型已下载 → start()(启动失败/未下载 → TranslationUnavailable)"""
    global _engine
    with _engine_lock:
        if _engine is None:
            from local_ai import GrammarToolEngine
            _engine = GrammarToolEngine()
        try:
            import requests
            if requests.get(f"{_engine.base}/health", timeout=2).status_code == 200:
                return _engine        # 复用已有服务(含 AI 对话框起的)
        except Exception:
            pass
        if not _model_downloaded():
            raise TranslationUnavailable(
                "本地模型未下载(设置 → AI 助手 → 本地模型下载后可用)")
        try:
            _engine.start()
        except Exception as e:
            raise TranslationUnavailable(f"本地翻译引擎启动失败:{e}") from e
        return _engine


# ---------------- 对外纯函数 ----------------
def translate_text(text: str, slug: str = "", field: str = "description",
                   engine=None, timeout: int = 90) -> dict:
    """英→中翻译(缓存优先),纯函数、与 UI 解耦(W5 供游戏内翻译复用)。

    参数:
      text    待翻译文本(英文);已是中文则原样返回,不触发推理
      slug    Mod slug(缓存 key 用;纯文本调用留空)
      field   字段名(description / summary 等,缓存 key 用)
      engine  可选注入引擎(测试用);None = 模块级懒加载单例
      timeout 推理超时(秒)

    返回 dict:
      {translated, text(译文或原文), confidence(high/low), machine(是否机翻,
       True=需"机翻仅供参考"标注), cached, source(cache/model/original/
       already_cn/disabled), glossary_hit}

    失败(模型不可用/超时/异常)→ 抛 TranslationUnavailable;要"永不抛异常"
    用 translate_text_safe()(返回原文降级)。"""
    text = (text or "").strip()
    base = {"translated": False, "text": text, "confidence": "low",
            "machine": False, "cached": False, "glossary_hit": False}

    if not enabled():
        base["source"] = "disabled"
        return base
    if not text:
        base["source"] = "original"
        return base
    if _has_cjk(text):
        base["source"] = "already_cn"     # 本身就是中文,无需翻译
        return base

    key = _cache_key(slug, field, text)
    with _store_lock:
        store = _load_store()
        hit = store["entries"].get(key)
    if hit:
        return {"translated": True, "text": hit.get("t", text),
                "confidence": hit.get("c", "low"), "machine": True,
                "cached": True, "source": "cache",
                "glossary_hit": bool(hit.get("g", False))}

    eng = engine if engine is not None else get_translation_engine()
    try:
        from local_ai import MC_GLOSSARY
        output = eng.translate(text, timeout=timeout)
    except TranslationUnavailable:
        raise
    except Exception as e:
        raise TranslationUnavailable(f"翻译失败:{type(e).__name__}: {e}") from e

    gh = _glossary_hit(text, MC_GLOSSARY)
    conf = _confidence(text, output, gh)
    with _store_lock:
        store = _load_store()
        store["entries"][key] = {"t": output, "c": conf, "g": gh,
                                 "ts": _now_ts()}
        _save_store(store)
    return {"translated": True, "text": output, "confidence": conf,
            "machine": True, "cached": False, "source": "model",
            "glossary_hit": gh}


def translate_text_safe(text: str, slug: str = "", field: str = "description",
                        engine=None, timeout: int = 90) -> dict:
    """永不抛异常的翻译入口:失败直接返回原文(降级),供 UI/工具层直接调用。"""
    try:
        return translate_text(text, slug=slug, field=field,
                              engine=engine, timeout=timeout)
    except TranslationUnavailable as e:
        return {"translated": False, "text": (text or "").strip(),
                "confidence": "low", "machine": False, "cached": False,
                "source": "failed", "glossary_hit": False,
                "error": str(e)}


def _now_ts() -> float:
    import time
    return time.time()


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"模型指纹:{model_cache_version()}")
    print(f"缓存目录:{CACHE_DIR}")
    print(f"开关:{enabled()}")
    print("用法:from mod_translate import translate_text, translate_text_safe")
