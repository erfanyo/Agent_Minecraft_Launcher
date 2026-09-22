"""Offline regression checks; all credentials and packs are synthetic."""
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from log_privacy import redact, redact_text
from safe_paths import safe_child
from modpack import (_extract_zip_to, _download_mods_parallel,
                     _extract_optional_pack_icon)


class SafetyTests(unittest.TestCase):
    def test_redaction(self):
        settings = {'cloud_api_key': 'FAKE_PRIVATE_VALUE'}
        payload = {'user': 'my key is FAKE_PRIVATE_VALUE',
                   'reply': '--accessToken SECRETACCESS --session SECRETSESSION',
                   'tools': [{'key': 'api_key', 'value': 'HIDDENVALUE'},
                             {'result': 'https://example.org/?token=URLSECRET&ok=1'},
                             {'result': 'Authorization: Bearer BEARERSECRET'}]}
        output = json.dumps(redact(payload, settings))
        for value in ['FAKE_PRIVATE_VALUE', 'SECRETACCESS', 'SECRETSESSION',
                      'HIDDENVALUE', 'URLSECRET', 'BEARERSECRET']:
            self.assertNotIn(value, output)
        self.assertIn('user', output)
        self.assertNotIn('SERIALIZEDSECRET', redact_text('{"key":"api_key","value":"SERIALIZEDSECRET"}'))
        self.assertEqual(redact_text('Connection timeout: 403'), 'Connection timeout: 403')

    def test_paths(self):
        with tempfile.TemporaryDirectory() as root:
            expected = os.path.realpath(os.path.join(root, 'mods', 'good.jar'))
            self.assertEqual(safe_child(root, 'mods/good.jar'), expected)
            for path in ['../escape', 'mods/../../escape', r'mods\..\escape',
                         '/absolute', 'C:/outside', 'C:relative', r'\\server\file',
                         'mods/a:stream', 'NUL.txt', 'mods/.. /escape']:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    safe_child(root, path)

    def test_reject_pack_before_extracting(self):
        with tempfile.TemporaryDirectory() as root:
            pack = os.path.join(root, 'bad.zip')
            with zipfile.ZipFile(pack, 'w') as archive:
                archive.writestr('overrides/config/good.txt', 'good')
                archive.writestr('overrides/config/../../escape', 'bad')
            target = os.path.join(root, 'instance')
            with self.assertRaises(ValueError):
                _extract_zip_to(pack, target, 'overrides/')
            self.assertFalse(os.path.exists(target))

    def test_manifest_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as root, patch('modpack.download_with_mirror') as download:
            with self.assertRaises(ValueError):
                _download_mods_parallel([{'path': 'C:/escape', 'downloads': ['https://example.org']}], root)
            download.assert_not_called()

    def test_root_pack_icon_is_preserved_without_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            pack = os.path.join(root, 'pack.zip')
            target = os.path.join(root, 'instance')
            os.makedirs(target)
            with zipfile.ZipFile(pack, 'w') as archive:
                archive.writestr('icon.png', b'pack-icon')
            result = _extract_optional_pack_icon(pack, target)
            self.assertEqual(Path(result).read_bytes(), b'pack-icon')
            with open(os.path.join(target, 'icon.png'), 'wb') as file:
                file.write(b'user-icon')
            self.assertIsNone(_extract_optional_pack_icon(pack, target))
            self.assertEqual(Path(target, 'icon.png').read_bytes(), b'user-icon')

    def test_failed_file_propagates(self):
        with tempfile.TemporaryDirectory() as root, patch('modpack.download_with_mirror', side_effect=RuntimeError('timeout')):
            with self.assertRaisesRegex(RuntimeError, 'timeout'):
                _download_mods_parallel([{'path': 'mods/a.jar', 'downloads': ['https://example.org']}], root)

    def test_controller_and_indicator(self):
        from PySide6.QtCore import QEventLoop, QTimer
        from PySide6.QtWidgets import QApplication
        from task_controllers import DownloadTaskController
        from download_indicator import DownloadIndicator
        app = QApplication.instance() or QApplication([])
        for worker in [lambda s, p: s('❌ 下载失败: timeout'), lambda s, p: False]:
            loop = QEventLoop()
            controller = DownloadTaskController()
            results = []
            controller.completed.connect(lambda ok, error: (results.append(ok), loop.quit()))
            controller.start(worker)
            QTimer.singleShot(2000, loop.quit)
            loop.exec()
            self.assertEqual(results, [False])
        ball = DownloadIndicator()
        ball.set_progress(1, 1)
        ball.set_failed()
        self.assertTrue(ball._failed)
        ball.grab()  # Exercise the actual red-X painter.
        ball.set_progress(0, 1)
        self.assertFalse(ball._failed)
        ball.set_progress(1, 1)
        ball.set_completed()
        self.assertTrue(ball._completed)
        ball.grab()


if __name__ == '__main__':
    unittest.main()
