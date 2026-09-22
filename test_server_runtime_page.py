# -*- coding: utf-8 -*-
"""服务端详情「运行配置」页的集成单测。

在临时目录里造一个假服务端,验证页面真能把内存/额外参数写进 user_jvm_args.txt,
以及非法输入不会落盘。不碰任何真实服务端。
"""
import json
import os
import tempfile
import unittest

from PySide6.QtWidgets import QApplication, QLineEdit, QSpinBox

_app = QApplication.instance() or QApplication([])

import server_jvm as sj
import server_jvm_io as sj_io
from server_details import ServerDetailsView


def _fake_server(temp, jvm_text=None):
    server_dir = os.path.join(temp, 'server')
    os.makedirs(os.path.join(server_dir, 'mods'), exist_ok=True)
    if jvm_text is not None:
        with open(sj_io.jvm_args_path(server_dir), 'w', encoding='utf-8') as f:
            f.write(jvm_text)
    package = os.path.join(temp, 'package')
    os.makedirs(package, exist_ok=True)
    with open(os.path.join(package, '.amcl-server.json'), 'w',
              encoding='utf-8') as f:
        json.dump({'name': 'Test', 'report': {}, 'ui_state': {}}, f)
    return {'id': 'package', 'name': 'Test', 'path': server_dir,
            'packagePath': package, 'report': {}, 'candidate': False}


class RuntimePageTests(unittest.TestCase):
    def _view(self, record):
        view = ServerDetailsView()
        self.addCleanup(self._destroy, view)
        view.set_server(record)
        labels = view.shell.menu.items()
        view.shell.switch_to(labels.index('运行配置'))
        return view

    @staticmethod
    def _destroy(view):
        try:
            view.close()
            view.setParent(None)
            view.deleteLater()
            QApplication.processEvents()
        except RuntimeError:
            pass

    def test_saves_memory_to_jvm_args_file(self):
        with tempfile.TemporaryDirectory() as temp:
            record = _fake_server(temp)
            view = self._view(record)
            view.jvm_max_spin.setValue(6)
            view.jvm_min_spin.setValue(2)
            view.jvm_extra_edit.setText('-XX:+UseZGC')
            view._save_runtime()
            info = sj_io.current_settings(record['path'])
            self.assertEqual((info['max'], info['min']), ('6G', '2G'))
            self.assertIn('-XX:+UseZGC', info['extras'])

    def test_rejects_unsupported_extra_without_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            record = _fake_server(temp, '-Xmx4G\n')
            view = self._view(record)
            view.jvm_extra_edit.setText('-javaagent:evil.jar')
            view._save_runtime()
            self.assertIn('⛔', view.jvm_status.text())
            self.assertNotIn('javaagent',
                             sj_io.read_text(sj_io.jvm_args_path(record['path'])))

    def test_rejects_min_greater_than_max(self):
        with tempfile.TemporaryDirectory() as temp:
            record = _fake_server(temp, '-Xmx4G\n')
            view = self._view(record)
            view.jvm_max_spin.setValue(2)
            view.jvm_min_spin.setValue(8)
            view._save_runtime()
            self.assertIn('⛔', view.jvm_status.text())
            self.assertEqual(sj_io.current_settings(record['path'])['max'], '4G')

    def test_reads_existing_values_into_widgets(self):
        with tempfile.TemporaryDirectory() as temp:
            record = _fake_server(temp, '-Xmx8G\n-Xms3G\n-XX:+UseZGC\n')
            view = self._view(record)
            self.assertEqual(view.jvm_max_spin.value(), 8)
            self.assertEqual(view.jvm_min_spin.value(), 3)
            self.assertIn('-XX:+UseZGC', view.jvm_extra_edit.text())

    def test_gc_button_replaces_same_family(self):
        """同族 GC 开关只能留一个,否则 JVM 会报冲突。"""
        with tempfile.TemporaryDirectory() as temp:
            record = _fake_server(temp)
            view = self._view(record)
            view._append_jvm_arg('-XX:+UseG1GC')
            view._append_jvm_arg('-XX:+UseZGC')
            args = sj.tokenize(view.jvm_extra_edit.text())
            gcs = [a for a in args if a.endswith('GC')]
            self.assertEqual(len(gcs), 1)
            self.assertIn('-XX:+UseZGC', gcs)

    def test_unsupported_existing_arg_is_warned_and_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            record = _fake_server(temp, '-Xmx4G\n-Xmn1G\n')
            view = self._view(record)
            view.jvm_max_spin.setValue(6)
            view._save_runtime()
            self.assertIn('⛔', view.jvm_status.text())
            self.assertIn('-Xmn1G', sj_io.read_text(
                sj_io.jvm_args_path(record['path'])))

    def test_backup_created_on_first_save(self):
        with tempfile.TemporaryDirectory() as temp:
            record = _fake_server(temp, '-Xmx4G\n')
            view = self._view(record)
            view.jvm_max_spin.setValue(8)
            view._save_runtime()
            self.assertTrue(os.path.isfile(
                sj_io.jvm_args_path(record['path']) + sj_io.BACKUP_SUFFIX))


if __name__ == '__main__':
    unittest.main()
