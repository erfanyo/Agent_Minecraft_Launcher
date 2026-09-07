# -*- coding: utf-8 -*-
"""Local, privacy-conscious cloud tool-call logs for later training-data curation."""
from __future__ import annotations

import json
import os
from datetime import datetime

from paths import data_dir
from log_privacy import redact

def _redact(value, key: str = ""):
    return redact(value, key=key)


def _user_text(messages: list) -> str:
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [str(i.get("text", "")) for i in content
                     if isinstance(i, dict) and i.get("type") == "text"]
            images = sum(1 for i in content if isinstance(i, dict) and i.get("type") == "image_url")
            return "\n".join(parts) + (f"\n[附带图片 {images} 张]" if images else "")
    return ""


def append(settings: dict, messages: list, tool_calls: list[dict], reply: str) -> None:
    """Append a JSONL sample only when the user enabled local training logs."""
    provider = str(settings.get("ai_provider", "")).lower()
    if (not settings.get("ai_cloud_tool_log", True) or not tool_calls or
            provider in {"local_builtin", "ollama", "lmstudio"}):
        return
    row = {
        "schema": "amcl.cloud-tool-call.v1",
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "provider": provider,
        "model": settings.get("ai_model", ""),
        "user": _user_text(messages),
        "tool_calls": tool_calls,
        "reply": str(reply or ""),
    }
    row = redact(row, settings)
    path = os.path.join(data_dir("ai_training"), "cloud_tool_calls.jsonl")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
