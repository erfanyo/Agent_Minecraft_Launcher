# -*- coding: utf-8 -*-
"""列表限长 + 搜索:统一「长列表限高,超过 N 项就配搜索框」的做法。

约定(与启动器现有 UI 一致):
  · **所有长列表限高**(默认 260px),再长也不撑爆界面;
  · **条目超过 20 个才显示搜索框**(不够长就不占地方);
  · 过滤是**隐藏**条目,不删除,因此选中项 / 绑定数据语义不变。

最短用法(适用于 QListWidget / QTreeWidget)::

    from list_search import make_searchable
    make_searchable(self.some_list)      # 挂完自动跟随增删刷新

非列表控件的两种情形见 docs/list-limit-and-search.md:
  · 自定义行(QVBoxLayout 里一坨 widget,如模型目录)→ QScrollArea + setVisible 过滤;
  · QComboBox(如资源版本)→ 搜索框 + 用全集重填(保住 currentData())。
"""
from PySide6.QtWidgets import (
    QLineEdit, QListWidget, QTreeWidget, QTreeWidgetItemIterator,
    QVBoxLayout, QWidget,
)

#: 超过这个条目数才出现搜索框
DEFAULT_THRESHOLD = 20
#: 列表默认最大高度(px)
DEFAULT_MAX_HEIGHT = 260


def cap_height(widget, max_height: int = DEFAULT_MAX_HEIGHT):
    """给列表 / 滚动区限高。"""
    widget.setMaximumHeight(int(max_height))
    return widget


class SearchableList:
    """搜索框 + 列表的组合句柄。条目按文本过滤(隐藏,不删除)。"""

    def __init__(self, widget, edit: QLineEdit, threshold: int):
        self.widget = widget
        self.edit = edit
        self.threshold = int(threshold)

    # ---- 刷新 ----
    def refresh(self):
        """条目变化后调用:决定搜索框是否显示,并重新套用当前过滤词。

        信号回调可能比控件活得久(窗口先销毁),此时底层 C++ 对象已释放,安静退出即可。
        """
        try:
            n = self._count()
        except RuntimeError:
            return
        self.edit.setVisible(n > self.threshold)
        if n <= self.threshold and self.edit.text():
            self.edit.blockSignals(True)
            self.edit.clear()
            self.edit.blockSignals(False)
        self.apply()

    def apply(self):
        """按当前搜索词隐藏不匹配的条目。"""
        query = self.edit.text().strip().lower()
        try:
            items = self._items()
        except RuntimeError:
            return
        for item in items:
            if not query:
                item.setHidden(False)
            else:
                item.setHidden(query not in self._text(item).lower())

    # ---- 控件差异 ----
    def _count(self) -> int:
        if isinstance(self.widget, QTreeWidget):
            it = QTreeWidgetItemIterator(self.widget)
            n = 0
            while it.value():
                n += 1
                it += 1
            return n
        return self.widget.count()

    def _items(self) -> list:
        if isinstance(self.widget, QTreeWidget):
            out, it = [], QTreeWidgetItemIterator(self.widget)
            while it.value():
                out.append(it.value())
                it += 1
            return out
        return [self.widget.item(i) for i in range(self.widget.count())]

    def _text(self, item) -> str:
        if isinstance(self.widget, QTreeWidget):
            return item.text(0)
        return item.text()


def make_searchable(widget, threshold: int = DEFAULT_THRESHOLD,
                    max_height: int = DEFAULT_MAX_HEIGHT,
                    placeholder: str = "搜索…") -> SearchableList:
    """把 ``widget``(QListWidget / QTreeWidget)包成「搜索框 + 限高列表」。

    会就地插到原控件所在的布局位置,所以调用方无需改布局代码;
    并自动连接模型的增删信号,之后列表内容变了搜索框会自动显示/隐藏。
    """
    if not isinstance(widget, (QListWidget, QTreeWidget)):
        raise TypeError("make_searchable 只支持 QListWidget / QTreeWidget;"
                        "其它控件请参考 docs/list-limit-and-search.md")
    parent = widget.parentWidget()
    layout = parent.layout() if parent is not None else None
    box = QWidget(parent)
    column = QVBoxLayout(box)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(4)

    edit = QLineEdit(box)
    edit.setPlaceholderText(placeholder)
    edit.setClearButtonEnabled(True)
    edit.setVisible(False)          # 条目够多时才显示
    column.addWidget(edit)

    if layout is not None:
        index = layout.indexOf(widget)
        layout.removeWidget(widget)
        widget.setParent(box)
        column.addWidget(widget)
        if index >= 0:
            layout.insertWidget(index, box)
        else:
            layout.addWidget(box)
    else:
        column.addWidget(widget)

    cap_height(widget, max_height)
    handle = SearchableList(widget, edit, threshold)
    edit.textChanged.connect(lambda _text: handle.apply())

    model = widget.model()          # 增删 / 重置后自动刷新搜索框可见性
    for name in ("rowsInserted", "rowsRemoved", "modelReset", "layoutChanged"):
        signal = getattr(model, name, None)
        if signal is not None:
            try:
                signal.connect(lambda *args: handle.refresh())
            except Exception:
                pass
    handle.refresh()
    return handle
