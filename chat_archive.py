# -*- coding: utf-8 -*-
"""
AI 聊天记录·储存与归档:把当前对话存成一份会话,支持从归档快速恢复。

- 存档目录: `AMCL/chat_archive/`(启动器私有数据,随 AMCL 走)。
- 每份会话 = 一个 <时间戳>.json,含:
    {title, created_at, chat_messages(喂给LLM的消息), entries(展示流)}
- 恢复 = 读该 json → 替换 当前对话的 _chat_messages / _entries → 重绘。
- 快速恢复:归档列表点一项 → 立即载入,可继续提问(历史带工具过程)。
"""
import json
import os
import time

from paths import CONFIG_DIR

ARCHIVE_DIR = os.path.join(CONFIG_DIR, "chat_archive")


def _ensure_dir():
    try:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
    except OSError:
        pass


def _safe_name(title: str) -> str:
    s = (title or "").strip().replace("\n", " ")[:40] or "对话"
    out = "".join(ch if ch.isalnum() or ch in " ._-" else "_" for ch in s).strip()
    return out or "对话"


def save_session(chat_messages: list, entries: list, title: str = "") -> dict:
    """把当前对话存成一份会话。返回 {ok, path, title}。"""
    _ensure_dir()
    title = title or _default_title(chat_messages, entries)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(ARCHIVE_DIR, f"{ts}-{_safe_name(title)}.json")
    data = {
        "title": title,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chat_messages": chat_messages or [],
        "entries": _serialize_entries(entries or []),
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        return {"ok": True, "path": path, "title": title}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def list_sessions() -> list:
    """归档列表(最新在前):[{title, created_at, path, count}]。"""
    _ensure_dir()
    out = []
    for f in sorted(os.listdir(ARCHIVE_DIR), reverse=True):
        if not f.endswith(".json"):
            continue
        p = os.path.join(ARCHIVE_DIR, f)
        try:
            d = json.load(open(p, encoding="utf-8"))
            out.append({
                "title": d.get("title", f),
                "created_at": d.get("created_at", ""),
                "path": p,
                "count": len(d.get("entries", [])),
            })
        except Exception:
            continue
    return out


def load_session(path: str) -> dict:
    """读取一份会话。返回 {ok, title, chat_messages, entries} 或 {ok:False,error}。"""
    try:
        d = json.load(open(path, encoding="utf-8"))
        return {"ok": True, "title": d.get("title", ""),
                "chat_messages": d.get("chat_messages", []),
                "entries": _deserialize_entries(d.get("entries", []))}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def delete_session(path: str) -> bool:
    try:
        if os.path.isfile(path):
            os.remove(path)
            return True
    except Exception:
        pass
    return False


def _default_title(chat_messages, entries) -> str:
    """取第一条用户消息前 20 字做标题。"""
    for e in entries or []:
        if e and e[0] == "user":
            return (e[1] or "对话")[:20]
    for m in chat_messages or []:
        if m.get("role") == "user":
            return (m.get("content", "") or "对话")[:20]
    return "对话"


def _serialize_entries(entries: list) -> list:
    """把展示流条目转成可 JSON 的结构(丢弃不便序列化的对象)。"""
    out = []
    for e in entries:
        if not isinstance(e, tuple) or not e:
            continue
        kind = e[0]
        if kind in ("system", "user", "ai"):
            out.append({"kind": kind, "text": str(e[1])})
        elif kind == "tool" and len(e) == 5:
            # ("tool", id, name, args, result)
            out.append({"kind": "tool", "id": e[1], "name": e[2],
                        "args": e[3], "result": e[4]})
    return out


def _deserialize_entries(data: list) -> list:
    out = []
    for it in data or []:
        kind = it.get("kind")
        if kind in ("system", "user", "ai"):
            out.append((kind, it.get("text", "")))
        elif kind == "tool":
            out.append(("tool", it.get("id", 0), it.get("name", ""),
                        it.get("args", {}), it.get("result", "")))
    return out
