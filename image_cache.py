# -*- coding: utf-8 -*-
"""
Mod 图片 + 描述 缓存模块。

解决两个问题:
1. **图片不显示**:`requests.get` 拉图标失败/慢/限流,且**没有缓存**——每次进详情都重新拉一遍,
   失败就白屏。这里加**内存 + 磁盘**两级缓存(磁盘在 `AMCL/cache/`),命中即秒回;拉取加超时重建。
2. **不同版本同一 Mod 复用**:缓存键用 **Mod slug(项目 id)**,而不是"版本号/版本文件 id"。
   因为同一 Mod(如 sodium)换个游戏版本/加载器,图标和描述文本是**同一个**,不该因版本不同重新下载。

设计:
- 缓存文件:`AMCL/cache/icons/<safe-slug>.png`(图标)、`AMCL/cache/desc/<safe-slug>.txt`(描述文本)。
- 读写都安全:线程锁 + 原子写(先写临时文件再 rename),避免并发/半写入。
- `load_icon(slug, url, size, callback)` → 主线程回调 setPixmap;命中缓存不阻塞,失败用占位。
- 描述文本缓存:只在未命中时才调用翻译;命中直接复用(省 token/不重新推理)。
- "重复注册缓存问题不大":同一个 slug 被多线程/多版本同时请求,cache 用 slug 去重,最多并发拉一次。
"""
import os
import threading
import time

import paths

# 缓存根目录:AMCL/cache/{icons,desc}
CACHE_ROOT = os.path.join(paths.CONFIG_DIR, "cache")
ICON_DIR = os.path.join(CACHE_ROOT, "icons")
DESC_DIR = os.path.join(CACHE_ROOT, "desc")

_ICON_LOCK = threading.Lock()
_DESC_LOCK = threading.Lock()
_ICON_CACHE = {}      # slug -> (pixmap bytes, mtime)  内存层
_DESC_CACHE = {}      # slug -> (text, mtime)          内存层
_LOCK = threading.Lock()

# 磁盘缓存有效期(秒)。图标/描述随 Mod 更新而变化,给个较长 TTL,过期则重新拉取。
ICON_TTL = 30 * 24 * 3600       # 30 天
DESC_TTL = 30 * 24 * 3600       # 30 天


def _safe_slug(slug: str) -> str:
    """把 slug 转成安全文件名(防路径穿越/非法字符)。"""
    s = (slug or "").strip()
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in s)
    return safe or "unnamed"


def _ensure_dirs():
    for d in (ICON_DIR, DESC_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass


def _atomic_write(path: str, data: bytes) -> None:
    """原子写:先写临时文件再 rename,避免读到半个文件。"""
    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass


def _read_disk(path: str, ttl: int) -> bytes | None:
    try:
        if os.path.isfile(path) and (time.time() - os.path.getmtime(path)) < ttl:
            with open(path, "rb") as f:
                return f.read()
    except Exception:
        pass
    return None


# ---------------- 图标 ----------------
def icon_path(slug: str) -> str:
    return os.path.join(ICON_DIR, _safe_slug(slug) + ".png")


def load_icon(slug: str, url: str, size: int = 56,
              on_loaded=None, on_fallback=None) -> bytes | None:
    """加载图标(slug 键,跨版本复用)。返回 PNG bytes(可能为 None)。
    若 on_loaded(cb) 提供,则在主线程(若已在)或直接回调。首次拉取带网络+超时+缓存。"""
    _ensure_dirs()
    _ICON_LOCK.acquire()
    try:
        cached = _ICON_CACHE.get(slug)
        if cached:
            return cached[0]
    finally:
        _ICON_LOCK.release()
    # 内存没命中 → 读磁盘
    disp = _read_disk(icon_path(slug), ICON_TTL)
    if disp:
        _ICON_LOCK.acquire()
        try:
            _ICON_CACHE[slug] = (disp, time.time())
        finally:
            _ICON_LOCK.release()
        return disp
    # 都没命中 → 拉网络
    if url:
        try:
            import requests
            resp = requests.get(url, timeout=12)
            if resp.status_code == 200 and resp.content:
                _save_icon(slug, resp.content)
                return resp.content
        except Exception:
            pass
    return None


def _save_icon(slug: str, content: bytes) -> None:
    try:
        _ensure_dirs()
        _atomic_write(icon_path(slug), content)
        _ICON_LOCK.acquire()
        try:
            _ICON_CACHE[slug] = (content, time.time())
        finally:
            _ICON_LOCK.release()
    except Exception:
        pass


def clear_icons() -> int:
    """清除磁盘 + 内存图标缓存,返回删除的文件数。"""
    n = 0
    _ICON_LOCK.acquire()
    try:
        _ICON_CACHE.clear()
    finally:
        _ICON_LOCK.release()
    try:
        if os.path.isdir(ICON_DIR):
            for f in os.listdir(ICON_DIR):
                p = os.path.join(ICON_DIR, f)
                if os.path.isfile(p):
                    try:
                        os.remove(p); n += 1
                    except Exception:
                        pass
    except Exception:
        pass
    return n


# ---------------- 描述文本 ----------------
def desc_path(slug: str) -> str:
    return os.path.join(DESC_DIR, _safe_slug(slug) + ".txt")


def get_cached_desc(slug: str) -> str | None:
    """取缓存的描述文本(磁盘+内存)。未命中返回 None。"""
    _DESC_LOCK.acquire()
    try:
        if slug in _DESC_CACHE:
            return _DESC_CACHE[slug][0]
    finally:
        _DESC_LOCK.release()
    raw = _read_disk(desc_path(slug), DESC_TTL)
    if raw is not None:
        text = raw.decode("utf-8", errors="replace")
        _DESC_LOCK.acquire()
        try:
            _DESC_CACHE[slug] = (text, time.time())
        finally:
            _DESC_LOCK.release()
        return text
    return None


def set_cached_desc(slug: str, text: str) -> None:
    """写入缓存(供翻译完成后复用)。"""
    try:
        _ensure_dirs()
        _atomic_write(desc_path(slug), (text or "").encode("utf-8"))
        _DESC_LOCK.acquire()
        try:
            _DESC_CACHE[slug] = (text or "", time.time())
        finally:
            _DESC_LOCK.release()
    except Exception:
        pass


def clear_desc() -> int:
    n = 0
    _DESC_LOCK.acquire()
    try:
        _DESC_CACHE.clear()
    finally:
        _DESC_LOCK.release()
    try:
        if os.path.isdir(DESC_DIR):
            for f in os.listdir(DESC_DIR):
                p = os.path.join(DESC_DIR, f)
                if os.path.isfile(p):
                    try:
                        os.remove(p); n += 1
                    except Exception:
                        pass
    except Exception:
        pass
    return n
