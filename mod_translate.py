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

from paths import cache_dir  # 统一路径访问层

CACHE_DIR = cache_dir("translations")
CACHE_FILE = os.path.join(CACHE_DIR, "translations.json")
MAX_ENTRIES = 2000            # 缓存条目上限,超出丢最旧的(防无限膨胀)
SHORT_TEXT_LEN = 240          # ≤ 此长度视为短文本 → 高置信度

# 目标语言代码 → 显示名(中文→X 机翻用)
_LANG_NAME = {
    "en": "英语 English", "fr": "法语 Français", "es": "西班牙语 Español",
    "ru": "俄语 Русский", "ar": "阿拉伯语 العربية", "ja": "日语 日本語", "ko": "韩语 한국어",
}

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


def translation_source() -> str:
    """当前描述翻译来源；独立于聊天策略，默认本地以避免意外消耗云端额度。"""
    try:
        from settings import load_settings
        return "cloud" if load_settings().get("ai_mod_translate_source") == "cloud" else "local"
    except Exception:
        return "local"


def model_cache_version() -> str:
    """当前模型指纹(缓存失效键):manifest 顶层版本 + 资源 model_version/quant/sha256 前 12 位。
    清单版本号变更 / 模型资源定义变更 → 指纹变 → 缓存整批作废。"""
    try:
        import model_registry
        if translation_source() == "cloud":
            from settings import load_settings
            s = load_settings()
            return "cloud|" + "|".join(str(s.get(k, "")) for k in
                                         ("ai_cloud_provider", "ai_cloud_base_url", "ai_cloud_model"))
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


def _external_config() -> tuple:
    """读外部 OpenAI 兼容引擎设置(如 LM Studio 的 9B):(base, model)。
    设置键 ai_local_mode(内置查 'lmstudio'/'ollama')+ ai_local_endpoint / ai_local_model;
    非 lmstudio 且无 endpoint → 返回 ('','') 用内置 llama-server。"""
    try:
        from settings import load_settings
        s = load_settings()
        mode = (s.get("ai_local_mode") or "builtin")
        base = (s.get("ai_local_endpoint") or "").strip()
        # 外部模型名单独存 ai_external_model(与 ai_local_model 本地 GGUF 分离,避免撞字段爆内存)
        model = (s.get("ai_external_model") or "").strip()
        if mode in ("lmstudio", "ollama"):
            if not model:
                # 没单独存模型名 → 从 LM Studio 探测一个(通常 qwen 9B)
                from settings import load_settings as _ls
                _b, _m = _probe_local_lmstudio()
                base = base or _b
                model = _m
            if base and model:
                return base, model
        if (base and model):
            return base, model
        # 防御:显式 builtin 但本地 LM Studio(1234)可达且有较大模型 → 优先外部,
        # 避免自起 llama-server 加载大模型爆内存(用户常手动用 LM Studio 跑大模型)。
        base, model = _probe_local_lmstudio()
        if base and model:
            return base, model
        return "", ""
    except Exception:
        return "", ""


def _probe_local_lmstudio() -> tuple:
    """探测本地 LM Studio(常见端口 1234 / 11434):返回 (base, model)。
    仅当端口可达且加载了非内置 0.8B 的模型时才用(否则仍回落内置)。"""
    import requests
    for port, scheme in ((1234, "http"), (11434, "http")):
        base = f"{scheme}://127.0.0.1:{port}"
        try:
            r = requests.get(base + "/v1/models", timeout=2)
            if r.status_code != 200:
                continue
            models = [m.get("id", "") for m in r.json().get("data", []) if m.get("id")]
            # 排除内置小模型,优先选一个非 0.8B 的大模型(如 qwen3.5-9b)
            big = [m for m in models if "0.8" not in m and "0.8b" not in m.lower()]
            if big:
                # 优先 qwen 9b 类
                pick = next((m for m in big if "9b" in m.lower() or "9b" in m), big[0])
                return base, pick
        except Exception:
            continue
    return "", ""


def get_translation_engine():
    """返回可用的 GrammarToolEngine(懒加载单例)。
    - 若设置指定了外部 OpenAI 兼容引擎(LM Studio 9B)→ 用外部,不起 llama-server;
    - 否则若 8090 已有健康 llama-server → 复用;否则检查模型已下载 → start();否则 TranslationUnavailable"""
    global _engine
    with _engine_lock:
        if _engine is None:
            from local_ai import GrammarToolEngine
            base, model = _external_config()
            if base and model:
                _engine = GrammarToolEngine(external_base=base, external_model=model)
            else:
                _engine = GrammarToolEngine()
        if _engine.is_external:
            # 外部引擎:探一下连通性,通了就直接用;不通抛异常(优雅降级)
            try:
                import requests
                url = _engine.external_base.rstrip("/")
                if not url.endswith("/v1"):
                    url = url + "/v1"
                requests.get(url + "/models", timeout=5).raise_for_status()
                return _engine
            except Exception as e:
                raise TranslationUnavailable(f"外部翻译引擎不可用:{type(e).__name__}: {e}")
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


