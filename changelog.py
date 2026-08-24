# -*- coding: utf-8 -*-
"""
「更新日志」页面的数据源:从 GitHub 仓库拉取 CHANGELOG.md → 结构化更新日志 → 展示用 HTML。

CHANGELOG.md 采用 Keep a Changelog + 语义化版本,结构大致为:

    # 更新日志(CHANGELOG)
    ## [v0.2.1] - 2026-08-23
    ### 🧠 AI 助手
    - **真正的多轮记忆**:历史消息全部传给模型
    ### ⚡ 性能
    - 下载并行化
    ---
    ## [未发布 / Unreleased]
    ### 规划
    - ...

数据源:从 GitHub 仓库拉取 CHANGELOG.md(不依赖本地文件),失败时由调用方
显示错误/重试态,保证「我的版本」更新日志页始终用的是线上最新内容。

本模块只负责解析与排版,不依赖 Qt 之外的界面层。
"""
import base64
import html
import os
import re

import requests

import paths

REPO = "erfanyo/Agent_Minecraft_Launcher"
# GitHub Contents API:返回 CHANGELOG.md 的 base64 内容(不依赖默认分支名)
GITHUB_CHANGELOG_API = f"https://api.github.com/repos/{REPO}/contents/CHANGELOG.md"

CHANGELOG_PATH = os.path.join(paths.BASE_DIR, "CHANGELOG.md")

_HEADERS = {"User-Agent": "AgentMinecraftLauncher-Updater/0.2.1",
            "Accept": "application/vnd.github.v3+json"}

# 版本标题:## [v0.2.1] - 2026-08-23   或   ## [未发布 / Unreleased]
_HEAD_RE = re.compile(r"^##\s+\[?(.+?)\]?\s*(?:-\s*(.*))?$")
# 分组标题:### 🧠 AI 助手
_GROUP_RE = re.compile(r"^###\s+(.+)$")
# 加粗: **文本**
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def parse_changelog(path: str = CHANGELOG_PATH) -> list:
    """解析 CHANGELOG.md,返回 [{version, date, groups:[{title, items:[str]}]}]。

    解析失败或文件不存在时返回空列表(更新日志页面不至于崩,只是空白)。
    """
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return []
    return parse_changelog_text(text)


def parse_changelog_text(text: str) -> list:
    """把 CHANGELOG.md 原文解析为结构化列表(与文件路径无关,供在线内容复用)。"""
    entries = []
    cur = None        # 当前版本条目
    cur_group = None  # 当前分组
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        m = _HEAD_RE.match(line)
        if m:
            if cur:
                entries.append(cur)
            cur = {"version": m.group(1).strip() or "未发布",
                   "date": (m.group(2) or "").strip(), "groups": []}
            cur_group = None
            continue

        g = _GROUP_RE.match(line)
        if g:
            if cur is None:  # 标题之前就出现了 ###(异常兜底)
                cur = {"version": "未发布", "date": "", "groups": []}
                entries.append(cur)
            cur_group = {"title": g.group(1).strip(), "items": []}
            cur["groups"].append(cur_group)
            continue

        if cur is None:
            continue
        if line.startswith("- "):  # 条目
            if cur_group is None:  # 直接紧跟版本号的条目(没有 ### 分组)
                cur_group = {"title": "", "items": []}
                cur["groups"].append(cur_group)
            cur_group["items"].append(line[2:].strip())

    if cur:
        entries.append(cur)
    return entries


def fetch_from_github(timeout: int = 15) -> str:
    """从 GitHub 拉取 CHANGELOG.md 原文(Contents API,base64 解码)。

    成功返回文本;失败(网络/非 200/无内容)抛异常,由调用方决定降级。
    """
    resp = requests.get(GITHUB_CHANGELOG_API, headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    content = data.get("content") or ""
    if data.get("encoding") == "base64":
        content = base64.b64decode(content).decode("utf-8", errors="replace")
    if not content.strip():
        raise OSError("GitHub CHANGELOG.md 为空")
    return content


def load_changelog(timeout: int = 15) -> list:
    """只从 GitHub 拉取更新日志(不依赖本地 CHANGELOG.md)。

    返回结构化列表;拉取失败(离线/非 200/空)抛异常,由调用方显示错误/重试态。
    """
    try:
        return parse_changelog_text(fetch_from_github(timeout=timeout))
    except Exception:
        raise


def _inline(text: str) -> str:
    """把条目文本转成安全 HTML:转发义 + 把 **xx** 转成 <b>xx</b>。"""
    return _BOLD_RE.sub(r"<b>\1</b>", html.escape(text))


def changelog_html(entries: list | None = None) -> str:
    """把解析结果排成一段可在 QTextBrowser 里显示的 HTML。

    entries 缺省时重新从 GitHub 拉取。若仍然为空(拉取失败/网络不可用),
    返回一段说明文案,保证「更新日志」页始终有内容可读。
    """
    if entries is None:
        entries = parse_changelog_text(fetch_from_github())
    if not entries:
        return "<p style='color:#888888'>未找到更新日志(GitHub 拉取失败或为空)。</p>"

    parts = ['<html><body style="font-family:Sans-Serif; font-size:13px; color:inherit;">']
    for entry in entries:
        title = _inline(entry["version"])
        date = _inline(entry["date"]) if entry["date"] else ""
        parts.append(
            '<h2 style="margin:6px 0 4px; padding-top:14px; '
            'border-top:1px solid #555; font-size:18px;">'
            f"<span style='color:#5B8DEF;'>{title}</span>"
            + (f" <span style='color:#999; font-size:12px; font-weight:normal;'>{date}</span>" if date else "")
            + "</h2>")
        if entry["groups"]:
            parts.append("<ul style='margin:0 0 6px; padding-left:18px;'>")
            for group in entry["groups"]:
                if group["title"]:
                    parts.append(
                        f"<li style='margin-top:6px; font-weight:bold; color:#c9d7ee;'>"
                        f"{_inline(group['title'])}</li>")
                    parts.append("<ul style='margin:2px 0 6px; padding-left:16px;'>")
                    for item in group["items"]:
                        parts.append(f"<li style='margin:2px 0;'>{_inline(item)}</li>")
                    parts.append("</ul>")
                else:
                    for item in group["items"]:
                        parts.append(f"<li style='margin:2px 0;'>{_inline(item)}</li>")
            parts.append("</ul>")
        else:
            # 没有 ### 分组,直接列出条目
            parts.append("<ul style='margin:0 0 6px; padding-left:18px;'>")
            for group in entry["groups"]:
                for item in group["items"]:
                    parts.append(f"<li style='margin:2px 0;'>{_inline(item)}</li>")
            parts.append("</ul>")
    parts.append("</body></html>")
    return "".join(parts)
