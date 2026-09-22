# -*- coding: utf-8 -*-
"""可折叠分组菜单 + 每实例界面状态单测。

关键约束:折叠只能隐藏成员按钮的**可见性**,不能改变菜单索引——右侧
QStackedWidget 的下标与菜单索引必须始终一一对应。
"""
import json
import os
import tempfile
import unittest

from PySide6.QtWidgets import QApplication, QWidget

import instance_metadata as meta
from center_shell import CenterShell

_app = QApplication.instance() or QApplication([])


def _panel(text=''):
    w = QWidget()
    w.setObjectName(text or 'panel')
    return w


class LeftMenuGroupTests(unittest.TestCase):
    def _shell(self):
        shell = CenterShell()
        shell.add_section('概览', lambda: _panel('overview'))
        shell.add_section('设置', lambda: _panel('settings'))
        shell.add_section_group('advanced', '高级选项', open_state=False)
        shell.add_grouped_section('advanced', 'KubeJS', lambda: _panel('kubejs'))
        shell.add_grouped_section('advanced', '运行配置', lambda: _panel('runtime'))
        shell.add_section('备份', lambda: _panel('backup'))
        return shell

    def test_group_items_hidden_when_collapsed(self):
        shell = self._shell()
        kubejs = shell.menu.items().index('KubeJS')
        # 用 isHidden 而不是 isVisible:父窗口未 show 时 isVisible 恒为 False,
        # 测不出「被 setVisible(False) 显式隐藏」这一状态。
        self.assertTrue(shell.menu._buttons[kubejs].isHidden())
        # 收起状态下点开分组 → 成员可见
        shell.menu.toggle_group('advanced', True)
        self.assertFalse(shell.menu._buttons[kubejs].isHidden())

    def test_collapsing_does_not_change_indices(self):
        """核心约束:折叠前后每个菜单索引仍指向同一个章节。"""
        shell = self._shell()
        before = shell.menu.items()
        shell.menu.toggle_group('advanced', True)
        shell.menu.toggle_group('advanced', False)
        after = shell.menu.items()
        self.assertEqual(before, after)
        self.assertEqual(shell.stack.count(), len(after))

    def test_switching_to_grouped_section_auto_expands(self):
        """切到藏在收起分组里的章节 → 自动展开,避免「切过去了但菜单没高亮」。"""
        shell = self._shell()
        kubejs = shell.menu.items().index('KubeJS')
        self.assertFalse(shell.menu.is_group_open('advanced'))
        shell.switch_to(kubejs)
        self.assertTrue(shell.menu.is_group_open('advanced'))
        self.assertEqual(shell.stack.currentIndex(), kubejs)

    def test_toggle_emits_signal_for_persistence(self):
        shell = self._shell()
        seen = []
        shell.menu.groupToggled.connect(lambda gid, state: seen.append((gid, state)))
        shell.menu.toggle_group('advanced', True)
        self.assertEqual(seen, [('advanced', True)])

    def test_group_of_and_members(self):
        shell = self._shell()
        items = shell.menu.items()
        self.assertEqual(shell.menu.group_of(items.index('KubeJS')), 'advanced')
        self.assertIsNone(shell.menu.group_of(items.index('概览')))
        self.assertEqual(len(shell.menu.group_members('advanced')), 2)

    def test_group_header_appears_in_items(self):
        """分组标题本身也是菜单项(占一个索引),但不对应右侧面板。"""
        shell = self._shell()
        titles = [t for t in shell.menu.items() if '高级选项' in t]
        self.assertEqual(len(titles), 1)
        self.assertTrue(titles[0].startswith('▶'))

    def test_backward_compatible_plain_menu(self):
        """老调用方(只用 add_section)不受影响。"""
        shell = CenterShell()
        a = shell.add_section('A', lambda: _panel('a'))
        b = shell.add_section('B', lambda: _panel('b'))
        self.assertEqual((a, b), (0, 1))
        self.assertIsNone(shell.menu.group_of(0))
        shell.switch_to(1)
        self.assertEqual(shell.stack.currentIndex(), 1)


class UiStateTests(unittest.TestCase):
    def test_missing_file_returns_default(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(meta.read_ui_state(temp, 'advanced_open'))
            self.assertFalse(meta.read_ui_state(temp, 'advanced_open', False))

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertTrue(meta.write_ui_state(temp, 'advanced_open', True))
            self.assertTrue(meta.read_ui_state(temp, 'advanced_open'))
            self.assertTrue(meta.write_ui_state(temp, 'advanced_open', False))
            self.assertFalse(meta.read_ui_state(temp, 'advanced_open', True))

    def test_preserves_other_metadata(self):
        """写界面状态不能碰 minecraft_version 等既有键。"""
        with tempfile.TemporaryDirectory() as temp:
            with open(os.path.join(temp, 'amcl_instance.json'), 'w',
                      encoding='utf-8') as f:
                json.dump({'minecraft_version': '1.20.1',
                           'source_type': 'modpack'}, f)
            meta.write_ui_state(temp, 'advanced_open', True)
            data = meta.read_metadata(temp)
            self.assertEqual(data['minecraft_version'], '1.20.1')
            self.assertEqual(data['source_type'], 'modpack')
            self.assertTrue(data[meta.UI_STATE_KEY]['advanced_open'])

    def test_per_instance_isolation(self):
        """工作/生活两套实例各自记状态,互不影响。"""
        with tempfile.TemporaryDirectory() as temp:
            work = os.path.join(temp, 'work')
            life = os.path.join(temp, 'life')
            os.makedirs(work)
            os.makedirs(life)
            meta.write_ui_state(work, 'advanced_open', True)
            meta.write_ui_state(life, 'advanced_open', False)
            self.assertTrue(meta.read_ui_state(work, 'advanced_open'))
            self.assertFalse(meta.read_ui_state(life, 'advanced_open'))

    def test_write_failure_is_not_fatal(self):
        """目录不可写时返回 False,不抛异常(点一下菜单不该崩)。"""
        self.assertFalse(meta.write_ui_state(
            os.path.join(tempfile.gettempdir(), 'no-such-\x00-dir'),
            'advanced_open', True))

    def test_corrupt_metadata_is_tolerated(self):
        with tempfile.TemporaryDirectory() as temp:
            with open(os.path.join(temp, 'amcl_instance.json'), 'w',
                      encoding='utf-8') as f:
                f.write('{not json')
            self.assertIsNone(meta.read_ui_state(temp, 'advanced_open'))
            self.assertTrue(meta.write_ui_state(temp, 'advanced_open', True))


if __name__ == '__main__':
    unittest.main()
