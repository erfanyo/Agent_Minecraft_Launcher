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

from paths import data_dir

ARCHIVE_DIR = data_dir("chat_archive")


def _ensure_dir():
    try:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
    except OSError:
        pass


def _safe_name(title: str) -> str:
    s = (title or "").strip().replace("\n", " ")[:40] or "对话"
    out = "".join(ch if ch.isalnum() or ch in " ._-" else "_" for ch in s).strip()
    return out or "对话"


def save_session(chat_messages: list, entries: list, title: str = "",
                 instance_id: str = "") -> dict:
    """把当前对话存成一份会话。返回 {ok, path, title}。"""
    _ensure_dir()
    title = title or _default_title(chat_messages, entries)
    ts = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000_000:09d}"
    path = os.path.join(ARCHIVE_DIR, f"{ts}-{_safe_name(title)}.json")
    data = {
        "title": title,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "instance_id": instance_id or "",
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
                "instance_id": d.get("instance_id", ""),
            })
        except Exception:
            continue
    return out


def load_session(path: str) -> dict:
    """读取一份会话。返回 {ok, title, chat_messages, entries} 或 {ok:False,error}。"""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return {"ok": True, "title": d.get("title", ""),
                "instance_id": d.get("instance_id", ""),
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
    """取第一条用户消息前 20 字做标题。兼容 ChatEntry 与旧元组。"""
    for e in entries or []:
        kind = getattr(e, "kind", None) if not isinstance(e, tuple) else (
            e[0] if e else None)
        if kind == "user":
            text = e.text if hasattr(e, "text") else (e[1] or "")
            return (text or "对话")[:20]
    for m in chat_messages or []:
        if m.get("role") == "user":
            return (m.get("content", "") or "对话")[:20]
    return "对话"


def _serialize_entries(entries: list) -> list:
    """把展示流条目转成可 JSON 的结构。

    接受 ``chat_view.ChatEntry``(当前格式)与旧的裸元组(历史归档),统一输出
    ``{"kind": ...}`` 字典,因此新写入的归档不再依赖元组位置。
    """
    from chat_view import ChatEntry
    out = []
    for e in entries or []:
        entry = ChatEntry.from_any(e)
        if entry is not None:
            out.append(entry.to_dict())
    return out


def _deserialize_entries(data: list) -> list:
    """读回归档条目,统一成 ``chat_view.ChatEntry``(渲染层直接可用)。"""
    from chat_view import coerce_entries
    return coerce_entries(data or [])
