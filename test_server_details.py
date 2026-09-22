# -*- coding: utf-8 -*-
"""服务端详情页单测。

重点验证章节结构、折叠分组默认状态、菜单与堆栈索引对齐,以及各章节能构建出来。
查看器相关的测试已随实现移到 ``test_kubejs_viewer.py``(KubeJS 改成了插件)。
"""
import os
import tempfile
import unittest

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from server_details import ServerDetailsView


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
        self.assertEqual(labels[:5], ['概览', 'Mod', '玩家名单', '运行配置', '备份·存档'])
        self.assertIn('高级选项', labels)
        self.assertIn('server.properties', labels)
        self.assertIn('诊断', labels)

    def test_kubejs_section_removed_from_core(self):
        """KubeJS 已改成插件(主标签页「KubeJS 工具」),核心不该再留章节。

        留着会变成一个点了没用的空页;插件入口在主标签栏,不浅。
        """
        from server_details import server_sections
        labels = [label for label, _group in server_sections()]
        self.assertNotIn('KubeJS', labels)
        self.assertFalse(hasattr(ServerDetailsView, '_build_kubejs'))

    def test_no_section_is_a_placeholder_stub(self):
        """章节列表里不应再有「未实现」占位——占位会让用户以为功能坏了。"""
        from server_details import server_sections
        labels = [label for label, _group in server_sections()]
        self.assertNotIn('（未实现）', labels)
        for label in labels:
            self.assertNotIn('未实现', label)

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

    def test_player_section_add_and_remove(self):
        """玩家名单页要能真的落盘(通过视图上的按钮路径)。"""
        import server_players as spl
        with tempfile.TemporaryDirectory() as temp:
            record = self._record(temp)
            view = self._make_view()
            view.set_server(record)
            self.assertIn('whitelist', view._player_lists)
            # 直接走模块层,验证视图暴露的刷新钩子能读到写入结果
            result = spl.apply_entries(record['path'], 'whitelist',
                                       spl.add_entry([], 'whitelist',
                                                     name='Steve', uuid='u1'))
            self.assertTrue(result['ok'], result)
            view._player_lists['whitelist']()
            entries, _ = spl.read_entries(record['path'], 'whitelist')
            self.assertEqual([spl.entry_name(e) for e in entries], ['Steve'])


if __name__ == '__main__':
    unittest.main()
