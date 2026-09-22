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

    def add_section_group(self, group_id: str, label: str, *,
                          open_state: bool = False) -> int:
        """加一个可折叠分组标题(如「高级选项」)。

        与 :meth:`add_section` 不同,标题本身不对应右侧面板——它只控制成员章节
        在菜单里的显示/隐藏。需要折叠的章节用 :meth:`add_grouped_section` 添加。
        返回标题按钮的菜单索引。

        这里会为标题占位补一个空 QStackedWidget 页,保证「菜单索引 == 堆栈索引」
        这一不变式不被破坏(否则后续章节的右侧面板会整体错位一格)。
        """
        idx = self.menu.add_group(group_id, label, open_state=open_state)
        self.stack.addWidget(QWidget())
        return idx

    def add_grouped_section(self, group_id: str, label: str, build_fn,
                            *, lazy: bool = False) -> int:
        """往折叠分组里加一个章节(语义同 add_section)。"""
        idx = self.menu.add_group_item(group_id, label)
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
        # 目标章节若藏在收起的分组里,先自动展开,否则用户会看到「切过去了但菜单
        # 里没有高亮项」的迷惑状态。
        group = self.menu.group_of(row)
        if group is not None and not self.menu.is_group_open(group):
            self.menu.toggle_group(group, True)
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
