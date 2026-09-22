# -*- coding: utf-8 -*-
"""KubeJS 脚本查看器单测(插件内实现)。

查看器已从核心移到 ``plugins/kubejs_viewer.py``:KubeJS 只有整合包作者会看,
按项目约定(core 只留大众功能)应以插件承载。
"""
import os
import tempfile
import unittest

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from plugin_test_support import ensure_plugin_path

ensure_plugin_path()

from kubejs_viewer import (MAX_PREVIEW_CHARS, KubejsViewer, build_script_tree,
                           is_viewable, read_script)


class ScriptTreeTests(unittest.TestCase):
    def _make(self, temp):
        root = os.path.join(temp, 'kubejs')
        os.makedirs(os.path.join(root, 'server_scripts', 'business'))
        os.makedirs(os.path.join(root, 'startup_scripts'))
        for relative in ('server_scripts/a.js',
                         'server_scripts/business/b.js',
                         'startup_scripts/c.js',
                         'server_scripts/notes.txt',
                         'server_scripts/blob.jar'):
            with open(os.path.join(root, relative), 'w', encoding='utf-8') as f:
                f.write('x')
        with open(os.path.join(root, '.hidden'), 'w', encoding='utf-8') as f:
            f.write('x')
        return root

    def test_tree_includes_nested_files(self):
        with tempfile.TemporaryDirectory() as temp:
            tree = build_script_tree(self._make(temp))
            names = {node['name'] for node in tree}
            self.assertIn('server_scripts', names)
            self.assertIn('startup_scripts', names)
            server = next(n for n in tree if n['name'] == 'server_scripts')
            self.assertTrue(server['is_dir'])
            child_names = {c['name'] for c in server['children']}
            self.assertIn('business', child_names)
            business = next(c for c in server['children'] if c['name'] == 'business')
            self.assertEqual([g['name'] for g in business['children']], ['b.js'])

    def test_hidden_entries_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            tree = build_script_tree(self._make(temp))
            self.assertNotIn('.hidden', {node['name'] for node in tree})

    def test_missing_root_returns_empty(self):
        self.assertEqual(build_script_tree(os.path.join('no', 'such', 'dir')), [])
        self.assertEqual(build_script_tree(''), [])

    def test_is_viewable(self):
        self.assertTrue(is_viewable('a.js'))
        self.assertTrue(is_viewable('A.JSON'))
        self.assertFalse(is_viewable('mod.jar'))
        self.assertFalse(is_viewable('image.png'))

    def test_read_script_truncates_large_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, 'big.js')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('a' * (MAX_PREVIEW_CHARS + 500))
            text, truncated, error = read_script(path)
            self.assertEqual(error, '')
            self.assertTrue(truncated)
            self.assertLessEqual(len(text), MAX_PREVIEW_CHARS)

    def test_read_script_missing_file_reports_error(self):
        text, truncated, error = read_script('nope.js')
        self.assertTrue(error)
        self.assertFalse(truncated)

    def test_read_script_bad_encoding_does_not_raise(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, 'bad.js')
            with open(path, 'wb') as f:
                f.write(b'\xff\xfe\x00bad bytes')
            text, truncated, error = read_script(path)
            self.assertEqual(error, '')
            self.assertIsInstance(text, str)


class KubejsViewerWidgetTests(unittest.TestCase):
    def test_viewer_lists_and_previews(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, 'kubejs')
            os.makedirs(os.path.join(root, 'server_scripts'))
            with open(os.path.join(root, 'server_scripts', 'a.js'), 'w',
                      encoding='utf-8') as f:
                f.write('console.log("hello")')
            viewer = KubejsViewer(root)
            self.addCleanup(self._destroy, viewer)
            self.assertEqual(viewer.tree.topLevelItemCount(), 1)
            scripts = viewer.tree.topLevelItem(0)
            self.assertEqual(scripts.childCount(), 1)
            viewer.tree.setCurrentItem(scripts.child(0))
            self.assertIn('hello', viewer.view.toPlainText())

    def test_viewer_handles_missing_dir(self):
        viewer = KubejsViewer(os.path.join('no', 'such'))
        self.addCleanup(self._destroy, viewer)
        self.assertEqual(viewer.tree.topLevelItemCount(), 0)
        self.assertIn('未找到', viewer.title.text())

    @staticmethod
    def _destroy(viewer):
        try:
            viewer.close()
            viewer.setParent(None)
            viewer.deleteLater()
            QApplication.processEvents()
        except RuntimeError:
            pass


if __name__ == '__main__':
    unittest.main()
