# -*- coding: utf-8 -*-
"""「获取可用模型」下拉弹层的可见项数限制。

背景: 模型列表可能有几百个, Windows 原生弹层会无视 setMaxVisibleItems,
      弹层高度顶住屏幕上下边框。这里固化为 Qt 弹层 + 限高。
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QListView

from assistant import (AISettingsForm, AIQuickSettingsForm,
                       _commit_combo_search)

_app = QApplication.instance() or QApplication([])

MAX_VISIBLE = 12      # 上限(实现里是 10)


class ComboPopupLimitTests(unittest.TestCase):
    def _fill(self, combo, n=300):
        combo.clear()
        for i in range(n):
            combo.addItem(f"Qwen/model-{i:03d}", f"m{i}")

    def _check(self, combo):
        self._fill(combo)
        combo.show()
        _app.processEvents()
        # 用 Qt 自己的弹层(Windows 原生弹层会忽略最大可见项数)
        self.assertIsInstance(combo.view(), QListView)
        self.assertLessEqual(combo.maxVisibleItems(), MAX_VISIBLE,
                             "下拉弹层可见项数应受限,否则会顶住屏幕上下边框")
        self.assertIn("combobox-popup: 0", combo.styleSheet())
        combo.hide()

    def test_quick_form_combo_limited(self):
        self._form = AIQuickSettingsForm({})      # 留引用,否则表单被 GC 掉
        self._check(self._form.remote_models)

    def test_settings_form_combo_limited(self):
        self._form = AISettingsForm({})
        self._check(self._form.remote_models)

    def test_model_combo_is_searchable(self):
        """下拉应可打字搜索:输入关键词回车 → 选中该项并写回模型名。"""
        form = AIQuickSettingsForm({})
        self._form = form
        combo = form.remote_models
        self._fill(combo)
        combo.setCurrentIndex(0)
        self.assertTrue(combo.isEditable(), "下拉应可编辑以便搜索")
        self.assertIsNotNone(combo.completer(), "应挂 QCompleter")

        combo.lineEdit().setText("model-123")
        _commit_combo_search(combo)
        self.assertEqual(combo.currentData(), "m123", "回车应选中匹配项")
        self.assertEqual(form.model.text(), "m123", "选中后应写回模型名")

    def test_settings_form_combo_searchable(self):
        form = AISettingsForm({})
        self._form = form
        combo = form.remote_models
        self._fill(combo)
        combo.lineEdit().setText("model-007")
        _commit_combo_search(combo)
        self.assertEqual(combo.currentData(), "m7")
        self.assertEqual(form.cloud_model.text(), "m7")


if __name__ == "__main__":
    unittest.main()
