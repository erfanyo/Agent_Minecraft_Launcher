# -*- coding: utf-8 -*-
"""对话流的「渲染层」:纯函数 + 一个只负责显示的 QTextBrowser 子类。

**为什么单独拆一层**:原先这段逻辑以 ``_render_all()`` 的形式内联在
``assistant.py`` 的 ``AIChatDock`` 里——每次重绘都手拼 f-string HTML,样式与
编排纠缠、无法单测、加一种新展示形式就得往那个 if 链里再塞一个分支。

拆开后:

- ``ChatEntry``      一次展示的**数据**(替代裸元组 ``("tool", id, name, ...)``)
- ``render_entry``   纯函数:entry + tokens + 展开状态 → HTML 片段(**不碰 Qt,可单测**)
- ``render_table``   结构化表格 → HTML(``<table border cellpadding cellspacing>``,
                     QTextBrowser 只认这套富文本子集,不认 CSS 边框)
- ``table_to_text``  同一份表格数据 → 纯文本(给 AI/日志用,复用同一来源不重复实现)
- ``ChatView``       QTextBrowser 子类:``set_entries()`` 负责显示

设计约束(与项目既有约定一致):
1. 本模块**不产生硬编码色值**(``ui_color_scan.py`` 会扫描并判为待迁 token),
   所有颜色经 ``tokens`` 传入,默认由 ``ui_style`` 提供。
2. 本模块**不反向引用** ``assistant`` 的 ``TOOLS``/``executor``/线程状态。
3. 链接协议(``tool:<id>`` / ``ai:<index>``)保持不变,点击由外层 ``ChatView``
   回调转交,避免渲染层知道业务语义。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import html
from typing import Any, Callable, Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTextBrowser

from ui_style import (accent_color, current_color, muted_color, success_color,
                      text_color, warning_color, danger_color)


# ---------------- 数据模型 ----------------
@dataclass
class ChatEntry:
    """对话流里的一条展示条目。

    ``kind`` 决定渲染分支;其余字段按 kind 取用(见 :func:`render_entry`)。
    提供 ``to_dict`` / ``from_any`` 以便 ``chat_archive`` 持久化,并兼容旧的
    裸元组格式(老归档里的 ``entries`` 仍是元组列表,必须能读回来)。
    """

    kind: str
    text: str = ""
    # kind == "tool"
    tool_id: int = 0
    name: str = ""
    args: dict = field(default_factory=dict)
    result: str = ""
    # kind == "table"
    title: str = ""
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)

    # ---- 序列化 ----
    def to_dict(self) -> dict:
        data: dict[str, Any] = {"kind": self.kind}
        if self.kind == "tool":
            data.update(id=self.tool_id, name=self.name, args=self.args,
                        result=self.result)
        elif self.kind == "table":
            data.update(title=self.title, columns=list(self.columns),
                        rows=[list(r) for r in self.rows])
        else:
            data["text"] = self.text
        return data

    @classmethod
    def from_any(cls, value) -> "ChatEntry | None":
        """接受 ChatEntry / dict / 旧元组,统一成 ChatEntry。无法识别返回 None。"""
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            kind = value.get("kind")
            if kind == "tool":
                return cls(kind="tool", tool_id=int(value.get("id") or 0),
                           name=str(value.get("name") or ""),
                           args=value.get("args") or {},
                           result=str(value.get("result") or ""))
            if kind == "table":
                return cls(kind="table", title=str(value.get("title") or ""),
                           columns=list(value.get("columns") or []),
                           rows=[list(r) for r in (value.get("rows") or [])])
            if kind in ("system", "user", "ai"):
                return cls(kind=kind, text=str(value.get("text") or ""))
            return None
        if isinstance(value, tuple) and value:
            kind = value[0]
            if kind in ("system", "user", "ai") and len(value) >= 2:
                return cls(kind=kind, text=str(value[1]))
            if kind == "tool" and len(value) >= 5:
                return cls(kind="tool", tool_id=int(value[1]), name=str(value[2]),
                           args=value[3] or {}, result=str(value[4]))
        return None

    @property
    def plain_text(self) -> str:
        """该条目的纯文本形态(用于存档标题/日志/查询)。"""
        if self.kind == "tool":
            return f"[工具 {self.name}] {self.result}"
        if self.kind == "table":
            return table_to_text(self.title, self.columns, self.rows)
        return self.text


def coerce_entries(values: Iterable) -> list[ChatEntry]:
    """把混合来源(旧元组/新数据类/dict)的序列统一成 ChatEntry 列表。"""
    out = []
    for value in values or []:
        entry = ChatEntry.from_any(value)
        if entry is not None:
            out.append(entry)
    return out


# ---------------- 主题 token ----------------
def default_tokens() -> dict:
    """当前主题下的渲染色。集中在一处,便于测试注入固定值。"""
    return {
        "text": text_color(),
        "muted": muted_color(),
        "accent": accent_color(),
        "success": success_color(),
        "warning": warning_color(),
        "danger": danger_color(),
        "user_bg": current_color("sel_bg"),
        "ai_bg": current_color("bg1"),
        "border": current_color("btn_border"),
        "row_alt": current_color("btn_bg"),
    }


# ---------------- 纯函数 ----------------
def esc(text: str) -> str:
    """HTML 转义 + 换行转 <br>(富文本里 \\n 会被当空白吞掉)。"""
    return html.escape(str(text or "")).replace("\n", "<br>")


def is_long_ai(text: str) -> bool:
    """答案是否值得折叠:多行,或单行超过一定长度。"""
    stripped = (text or "").strip()
    if not stripped:
        return False
    if "\n" in stripped:
        return True
    return len(stripped) > 130


def ai_summary(text: str, width: int = 90) -> str:
    """长回答的折叠摘要:取第一行,超宽截断加省略号。"""
    first = (text or "").strip().split("\n", 1)[0].strip()
    if len(first) > width:
        return first[:width - 1].rstrip() + "…"
    return first


def _bubble(body: str, bg: str, label: str, label_color: str, tokens: dict,
            suffix: str = "") -> str:
    return (f'<p style="background:{bg}; padding:7px 9px; border-radius:8px;">'
            f'<b style="color:{label_color};">{label}</b><br>{body}{suffix}</p>')


def render_table(title: str, columns: list, rows: list, tokens: dict) -> str:
    """把结构化表格渲染成 QTextBrowser 能认的富文本表格。

    注意:Qt 的富文本引擎只支持 ``<table border cellpadding cellspacing>``
    这类 HTML4 属性,**不支持** CSS 的 ``border-collapse``。因此边框靠 border
    属性画、斑马纹靠 ``bgcolor``,不要试图用 style 里的 border 取巧(不会生效)。
    """
    columns = [str(c) for c in (columns or [])]
    rows = [list(r) for r in (rows or [])]
    if not columns and not rows:
        return ""
    if not columns:
        columns = [f"列{i + 1}" for i in range(len(rows[0]) if rows else 0)]

    border = tokens["border"]
    header_bg = tokens["row_alt"]
    parts = []
    if title:
        parts.append(f'<p style="color:{tokens["muted"]}; margin-bottom:2px;">'
                     f'<b>{esc(title)}</b></p>')
    parts.append(f'<table border="1" cellpadding="4" cellspacing="0" '
                 f'width="100%" style="border-color:{border};">')
    parts.append('<tr>' + ''.join(
        f'<th bgcolor="{header_bg}" align="left" '
        f'style="color:{tokens["text"]};">{esc(c)}</th>' for c in columns) + '</tr>')
    for index, row in enumerate(rows):
        cells = []
        for cell in row:
            cells.append(f'<td align="left" style="color:{tokens["text"]};">'
                         f'{esc(cell)}</td>')
        # 斑马纹:偶数行给个浅底,长表更好读。
        attrs = f' bgcolor="{tokens["row_alt"]}"' if index % 2 else ''
        parts.append(f'<tr{attrs}>' + ''.join(cells) + '</tr>')
    parts.append('</table>')
    return ''.join(parts)


def table_to_text(title: str, columns: list, rows: list) -> str:
    """同一份表格数据的纯文本形态(交给模型/日志时用,避免二次实现)。"""
    columns = [str(c) for c in (columns or [])]
    rows = [list(r) for r in (rows or [])]
    lines = []
    if title:
        lines.append(title)
    if columns:
        lines.append(' | '.join(columns))
        lines.append('-+-'.join('-' * len(c) for c in columns))
    for row in rows:
        lines.append(' | '.join(str(c) for c in row))
    return '\n'.join(lines)


def render_entry(entry: ChatEntry, index: int, tokens: dict, *,
                 tool_level: Callable[[int], int] | None = None,
                 ai_expanded: bool = False) -> str:
    """渲染单条条目 → HTML 片段。纯函数:同样的输入永远得到同样的输出。"""
    level_of = tool_level or (lambda _tid: 0)

    if entry.kind == "system":
        return f'<p style="color:{tokens["muted"]};">{esc(entry.text)}</p>'

    if entry.kind == "user":
        return _bubble(esc(entry.text), tokens["user_bg"], "你",
                       tokens["accent"], tokens)

    if entry.kind == "ai":
        if not is_long_ai(entry.text):
            return _bubble(esc(entry.text), tokens["ai_bg"], "AI",
                           tokens["success"], tokens)
        if ai_expanded:
            return _bubble(esc(ai_summary(entry.text)), tokens["ai_bg"], "AI",
                           tokens["success"], tokens,
                           suffix=f'… <a href="ai:{index}" '
                                  f'style="color:{tokens["accent"]};">[展开]</a>')
        return _bubble(esc(entry.text), tokens["ai_bg"], "AI",
                       tokens["success"], tokens,
                       suffix=f' <a href="ai:{index}" '
                              f'style="color:{tokens["accent"]};">[收起]</a>')

    if entry.kind == "tool":
        args_text = ", ".join(f"{k}={v}" for k, v in (entry.args or {}).items())[:60]
        args_text = args_text or "(无参数)"
        full = (entry.result or "").strip()
        level = level_of(entry.tool_id)
        if level >= 2:
            return (f'<p style="color:{tokens["muted"]};">🔧 工具 {esc(entry.name)}'
                    f'({esc(args_text)})<br>&nbsp;&nbsp;→ {esc(full)} '
                    f'<a href="tool:{entry.tool_id}">[收起]</a></p>')
        if level == 1:
            preview = (full[:60].replace("\n", " ") + "…") if len(full) > 60 else full
            return (f'<p style="color:{tokens["muted"]};">🔧 工具 {esc(entry.name)}'
                    f'({esc(args_text)})<br>&nbsp;&nbsp;→ {esc(preview)} '
                    f'<a href="tool:{entry.tool_id}">[完整结果]</a></p>')
        return (f'<p style="color:{tokens["muted"]};">🔧 工具 {esc(entry.name)} '
                f'<a href="tool:{entry.tool_id}">[查看]</a></p>')

    if entry.kind == "table":
        return render_table(entry.title, entry.columns, entry.rows, tokens)

    return ''


def render_entries(entries: Iterable[ChatEntry], tokens: dict, *,
                   tool_level: Callable[[int], int] | None = None,
                   expanded_ai: set | None = None) -> str:
    """把整条展示流渲染成 HTML。逐条拼接,不依赖任何全局状态。"""
    expanded = expanded_ai or set()
    return ''.join(
        render_entry(entry, index, tokens, tool_level=tool_level,
                     ai_expanded=index in expanded)
        for index, entry in enumerate(entries))


# ---------------- 显示部件 ----------------
class ChatView(QTextBrowser):
    """只负责显示的对话流控件。

    刻意**不持有**会话状态:条目、展开级别由外层(``AIChatDock``)提供,
    本类只做「把给定条目画出来」,因此可以脱离 dock 单独构造与测试。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        self._tokens_provider: Callable[[], dict] = default_tokens
        self.setStyleSheet(
            f"QTextBrowser {{ background: transparent; border: none; "
            f"color: {text_color()}; }}")

    def set_tokens_provider(self, provider: Callable[[], dict]) -> None:
        """允许外层注入主题来源(测试可注入固定 token 以避免依赖全局主题)。"""
        self._tokens_provider = provider

    def set_entries(self, entries: Iterable[ChatEntry], *,
                    tool_level: Callable[[int], int] | None = None,
                    expanded_ai: set | None = None) -> None:
        """重绘整条展示流。部件已销毁(关闭窗口竞态)时静默忽略。"""
        try:
            self.clear()
        except RuntimeError:
            return
        try:
            tokens = self._tokens_provider()
            body = render_entries(entries, tokens, tool_level=tool_level,
                                  expanded_ai=expanded_ai)
            if body:
                self.append(body)
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().maximum())
        except RuntimeError:
            pass   # C++ 对象已销毁 → 忽略
