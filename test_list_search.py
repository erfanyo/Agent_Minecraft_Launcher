# -*- coding: utf-8 -*-
"""list_search:限长 + 搜索框的复用工具测试。"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (QApplication, QListWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from list_search import (DEFAULT_MAX_HEIGHT, DEFAULT_THRESHOLD, cap_height,
                         make_searchable)

_app = QApplication.instance() or QApplication([])


class _Host:
    """持有宿主 widget 的引用,避免被 GC 掉(否则 C++ 对象会先被销毁)。"""

    def __init__(self, widget):
        self.host = QWidget()
        self.layout = QVBoxLayout(self.host)
        self.layout.addWidget(widget)
        self.widget = widget


class ListSearchTests(unittest.TestCase):
    def test_many_items_show_search_and_filter(self):
        lst = QListWidget()
        for i in range(30):
            lst.addItem(f"item-{i:03d}")
        host = _Host(lst)
        handle = make_searchable(lst)
        self.assertFalse(handle.edit.isHidden(), "超过 20 项应显示搜索框")
        handle.edit.setText("item-00")
        visible = [i for i in range(lst.count()) if not lst.item(i).isHidden()]
        self.assertEqual(len(visible), 10)          # item-000..009
        handle.edit.clear()
        self.assertTrue(all(not lst.item(i).isHidden() for i in range(lst.count())))
        self.assertIsNotNone(host.host)

    def test_few_items_hide_search(self):
        lst = QListWidget()
        for i in range(5):
            lst.addItem(f"m{i}")
        host = _Host(lst)
        handle = make_searchable(lst)
        self.assertTrue(handle.edit.isHidden(), "不足阈值不该显示搜索框")
        self.assertIsNotNone(host.host)

    def test_height_is_capped(self):
        lst = QListWidget()
        host = _Host(lst)
        make_searchable(lst, max_height=180)
        self.assertEqual(lst.maximumHeight(), 180)
        self.assertIsNotNone(host.host)

    def test_search_appears_after_items_grow(self):
        lst = QListWidget()
        host = _Host(lst)
        handle = make_searchable(lst)
        self.assertTrue(handle.edit.isHidden())
        for i in range(DEFAULT_THRESHOLD + 1):      # 越过阈值
            lst.addItem(f"x{i}")
        self.assertFalse(handle.edit.isHidden(), "条目变多后应自动出现搜索框")
        lst.clear()
        self.assertTrue(handle.edit.isHidden(), "清空后应自动隐藏")
        self.assertIsNotNone(host.host)

    def test_tree_widget_supported(self):
        tree = QTreeWidget()
        tree.setHeaderLabels(["名称"])
        for i in range(25):
            QTreeWidgetItem(tree, [f"node-{i:02d}"])
        host = _Host(tree)
        handle = make_searchable(tree)
        self.assertFalse(handle.edit.isHidden())
        handle.edit.setText("node-01")
        visible = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                   if not tree.topLevelItem(i).isHidden()]
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0].text(0), "node-01")
        self.assertIsNotNone(host.host)

    def test_unsupported_widget_raises(self):
        with self.assertRaises(TypeError):
            make_searchable(QWidget())

    def test_cap_height_helper(self):
        lst = QListWidget()
        cap_height(lst, 123)
        self.assertEqual(lst.maximumHeight(), 123)
        lst2 = QListWidget()
        cap_height(lst2)
        self.assertEqual(lst2.maximumHeight(), DEFAULT_MAX_HEIGHT)


if __name__ == "__main__":
    unittest.main()
