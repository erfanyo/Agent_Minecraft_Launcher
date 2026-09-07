# -*- coding: utf-8 -*-
"""
统一的「左菜单(独立模块)+ 右侧面板」骨架(CenterShell)。

- 左菜单用独立模块 left_menu.LeftMenu(无折叠,样式统一,将来可加动画)。
- 右侧 QStackedWidget 放各章节面板;点击左菜单项 → 切右侧面板。
- 用于 设置 / 实例详情 / (未来其它),和「下载新资源」同一套操作逻辑。
"""
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from left_menu import LeftMenu


class CenterShell(QWidget):
    def __init__(self, parent=None, menu_width: int = 150):
        super().__init__(parent)
        self.menu = LeftMenu(width=menu_width)
        self.menu.itemClicked.connect(self._on_item_clicked)
        self.stack = QStackedWidget()
        self._lazy_builders = {}

        body = QHBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.menu)
        body.addWidget(self.stack, 1)
        # 左菜单与右面板间留一点空隙,视觉更透气
        body.setContentsMargins(8, 0, 8, 0)

    def add_section(self, label: str, build_fn, *, lazy: bool = False) -> int:
        """加一个章节。

        ``lazy=True`` 时只在用户第一次打开该章节时构建内容，适合教程、
        方案列表等不参与统一保存的重页面。
        """
        idx = self.menu.add_item(label)
        if lazy:
            self._lazy_builders[idx] = build_fn
            self.stack.addWidget(QWidget())
        else:
            self.stack.addWidget(build_fn())
        return idx

    def switch_to(self, idx: int):
        self.menu.select(idx)

    def switch_by_label(self, label: str) -> bool:
        items = self.menu.items()
        for i, it in enumerate(items):
            if it == label or label in it:
                self.menu.select(i)
                return True
        return False

    def _on_item_clicked(self, row: int):
        previous = self.stack.currentIndex()
        self._ensure_built(row)
        self.stack.setCurrentIndex(row)
        if previous != row:
            from ui_anim import reveal
            reveal(self.stack.currentWidget())

    def _ensure_built(self, row: int):
        build_fn = self._lazy_builders.pop(row, None)
        if build_fn is None:
            return
        placeholder = self.stack.widget(row)
        panel = build_fn()
        self.stack.removeWidget(placeholder)
        placeholder.deleteLater()
        self.stack.insertWidget(row, panel)

    def current_index(self) -> int:
        return self.menu.current()
