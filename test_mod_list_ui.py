# -*- coding: utf-8 -*-
"""Mod 列表圆点标记单测。

「启用/停用」用绿点/红点表示(替代 [已停用] 文字前缀)。这里锁定:
- 状态判定与 .jar/.jar.disabled 规则一致
- 每个列表项都带非空图标,且 UserRole 仍保存**真实文件名**(启用/停用/删除都靠它)
- 悬停提示里有状态文字(不依赖颜色也能确认)
- 主题色取自 ui_style,不写死色值
"""
import os
import tempfile
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget

_app = QApplication.instance() or QApplication([])

import mod_list_ui
from ui_style import danger_color, success_color


class StateTests(unittest.TestCase):
    def test_is_disabled(self):
        self.assertTrue(mod_list_ui.is_disabled('a.jar.disabled'))
        self.assertTrue(mod_list_ui.is_disabled('A.JAR.DISABLED'))
        self.assertFalse(mod_list_ui.is_disabled('a.jar'))

    def test_state_text(self):
        self.assertEqual(mod_list_ui.state_text('a.jar'), mod_list_ui.STATE_ENABLED)
        self.assertEqual(mod_list_ui.state_text('a.jar.disabled'),
                         mod_list_ui.STATE_DISABLED)

    def test_is_mod_file(self):
        self.assertTrue(mod_list_ui.is_mod_file('a.jar'))
        self.assertTrue(mod_list_ui.is_mod_file('a.jar.disabled'))
        self.assertFalse(mod_list_ui.is_mod_file('a.zip'))
        self.assertFalse(mod_list_ui.is_mod_file('notes.txt'))


class ItemTests(unittest.TestCase):
    def test_enabled_item_has_icon_and_tooltip(self):
        item = mod_list_ui.make_item('create.jar')
        self.assertFalse(item.icon().isNull(), '启用项要有绿点图标')
        self.assertIn('create.jar', item.text())
        self.assertIn('启用', item.toolTip())

    def test_disabled_item_keeps_full_filename(self):
        """文字保留 .disabled 后缀,UserRole 也必须是真实文件名。"""
        item = mod_list_ui.make_item('lootbeams.jar.disabled')
        self.assertFalse(item.icon().isNull(), '停用项要有红点图标')
        self.assertIn('lootbeams.jar.disabled', item.text())
        self.assertEqual(item.data(Qt.ItemDataRole.UserRole),
                         'lootbeams.jar.disabled')
        self.assertIn('已停用', item.toolTip())

    def test_userrole_always_real_filename(self):
        for name in ('a.jar', 'b.jar.disabled'):
            self.assertEqual(mod_list_ui.make_item(name).data(
                Qt.ItemDataRole.UserRole), name)

    def test_enabled_and_disabled_use_different_colors(self):
        """两点颜色必须不同(语义取自主题 success/danger)。"""
        self.assertNotEqual(success_color(), danger_color())
        enabled = mod_list_ui.make_item('a.jar').icon()
        disabled = mod_list_ui.make_item('b.jar.disabled').icon()
        self.assertFalse(enabled.isNull())
        self.assertFalse(disabled.isNull())

    def test_dot_icon_is_cached(self):
        """列表里每个 Mod 都要一个点,必须缓存,否则重复绘制上百次。"""
        from theme_icon import status_dot
        first = status_dot(success_color(), mod_list_ui.DOT_SIZE)
        again = status_dot(success_color(), mod_list_ui.DOT_SIZE)
        self.assertIs(first, again)


class ListableTests(unittest.TestCase):
    def _dir(self, temp, names):
        for name in names:
            path = os.path.join(temp, name)
            with open(path, 'wb') as stream:
                stream.write(b'x')
        return temp

    def test_lists_only_mod_files_sorted(self):
        with tempfile.TemporaryDirectory() as temp:
            self._dir(temp, ['b.jar', 'a.jar', 'notes.txt', 'c.jar.disabled'])
            self.assertEqual(mod_list_ui.listable_mods(temp),
                             ['a.jar', 'b.jar', 'c.jar.disabled'])

    def test_missing_directory_returns_empty(self):
        self.assertEqual(mod_list_ui.listable_mods(''), [])
        self.assertEqual(mod_list_ui.listable_mods(os.path.join('no', 'dir')), [])

    def test_directories_are_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            os.makedirs(os.path.join(temp, 'somefolder.jar'))
            self._dir(temp, ['a.jar'])
            self.assertEqual(mod_list_ui.listable_mods(temp), ['a.jar'])


class FillTests(unittest.TestCase):
    def test_fill_populates_and_reports_count(self):
        with tempfile.TemporaryDirectory() as temp:
            for name in ('a.jar', 'b.jar.disabled'):
                with open(os.path.join(temp, name), 'wb') as stream:
                    stream.write(b'x')
            widget = QListWidget()
            count = mod_list_ui.fill(widget, temp)
            self.assertEqual(count, 2)
            self.assertEqual(widget.count(), 2)
            self.assertGreater(widget.iconSize().width(), 0, '应设置图标尺寸')

    def test_fill_empty_directory_shows_placeholder(self):
        with tempfile.TemporaryDirectory() as temp:
            widget = QListWidget()
            count = mod_list_ui.fill(widget, temp)
            self.assertEqual(count, 0)
            self.assertEqual(widget.count(), 1)
            self.assertEqual(widget.item(0).icon().isNull(), True)

    def test_fill_clears_previous_contents(self):
        with tempfile.TemporaryDirectory() as temp:
            widget = QListWidget()
            widget.addItem('stale')
            mod_list_ui.fill(widget, temp)
            self.assertNotEqual(widget.item(0).text(), 'stale')


if __name__ == '__main__':
    unittest.main()
