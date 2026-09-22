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


# ---------------- Markdown 表格识别 ----------------
def _split_md_row(line: str) -> list:
    """拆一行 ``| a | b |``。两端的空单元格来自首尾竖线,需丢弃。"""
    return [cell.strip() for cell in line.strip().strip('|').split('|')]


def _is_md_separator(line: str) -> bool:
    """判定 ``|---|---|`` 这种分隔行。"""
    stripped = line.strip()
    if not stripped.startswith('|'):
        return False
    body = stripped.strip('|').strip()
    if not body or '-' not in body:
        return False
    return all(set(cell.strip()) <= set('-: ') and '-' in cell
               for cell in body.split('|'))


def parse_markdown_tables(text: str) -> list:
    """从文本里提取 Markdown 表格 → [(title, columns, rows), ...]。

    工具返回结构化清单时用 ``| a | b |`` 这种纯文本表格即可:**模型**看到的是
    规整文本,便于理解;**用户**看到的是渲染层画出的真实表格。这样「工具返回
    结构化数据」不需要给每个工具单独加一套 UI 管线,老工具也自动受益。
    识别失败时返回空列表,由调用方回退成纯文本,不会丢内容。
    """
    lines = (text or '').split('\n')
    found = []
    index = 0
    while index < len(lines) - 1:
        header, separator = lines[index], lines[index + 1]
        if '|' not in header or not _is_md_separator(separator):
            index += 1
            continue
        columns = _split_md_row(header)
        if not columns:
            index += 1
            continue
        body = []
        cursor = index + 2
        while cursor < len(lines) and '|' in lines[cursor] and lines[cursor].strip():
            cells = _split_md_row(lines[cursor])
            if len(cells) < len(columns):
                cells += [''] * (len(columns) - len(cells))
            body.append(cells[:len(columns)])
            cursor += 1
        title = ''
        if index > 0:
            previous = lines[index - 1].strip()
            if previous and '|' not in previous:
                title = previous
        found.append((title, columns, body))
        index = cursor
    return found


def render_text_with_tables(text: str, tokens: dict) -> str:
    """普通文本 + 内嵌 Markdown 表格 → HTML:表格画成真表,其余保持转义文本。

    按行扫描,遇到表格区域就整块替换,因此表格前后的说明文字都会被保留。
    """
    lines = (text or '').split('\n')
    tables = parse_markdown_tables(text)
    if not tables:
        return esc(text) if text else ''

    # 标记每个表格占用的行区间:表头 + 分隔 + 数据行。
    spans = []
    consumed = set()
    for title, columns, rows in tables:
        for start in range(len(lines) - 1):
            if start in consumed or '|' not in lines[start]:
                continue
            if _split_md_row(lines[start]) != columns:
                continue
            if not _is_md_separator(lines[start + 1]):
                continue
            end = start + 2 + len(rows)
            spans.append((start, end, title, columns, rows))
            consumed.update(range(start, min(end, len(lines))))
            break

    parts = []
    buffer = []
    position = 0
    for start, end, title, columns, rows in sorted(spans):
        buffer.extend(lines[position:start])
        body = '\n'.join(buffer).strip('\n')
        if body.strip():
            parts.append(esc(body))
        buffer = []
        parts.append(render_table(title, columns, rows, tokens))
        position = end
    buffer.extend(lines[position:])
    tail = '\n'.join(buffer).strip('\n')
    if tail.strip():
        parts.append(esc(tail))
    return ''.join(parts)


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
        body = render_text_with_tables(entry.text, tokens)
        if not is_long_ai(entry.text):
            return _bubble(body, tokens["ai_bg"], "AI", tokens["success"], tokens)
        if ai_expanded:
            # 折叠态只取首行,不可能构成完整表格 → 按纯文本处理,避免露出半截表头。
            summary = ai_summary(entry.text)
            return _bubble(esc(summary), tokens["ai_bg"], "AI", tokens["success"],
                           tokens,
                           suffix=f'… <a href="ai:{index}" '
                                  f'style="color:{tokens["accent"]};">[展开]</a>')
        return _bubble(body, tokens["ai_bg"], "AI", tokens["success"], tokens,
                       suffix=f' <a href="ai:{index}" '
                              f'style="color:{tokens["accent"]};">[收起]</a>')

    if entry.kind == "tool":
        args_text = ", ".join(f"{k}={v}" for k, v in (entry.args or {}).items())[:60]
        args_text = args_text or "(无参数)"
        full = (entry.result or "").strip()
        # 工具结果里若含 Markdown 表格,直接画成真表(QTextBrowser 认的富文本表格)。
        rendered = render_text_with_tables(full, tokens)
        # 折叠级别:调用方常用 ``dict.get`` 作回调,未记录的 id 会返回 None,
        # 因此这里必须把 None 归一成 0,否则与 >= 比较会抛 TypeError(真实崩溃点)。
        level = level_of(entry.tool_id)
        if level is None:
            level = 0
        if level >= 2:
            return (f'<p style="color:{tokens["muted"]};">🔧 工具 {esc(entry.name)}'
                    f'({esc(args_text)})<br>&nbsp;&nbsp;→ {rendered} '
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
        """重绘整条展示流。部件已销毁(关闭窗口竞态)时静默忽略。

        渲染异常**不再静默**:早期版本把 ``TypeError`` 一起吞掉,结果是对话区
        空白但界面照常响应,极难定位。现在只对「C++ 对象已销毁」静默,其余异常
        打印到 stderr 并降级为纯文本,保证消息至少可见。
        """
        try:
            self.clear()
        except RuntimeError:
            return
        try:
            tokens = self._tokens_provider()
            body = render_entries(entries, tokens, tool_level=tool_level,
                                  expanded_ai=expanded_ai)
        except RuntimeError:
            return   # C++ 对象已销毁 → 忽略
        except Exception as exc:                      # noqa: BLE001
            import sys
            print(f'[chat_view] 渲染失败,降级为纯文本:{type(exc).__name__}: {exc}',
                  file=sys.stderr)
            try:
                body = ''.join(esc(getattr(e, 'plain_text', '') or '')
                               for e in entries)
            except Exception:
                body = ''
        try:
            if body:
                self.append(body)
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().maximum())
        except RuntimeError:
            pass   # C++ 对象已销毁 → 忽略