def _translate_with_cloud(text: str, timeout: int, target_lang: str, target_name: str) -> str:
    """用用户已配置的 OpenAI 兼容云端模型翻译；不新建中转、不保存密钥。"""
    from settings import load_settings
    import requests
    s = load_settings()
    base = (s.get("ai_cloud_base_url") or "").rstrip("/")
    key = (s.get("ai_cloud_api_key") or "").strip()
    model = (s.get("ai_cloud_model") or "").strip()
    if not (base and key and model):
        raise TranslationUnavailable("云端翻译未配置：请先在设置 → AI 助手填写云端接口、密钥和模型。")
    target = target_name or ("简体中文" if target_lang == "zh" else target_lang)
    prompt = (f"把下面 Minecraft Mod 描述翻译成{target}。只输出译文，不解释；保留 Mod 名、版本号、URL、"
              "配置项和代码标识。\n\n" + text)
    try:
        r = requests.post(base + "/chat/completions", headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
                          json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 1024},
                          timeout=(15, timeout))
        r.raise_for_status()
        return (r.json()["choices"][0]["message"].get("content") or "").strip()
    except Exception as e:
        raise TranslationUnavailable(f"云端翻译失败：{type(e).__name__}: {e}") from e


# ---------------- 对外纯函数 ----------------
def translate_text(text: str, slug: str = "", field: str = "description",
                   engine=None, timeout: int = 90,
                   target_lang: str = "", target_name: str = "") -> dict:
    """翻译(缓存优先)。默认英→中;target_lang 指定目标语言代码(zh/en/fr/es/ru/ar/ja/ko…)
    时做「中文→目标语言」机翻(用于语言包生成)。纯函数、与 UI 解耦。

    参数:
      text    待翻译文本
      slug    Mod slug(缓存 key 用;纯文本调用留空)
      field   字段名(缓存 key 用)
      engine  可选注入引擎(测试用);None = 模块级懒加载单例
      timeout 推理超时(秒)
      target_lang 目标语言代码(留空=英→中默认);非空且 text 含中文 → 中文→target
      target_name 目标语言显示名(如 法语/English;留空自动映射)

    返回 dict: {translated, text, confidence, machine, cached, source, ...}
    失败抛 TranslationUnavailable;要"永不抛异常"用 translate_text_safe()。"""
    text = (text or "").strip()
    base = {"translated": False, "text": text, "confidence": "low",
            "machine": False, "cached": False, "glossary_hit": False}

    if not enabled():
        base["source"] = "disabled"
        return base
    if not text:
        base["source"] = "original"
        return base

    # 目标语言映射(中文→X 用;留空=默认英→中)
    target_lang = (target_lang or "").strip()
    if target_lang:
        tname = target_name or _LANG_NAME.get(target_lang, target_lang)
        # 中文→目标语言:源必须是中文(无中文则不是我们要翻的)
        if not _has_cjk(text):
            base["source"] = "not_cn"
            return base
    else:
        tname = "简体中文"
        # 默认英→中:源已是中文则无需翻译
        if _has_cjk(text):
            base["source"] = "already_cn"
            return base

    key = _cache_key(slug or f"mtz|{target_lang}", field, text)
    with _store_lock:
        store = _load_store()
        hit = store["entries"].get(key)
    if hit:
        return {"translated": True, "text": hit.get("t", text),
                "confidence": hit.get("c", "low"), "machine": True,
                "cached": True, "source": "cache",
                "glossary_hit": bool(hit.get("g", False))}

    try:
        if engine is None and translation_source() == "cloud":
            output = _translate_with_cloud(text, timeout, target_lang or "zh", tname)
        else:
            eng = engine if engine is not None else get_translation_engine()
            g = {}
            if not target_lang:
                from local_ai import MC_GLOSSARY
                g = MC_GLOSSARY
            output = eng.translate(text, timeout=timeout, glossary=g,
                                   target_lang=target_lang or "zh", target_name=tname)
    except TranslationUnavailable:
        raise
    except Exception as e:
        raise TranslationUnavailable(f"翻译失败:{type(e).__name__}: {e}") from e

    gh = False
    conf = _confidence(text, output, gh) if not target_lang else "high"
    # 空输出不落缓存(避免把"空翻译"污染缓存,下次命中空)
    if output and output.strip():
        with _store_lock:
            store = _load_store()
            store["entries"][key] = {"t": output, "c": conf, "g": gh,
                                     "ts": _now_ts()}
            _save_store(store)
    return {"translated": True, "text": output, "confidence": conf,
            "machine": True, "cached": False, "source": "model",
            "glossary_hit": gh}


def translate_text_safe(text: str, slug: str = "", field: str = "description",
                        engine=None, timeout: int = 90,
                        target_lang: str = "", target_name: str = "") -> dict:
    """永不抛异常的翻译入口:失败直接返回原文(降级),供 UI/工具层直接调用。"""
    try:
        return translate_text(text, slug=slug, field=field,
                              engine=engine, timeout=timeout,
                              target_lang=target_lang, target_name=target_name)
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
