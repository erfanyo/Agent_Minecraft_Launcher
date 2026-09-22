# -*- coding: utf-8 -*-
"""内容包面板(UI 层)单测。

只锁「不炸 + 按钮按 read_only 变化 + 导入后列表会刷新」这些看得见的行为,
文件拷贝逻辑本身在 test_pack_folder.py 里测过了。
"""
import os
import tempfile
import unittest

from PySide6.QtWidgets import QApplication, QPushButton

import pack_folder_ui as pui

_app = QApplication.instance() or QApplication([])


def _write(path, text='x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as stream:
        stream.write(text)
    return path


def _buttons(panel) -> list:
    return [b.text() for b in panel.findChildren(QPushButton)]


class PanelTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = os.path.join(self._temp.name, 'packs')

    def test_lists_files_and_folders(self):
        _write(os.path.join(self.root, 'a.nbt'))
        _write(os.path.join(self.root, 'notes.txt'))
        _write(os.path.join(self.root, 'MyPack', 'inner.txt'))
        panel = pui.PackFolderPanel(self.root, exts=('.nbt',))
        self.addCleanup(panel.deleteLater)
        texts = [panel.list.item(i).text() for i in range(panel.list.count())]
        self.assertTrue(any(t.startswith('a.nbt') for t in texts))
        self.assertTrue(any(t.startswith('MyPack') for t in texts))
        self.assertFalse(any('notes.txt' in t for t in texts))
        self.assertIn('2 个 · 共 2 个文件', panel.summary.text())

    def test_empty_folder_shows_hint_row(self):
        os.makedirs(self.root, exist_ok=True)
        panel = pui.PackFolderPanel(self.root)
        self.addCleanup(panel.deleteLater)
        self.assertEqual(panel.list.count(), 1)
        self.assertIn('空', panel.summary.text())

    def test_missing_folder_is_not_an_error(self):
        panel = pui.PackFolderPanel(os.path.join(self._temp.name, 'nope'))
        self.addCleanup(panel.deleteLater)
        self.assertEqual(panel.summary.text(), '空')

    def test_writable_panel_has_import_and_delete(self):
        os.makedirs(self.root, exist_ok=True)
        panel = pui.PackFolderPanel(self.root)
        self.addCleanup(panel.deleteLater)
        labels = _buttons(panel)
        self.assertIn('导入文件…', labels)
        self.assertIn('导入文件夹…', labels)
        self.assertIn('删除所选…', labels)

    def test_read_only_panel_hides_import_and_delete(self):
        os.makedirs(self.root, exist_ok=True)
        panel = pui.PackFolderPanel(self.root, read_only=True)
        self.addCleanup(panel.deleteLater)
        labels = _buttons(panel)
        self.assertNotIn('导入文件…', labels)
        self.assertNotIn('删除所选…', labels)
        self.assertIn('刷新', labels)

    def test_import_refreshes_list_and_reports(self):
        os.makedirs(self.root, exist_ok=True)
        source = _write(os.path.join(self._temp.name, 'src', 'brand.nbt'))
        said = []
        panel = pui.PackFolderPanel(self.root, exts=('.nbt',), on_status=said.append)
        self.addCleanup(panel.deleteLater)
        panel.import_paths([source])
        self.assertTrue(os.path.isfile(os.path.join(self.root, 'brand.nbt')))
        texts = [panel.list.item(i).text() for i in range(panel.list.count())]
        self.assertTrue(any('brand.nbt' in t for t in texts))
        self.assertEqual(said, ['已导入 1 项'])

    def test_recursive_panel_lists_nested_files(self):
        _write(os.path.join(self.root, 'com', 'demo', 'Thing.badiff'))
        panel = pui.PackFolderPanel(self.root, exts=('.badiff',), recursive=True,
                                    read_only=True)
        self.addCleanup(panel.deleteLater)
        self.assertEqual(panel.list.item(0).text(), 'com/demo/Thing.badiff')

    def test_selected_paths_ignores_placeholder(self):
        os.makedirs(self.root, exist_ok=True)
        panel = pui.PackFolderPanel(self.root)
        self.addCleanup(panel.deleteLater)
        self.assertEqual(panel.selected_paths(), [])

    def test_delete_only_touches_selection(self):
        keep = _write(os.path.join(self.root, 'keep.nbt'))
        gone = _write(os.path.join(self.root, 'gone.nbt'))
        panel = pui.PackFolderPanel(self.root, exts=('.nbt',))
        self.addCleanup(panel.deleteLater)
        # 直接走逻辑层(UI 的确认弹窗不该在测试里真弹)
        import pack_folder
        outcome = pack_folder.remove_paths([gone])
        panel.reload()
        self.assertEqual(outcome['removed'], ['gone.nbt'])
        self.assertTrue(os.path.isfile(keep))
        self.assertEqual(panel.list.count(), 1)


if __name__ == '__main__':
    unittest.main()
