# -*- coding: utf-8 -*-
"""KubeJS 报错定位的界面集成单测。

验证「点报错 → 跳到那一行并高亮」这条链路,以及找不到文件时的降级提示。
不碰真实服务端,用临时 kubejs 目录。
"""
import os
import tempfile
import unittest

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from kubejs_viewer import KubejsViewer


def _make_kubejs(temp, lines=600):
    root = os.path.join(temp, 'kubejs')
    folder = os.path.join(root, 'server_scripts', 'business')
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, 'counter.js'), 'w', encoding='utf-8') as f:
        for number in range(1, lines + 1):
            f.write(f'let v{number} = {number};\n')
    return root


LOG = ("[18:18:15] [Server thread/ERROR] [KubeJS Server/]: "
       "business/counter.js#501: Error in 'BlockEvents.rightClicked': "
       "TypeError: Cannot find function getIngredients in object x\n")


class ErrorNavigationTests(unittest.TestCase):
    def _viewer(self, root, log=LOG):
        viewer = KubejsViewer(root)
        self.addCleanup(self._destroy, viewer)
        viewer.set_log(log)
        viewer.errors_btn.setChecked(True)
        return viewer

    @staticmethod
    def _destroy(viewer):
        try:
            viewer.close()
            viewer.setParent(None)
            viewer.deleteLater()
            QApplication.processEvents()
        except RuntimeError:
            pass

    def test_errors_listed_from_log(self):
        with tempfile.TemporaryDirectory() as temp:
            viewer = self._viewer(_make_kubejs(temp))
            self.assertEqual(viewer.errors_list.count(), 1)
            self.assertIn('counter.js#501', viewer.errors_list.item(0).text())
            self.assertIn('1 处', viewer.errors_summary.text())

    def test_selecting_error_jumps_and_highlights(self):
        """核心:点报错要跳到那一行,并且只高亮那一行。"""
        with tempfile.TemporaryDirectory() as temp:
            viewer = self._viewer(_make_kubejs(temp))
            viewer.errors_list.setCurrentRow(0)
            QApplication.processEvents()
            self.assertIn('501', viewer.view.toPlainText())
            self.assertEqual(len(viewer.view.extraSelections()), 1)
            self.assertIn('补丁', viewer.errors_hint.text())

    def test_resolves_path_without_scripts_prefix(self):
        """日志里的路径不带 server_scripts 前缀,也要能找到文件。"""
        with tempfile.TemporaryDirectory() as temp:
            root = _make_kubejs(temp)
            viewer = self._viewer(root)
            self.assertTrue(viewer.select_file('business/counter.js', 501))

    def test_select_file_returns_false_when_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            viewer = self._viewer(_make_kubejs(temp))
            self.assertFalse(viewer.select_file('nope/missing.js', 1))

    def test_unresolvable_error_shows_explanation(self):
        with tempfile.TemporaryDirectory() as temp:
            log = ("[10:00:00] [Server thread/ERROR] [KubeJS Server/]: "
                   "ghost/gone.js#7: Error in 'X': TypeError: boom\n")
            viewer = self._viewer(_make_kubejs(temp), log=log)
            viewer.errors_list.setCurrentRow(0)
            QApplication.processEvents()
            self.assertIn('找不到脚本文件', viewer.view.toPlainText())

    def test_panel_hidden_until_toggled(self):
        with tempfile.TemporaryDirectory() as temp:
            viewer = KubejsViewer(_make_kubejs(temp))
            self.addCleanup(self._destroy, viewer)
            viewer.set_log(LOG)
            self.assertTrue(viewer.errors_panel.isHidden())
            viewer.errors_btn.setChecked(True)
            self.assertFalse(viewer.errors_panel.isHidden())

    def test_empty_log_reports_none(self):
        with tempfile.TemporaryDirectory() as temp:
            viewer = self._viewer(_make_kubejs(temp), log='all good\n')
            self.assertEqual(viewer.errors_list.count(), 0)
            self.assertIn('没有发现', viewer.errors_summary.text())


if __name__ == '__main__':
    unittest.main()
