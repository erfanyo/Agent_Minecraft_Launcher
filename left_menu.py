# -*- coding: utf-8 -*-
"""
左侧菜单(独立小模块)。

**为什么独立**:多个"左菜单 + 右面板"的页面(下载新资源 / 设置 / 实例详情)共用同一套
左侧菜单,故抽成独立模块 → 样式统一、行为一致;将来若要在菜单上加**复杂动画**
(滑入/高亮条滑动等),只需在这个模块内部实现,不影响使用方。

- 用一组**可选中按钮**(QPushButton checkable)渲染,左对齐 + 圆角 + 选中蓝条高亮。
- **没有折叠功能**(菜单已调窄,折叠用不上)。
- 通过 itemClicked 信号通知使用方切换右侧面板。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from ui_style import menu_btn_style, set_style


class LeftMenu(QWidget):
    itemClicked = Signal(int)   # 点击第 i 项

    def __init__(self, width: int = 150, parent=None):
        super().__init__(parent)
        self.setFixedWidth(width)
        self._buttons = []       # [QPushButton]
        self._current = -1       # 当前选中索引(-1=无)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(4)        # 固定行距
        lay.addStretch(1)        # 底部撑开 → 菜单项靠上排列(顶部对齐、行距固定)
        self._lay = lay

    def add_item(self, label: str, icon: str = "") -> int:
        """加一个菜单项(可选 emoji 图标),返回其索引。"""
        text = (icon + " " + label) if icon else label
        b = QPushButton(text)
        b.setCheckable(True)
        b.setFixedHeight(40)     # 固定行高 → 行距均匀、靠上排列
        set_style(b, menu_btn_style)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        idx = len(self._buttons)
        b.clicked.connect(lambda _c=False, i=idx: self._select(i))
        # 插到末尾 stretch 之前,保证始终靠上、底部留白
        self._lay.insertWidget(self._lay.count() - 1, b)
        self._buttons.append(b)
        return idx

    def select(self, idx: int):
        self._select(idx)

    def _select(self, idx: int):
        for i, b in enumerate(self._buttons):
            b.setChecked(i == idx)
        if idx == self._current:
            return   # 已是当前项:只刷新高亮,不重复发信号(避免 switch_to↔itemClicked 循环)
        self._current = idx
        if 0 <= idx < len(self._buttons):
            self.itemClicked.emit(idx)

    def current(self) -> int:
        return self._current


    def items(self) -> list:
        return [b.text() for b in self._buttons]

    def count(self) -> int:
        return len(self._buttons)
