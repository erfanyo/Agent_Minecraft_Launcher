# -*- coding: utf-8 -*-
"""
统一的「左菜单(纵向)+ 右侧面板」骨架(CenterShell)。

**用途**:让 设置 / 实例详情 / (未来其它) 和 「下载新资源」用同一套布局/操作逻辑,
避免各写各的、风格割裂。调用方:add_section(label, build_fn) 逐个加章节,switch_to 切页。

与 ResourceCenter 的差异:ResourceCenter 是资源浏览专用(搜索/筛选/详情),较复杂;
CenterShell 是轻量通用骨架,只负责"左菜单 → 右面板"的导航,内容由调用方填。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QListWidget, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from ui_style import card_btn_style, list_style


class CenterShell(QWidget):
    def __init__(self, parent=None, menu_width=150):
        super().__init__(parent)
        # 左侧菜单(collapse 按钮 + 项目列表)
        self.menu = QListWidget()
        self.menu.setFixedWidth(menu_width)
        self.menu.setStyleSheet(list_style())
        self.menu.currentRowChanged.connect(self._on_row_changed)

        # 右侧面板
        self.stack = QStackedWidget()

        self.collapse_btn = QPushButton("◀ 收起")
        self.collapse_btn.setStyleSheet(card_btn_style())
        self.collapse_btn.clicked.connect(self._toggle_menu)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(4)
        left.addWidget(self.collapse_btn)
        left.addWidget(self.menu, 1)

        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(menu_width)

        body = QHBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(left_w)
        body.addWidget(self.stack, 1)

        self._collapsed = False

    def add_section(self, label: str, build_fn) -> int:
        """加一个章节:left 菜单项 + 右侧面板。build_fn() 返回该面板的 QWidget。"""
        idx = self.menu.count()
        self.menu.addItem(label)
        self.stack.addWidget(build_fn())
        return idx

    def switch_to(self, idx: int):
        if 0 <= idx < self.menu.count():
            self.menu.setCurrentRow(idx)

    def switch_by_label(self, label: str) -> bool:
        for i in range(self.menu.count()):
            if self.menu.item(i).text() == label:
                self.menu.setCurrentRow(i)
                return True
        return False

    def _on_row_changed(self, row):
        self.stack.setCurrentIndex(row)

    def current_index(self) -> int:
        return self.menu.currentRow()

    def _toggle_menu(self):
        self._collapsed = not self._collapsed
        self.menu.setFixedWidth(44 if self._collapsed else self.menu.width())

    # 内容区可直接借用:给右面板加内容
    def set_current_widget(self, widget: QWidget):
        self.stack.setCurrentWidget(widget)
