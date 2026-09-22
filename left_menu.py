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
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget
from PySide6.QtGui import QIcon

from ui_style import menu_btn_style, set_style


def _is_emoji(text: str) -> bool:
    """粗略判断字符串是不是 emoji(旧兼容:emoji 拼在文字前,不像图标名)。"""
    return any("\ud800" <= c <= "\udfff" or 0x1F000 <= ord(c) <= 0x1FAFF
               for c in text)


class LeftMenu(QWidget):
    itemClicked = Signal(int)   # 点击第 i 项
    groupToggled = Signal(str, bool)   # (分组 id, 是否展开)——供调用方持久化状态

    def __init__(self, width: int = 150, parent=None):
        super().__init__(parent)
        self.setFixedWidth(width)
        self._buttons = []       # [QPushButton]
        self._current = -1       # 当前选中索引(-1=无)
        self._groups = {}        # 分组 id -> {'button','members','open'}
        self._membership = {}    # 菜单索引 -> 所属分组 id
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(4)        # 固定行距
        lay.addStretch(1)        # 底部撑开 → 菜单项靠上排列(顶部对齐、行距固定)
        self._lay = lay

    def _add_button(self, text: str, qicon=None, icon_size: int = 18):
        b = QPushButton(text)
        b.setCheckable(True)
        b.setFixedHeight(40)     # 固定行高 → 行距均匀、靠上排列
        set_style(b, menu_btn_style)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        if qicon is not None and not qicon.isNull():
            b.setIcon(qicon)
            sizes = qicon.availableSizes()
            b.setIconSize(sizes[0] if sizes else QSize(icon_size, icon_size))
        # 插到末尾 stretch 之前,保证始终靠上、底部留白
        self._lay.insertWidget(self._lay.count() - 1, b)
        self._buttons.append(b)
        return len(self._buttons) - 1, b

    def add_item(self, label: str, icon=None, icon_size: int = 18) -> int:
        """加一个菜单项。

        icon: 三种形式
          - None / ""      → 无图标;
          - 主题图标名(str) → 用 theme_icon(icon) 渲染成 QIcon(跟随主题色);
          - 旧 emoji 字符串 → 兼容旧调用,拼在文字前(不推荐,建议用图标名)。
        返回其索引。"""
        is_icon_name = isinstance(icon, str) and bool(icon) and not _is_emoji(icon)
        if is_icon_name:
            from theme_icon import theme_icon
            qicon = theme_icon(icon, icon_size)
        elif isinstance(icon, QIcon):
            qicon = icon
        else:
            qicon = None
        # 仅旧 emoji 字符串拼在文字前;主题图标名 / QIcon 用 setIcon 显示,不污染文字
        text = (icon + " " + label) if (isinstance(icon, str) and icon and not is_icon_name) else label
        idx, b = self._add_button(text, qicon, icon_size)
        b.clicked.connect(lambda _c=False, i=idx: self._select(i))
        return idx

    def add_group(self, group_id: str, label: str, *, open_state: bool = False,
                  icon=None, icon_size: int = 18) -> int:
        """加一个**可折叠分组**标题(如「高级选项」)。

        与 :meth:`add_item` 的区别:标题自身不切换右侧面板,只负责展开/收起组内
        成员;成员用 :meth:`add_group_item` 追加。返回标题按钮的菜单索引。

        注意:折叠只隐藏成员按钮的可见性,**不改变索引**——右侧 QStackedWidget
        的下标与菜单索引必须一一对应,因此绝不能在收起时移除按钮。
        """
        is_icon_name = isinstance(icon, str) and bool(icon) and not _is_emoji(icon)
        if is_icon_name:
            from theme_icon import theme_icon
            qicon = theme_icon(icon, icon_size)
        elif isinstance(icon, QIcon):
            qicon = icon
        else:
            qicon = None
        idx, button = self._add_button(self._group_text(label, open_state), qicon, icon_size)
        button.setCheckable(False)      # 分组标题是开关,不是选中项
        button.clicked.connect(
            lambda _c=False, gid=group_id: self.toggle_group(gid))
        self._groups[group_id] = {'button': button, 'label': label,
                                  'members': [], 'open': bool(open_state)}
        return idx

    @staticmethod
    def _group_text(label: str, opened: bool) -> str:
        return ("▼ " if opened else "▶ ") + label

    def add_group_item(self, group_id: str, label: str, icon=None,
                       icon_size: int = 18) -> int:
        """往某个分组里加成员项;返回菜单索引(与 add_item 相同语义)。"""
        group = self._groups.get(group_id)
        if group is None:
            raise KeyError(f'未知分组:{group_id}')
        idx = self.add_item(label, icon, icon_size)
        group['members'].append(idx)
        self._membership[idx] = group_id
        self._buttons[idx].setVisible(group['open'])
        return idx

    def toggle_group(self, group_id: str, opened=None):
        """展开/收起分组(不传 ``opened`` 则取反),并广播 groupToggled。"""
        group = self._groups.get(group_id)
        if group is None:
            return
        state = (not group['open']) if opened is None else bool(opened)
        group['open'] = state
        group['button'].setText(self._group_text(group['label'], state))
        for idx in group['members']:
            self._buttons[idx].setVisible(state)
        self.groupToggled.emit(group_id, state)

    def is_group_open(self, group_id: str) -> bool:
        group = self._groups.get(group_id)
        return bool(group and group['open'])

    def group_of(self, index: int):
        """返回该菜单索引所属分组 id(不在分组内返回 None)。"""
        return self._membership.get(index)

    def group_members(self, group_id: str) -> list:
        group = self._groups.get(group_id)
        return list(group['members']) if group else []

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
