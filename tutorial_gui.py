# -*- coding: utf-8 -*-
"""
新手教程通用渲染器:读 tutorial_content 里的数据,左边页面列表 + 右边说明正文。

**模块化**:这个渲染器不关心具体界面/按钮,只按数据渲染(位置 / 控件名 / 作用)。
UI 以后怎么改,只要更新 tutorial_content.py 的数据,渲染器这里不用动。
"""
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QLabel, QListWidget, QSplitter, QTextBrowser, QVBoxLayout,
)

from i18n import t
from tutorial_content import get_concepts, get_pages
from ui_style import text_color


def _md(text: str) -> str:
    """轻量 markdown → html:先转义 <>&,再把 **加粗** 转成 <b>,换行转 <br>。"""
    text = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return text.replace("\n", "<br>")


def _concept_html() -> str:
    parts = ["<h2 style='margin:0 0 10px 0;'>&#128218; 基本概念(先看这个)</h2>"]
    for title, body in get_concepts():
        parts.append(
            f"<div style='margin:0 0 12px 0; padding-bottom:8px; "
            f"border-bottom:1px solid #2a3240;'>"
            f"<div style='font-weight:bold; color:#e8ecf2; font-size:14px;'>{_md(title)}</div>"
            f"<div style='color:#c6cdd8; font-size:13px; line-height:1.6;'>{_md(body)}</div>"
            f"</div>")
    return "".join(parts)


def _page_html(title: str, intro: str, items: list) -> str:
    parts = [f"<h2 style='margin:0 0 6px 0;'>&#128218; {_md(title)}</h2>"]
    if intro:
        parts.append(f"<p style='color:#aab3c0; margin:0 0 12px 0;'>{_md(intro)}</p>")
    for where, label, what in items:
        parts.append(
            f"<div style='margin:0 0 10px 0; padding-bottom:8px; "
            f"border-bottom:1px solid #2a3240;'>"
            f"<div style='color:#6E8FBF; font-size:12px;'>{_md(where)}</div>"
            f"<div style='font-weight:bold; color:#e8ecf2; font-size:14px;'>{_md(label)}</div>"
            f"<div style='color:#c6cdd8; font-size:13px; line-height:1.6;'>{_md(what)}</div>"
            f"</div>")
    return "".join(parts)


class TutorialDialog(QDialog):
    """新手教程对话框:左侧页面列表,右侧该页的「位置 / 控件名 / 作用」说明。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("📖 新手教程", "Beginner Tutorial"))
        self.resize(780, 640)

        # ---- 左侧:页面导航(全部来自 tutorial_content 数据) ----
        self.nav = QListWidget()
        self.nav.setFixedWidth(208)
        self._meta = [(None, t("基本概念", "Basics"))]      # (page_id, 标题)  None=基本概念
        self.nav.addItem(self._meta[0][1])
        for p in get_pages():
            self.nav.addItem(p["title"])
            self._meta.append((p["id"], p["title"]))

        # ---- 右侧:正文(QTextBrowser,只读富文本) ----
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.setStyleSheet(
            "QTextBrowser { background: transparent; border: none;"
            f" color: {text_color()}; padding: 2px; }}")
        self.browser.setHtml(_concept_html())

        # ---- 布局 ----
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.nav)
        split.addWidget(self.browser)
        split.setStretchFactor(1, 1)
        split.setSizes([208, 560])

        tip = QLabel(t("这里只讲「每个界面里有什么、在哪、有什么用」,点左侧切页面;"
                       "不改变启动器任何设置。", "Read-only guide: what each control does."))
        tip.setStyleSheet("color:#8a93a0;")
        tip.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(split, 1)
        layout.addWidget(tip)

        self.nav.currentRowChanged.connect(self._show)
        self.nav.setCurrentRow(0)

    def _show(self, row: int):
        page_id, _title = self._meta[row]
        if page_id is None:
            html = _concept_html()
        else:
            page = next((p for p in get_pages() if p["id"] == page_id), None)
            if page is None:
                html = "<p>没有找到该页内容。</p>"
            else:
                html = _page_html(page["title"], page.get("intro", ""), page["items"])
        self.browser.setHtml(html)
        self.browser.verticalScrollBar().setValue(0)
