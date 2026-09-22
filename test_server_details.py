# -*- coding: utf-8 -*-
"""KubeJS 脚本查看器 + 服务端详情页单测。

重点验证:
- 目录树构建(纯函数)正确、跳过隐藏项与符号链接
- 大文件截断、非文本文件不尝试预览
- 服务端详情页章节结构、折叠分组默认状态、菜单与堆栈索引对齐
"""
import os
import tempfile
import unittest

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from kubejs_viewer import (MAX_PREVIEW_CHARS, build_script_tree, is_viewable,
                           read_script, KubejsViewer)


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
            names = {node['name'] for node in tree}
            self.assertNotIn('.hidden', names)

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
        text, truncated, error = read_script(os.path.join('nope.js'))
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
            self.assertEqual(viewer.tree.topLevelItemCount(), 1)
            scripts = viewer.tree.topLevelItem(0)
            self.assertEqual(scripts.childCount(), 1)
            # 选中脚本 → 右侧显示内容
            viewer.tree.setCurrentItem(scripts.child(0))
            self.assertIn('hello', viewer.view.toPlainText())

    def test_viewer_handles_missing_dir(self):
        viewer = KubejsViewer(os.path.join('no', 'such'))
        self.assertEqual(viewer.tree.topLevelItemCount(), 0)
        self.assertIn('未找到', viewer.title.text())


class ServerDetailsTests(unittest.TestCase):
    """服务端详情页结构测试。

    注意:每个用例都会显式销毁自己创建的控件(``addCleanup``)。Qt 控件若在用例
    结束后仅靠垃圾回收销毁,``deleteLater`` 与 C++ 侧子对象的析构顺序不确定,
    实测会让**后续用例**(乃至整个 discovery 运行)出现原生访问违例
    (0xC0000005,进程直接崩)。显式 close + 解除父子 + deleteLater + 处理事件
    能把顺序固定下来。
    """

    def _make_view(self):
        from server_details import ServerDetailsView
        view = ServerDetailsView()
        self.addCleanup(self._destroy, view)
        return view

    @staticmethod
    def _destroy(widget):
        try:
            widget.close()
            widget.setParent(None)
            widget.deleteLater()
            QApplication.processEvents()
        except RuntimeError:
            pass   # 已被 C++ 侧销毁

    def _record(self, temp):
        server_dir = os.path.join(temp, 'server')
        os.makedirs(os.path.join(server_dir, 'mods'))
        os.makedirs(os.path.join(server_dir, 'kubejs', 'server_scripts'))
        with open(os.path.join(server_dir, 'server.properties'), 'w',
                  encoding='utf-8') as f:
            f.write('server-port=25565\n')
        package = os.path.join(temp, 'package')
        os.makedirs(package)
        import json
        with open(os.path.join(package, '.amcl-server.json'), 'w',
                  encoding='utf-8') as f:
            json.dump({'name': 'Test', 'report': {}, 'ui_state': {}}, f)
        return {'id': 'package', 'name': 'Test', 'path': server_dir,
                'packagePath': package, 'report': {}, 'candidate': False}

    def test_sections_match_expected_shape(self):
        from server_details import server_sections
        labels = [label for label, _group in server_sections()]
        self.assertEqual(labels[:4], ['概览', 'Mod', '运行配置', '备份·存档'])
        self.assertIn('高级选项', labels)
        self.assertIn('server.properties', labels)
        self.assertIn('KubeJS', labels)

    def test_advanced_group_collapsed_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            view = self._make_view()
            view.set_server(self._record(temp))
            self.assertFalse(view.shell.menu.is_group_open('advanced'))

    def test_advanced_state_is_restored_per_server(self):
        with tempfile.TemporaryDirectory() as temp:
            record = self._record(temp)
            first = self._make_view()
            first.set_server(record)
            first.shell.menu.toggle_group('advanced', True)
            # 重新构建(模拟切换实例后回来)→ 应恢复展开状态
            again = self._make_view()
            again.set_server(record)
            self.assertTrue(again.shell.menu.is_group_open('advanced'))

    def test_menu_and_stack_indices_stay_aligned(self):
        with tempfile.TemporaryDirectory() as temp:
            view = self._make_view()
            view.set_server(self._record(temp))
            self.assertEqual(view.shell.stack.count(),
                             len(view.shell.menu.items()))

    def test_builders_do_not_crash(self):
        """逐个切换章节,确保每个 builder 都能真的构建出来。"""
        with tempfile.TemporaryDirectory() as temp:
            view = self._make_view()
            view.set_server(self._record(temp))
            count = view.shell.stack.count()
            for index in range(count):
                view.shell.switch_to(index)
            self.assertEqual(view.shell.stack.currentIndex(), count - 1)

    def test_set_server_none_clears(self):
        with tempfile.TemporaryDirectory() as temp:
            view = self._make_view()
            view.set_server(self._record(temp))
            self.assertIsNotNone(view.shell)
            view.set_server(None)
            self.assertIsNone(view.shell)


if __name__ == '__main__':
    unittest.main()
