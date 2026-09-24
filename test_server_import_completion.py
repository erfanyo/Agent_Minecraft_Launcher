import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from archive_inspection import inspect_archive
from server_packs import import_server_pack, list_servers, set_server_launch_jar


class ImportCompletionTests(unittest.TestCase):
    def make_pack(self, root):
        path = Path(root, 'test.zip')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('bundle/server.properties', 'motd=test')
            archive.writestr('bundle/mods/example.jar', b'example')
        return path

    def test_no_directory_rename_and_visible_only_when_complete(self):
        with tempfile.TemporaryDirectory() as root:
            pack = self.make_pack(root)
            report = inspect_archive(pack)
            observations = []
            def status(message):
                observations.append(len(list_servers(root)))
            with patch('server_packs.os.rename', side_effect=PermissionError('directory locked')) as rename:
                result = import_server_pack(pack, root, report['sha256'], status_callback=status)
            rename.assert_not_called()
            self.assertTrue(all(count == 0 for count in observations))
            self.assertEqual(len(list_servers(root)), 1)
            self.assertFalse(Path(result, '.amcl-importing').exists())

    def test_commit_failure_keeps_hidden_files_and_source(self):
        with tempfile.TemporaryDirectory() as root:
            pack = self.make_pack(root)
            original = pack.read_bytes()
            report = inspect_archive(pack)
            with patch('server_packs.os.replace', side_effect=PermissionError('metadata locked')):
                with self.assertRaisesRegex(RuntimeError, 'metadata locked'):
                    import_server_pack(pack, root, report['sha256'])
            self.assertEqual(list_servers(root), [])
            folders = list(Path(root, 'servers').iterdir())
            self.assertEqual(len(folders), 1)
            self.assertTrue((folders[0] / '.amcl-importing').exists())
            self.assertTrue((folders[0] / 'mods/example.jar').exists())
            self.assertEqual(pack.read_bytes(), original)

    def test_selected_launch_jar_is_relative_and_persistent(self):
        with tempfile.TemporaryDirectory() as root:
            pack = self.make_pack(root)
            report = inspect_archive(pack)
            imported = Path(import_server_pack(pack, root, report['sha256']))
            jar = imported / 'custom-server.jar'
            jar.write_bytes(b'jar')
            server = list_servers(root)[0]
            self.assertEqual(set_server_launch_jar(server, jar), 'custom-server.jar')
            self.assertEqual(list_servers(root)[0]['launchJar'], 'custom-server.jar')
            set_server_launch_jar(server, None)
            self.assertIsNone(list_servers(root)[0]['launchJar'])

    def test_importing_identical_archive_reuses_existing_server(self):
        with tempfile.TemporaryDirectory() as root:
            pack = self.make_pack(root)
            report = inspect_archive(pack)
            first = import_server_pack(pack, root, report['sha256'],
                                       display_name='第一次导入')
            statuses = []
            second = import_server_pack(pack, root, report['sha256'],
                                        status_callback=statuses.append,
                                        display_name='不应创建的新实例')
            self.assertEqual(second, first)
            self.assertEqual(len(list(Path(root, 'servers').iterdir())), 1)
            self.assertEqual([item['name'] for item in list_servers(root)], ['第一次导入'])
            self.assertTrue(any('已经导入过' in message for message in statuses))

    def test_legacy_duplicate_is_hidden_without_deleting_its_directory(self):
        with tempfile.TemporaryDirectory() as root:
            servers = Path(root, 'servers')
            first = servers / 'server-first'
            second = servers / 'server-second'
            first.mkdir(parents=True)
            second.mkdir()
            report = {'sha256': 'a' * 64, 'serverRoot': None}
            (first / '.amcl-server.json').write_text(json.dumps({
                'name': '保留的实例', 'report': report}), encoding='utf-8')
            (second / '.amcl-server.json').write_text(json.dumps({
                'name': '重复实例', 'report': report}), encoding='utf-8')
            os.utime(first / '.amcl-server.json', ns=(1_000_000_000, 1_000_000_000))
            os.utime(second / '.amcl-server.json', ns=(2_000_000_000, 2_000_000_000))
            visible = list_servers(root)
            self.assertEqual([item['name'] for item in visible], ['保留的实例'])
            self.assertEqual(visible[0]['duplicatePackagePaths'], [str(second)])
            self.assertTrue(second.is_dir())

    def test_scan_progress_completes_monotonically(self):
        with tempfile.TemporaryDirectory() as root:
            pack = self.make_pack(root)
            progress = []
            inspect_archive(pack, progress_callback=lambda done, total: progress.append((done, total)))
            self.assertGreater(len(progress), 0)
            self.assertEqual(progress[-1][0], progress[-1][1])
            self.assertEqual(sorted(done for done, _ in progress), [done for done, _ in progress])

    def test_ui_failure_updates_log_and_state(self):
        import time
        from PySide6.QtWidgets import QApplication
        from server_center import ServerCenter
        app = QApplication.instance() or QApplication([])
        panel = ServerCenter()
        def fail(_):
            raise PermissionError('simulated access denied')
        with patch('server_center.QMessageBox.warning') as warning:
            panel._run(fail, lambda _: None)
            deadline = time.monotonic() + 5
            while panel._busy and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)
            self.assertFalse(panel._busy)
            self.assertTrue(panel.import_btn.isEnabled())
            self.assertIn('simulated access denied', panel.log.toPlainText())
            self.assertIn('处理失败', panel.task_status.text())
            warning.assert_called_once()
        panel.close()

    def test_large_progress_fits_qt_integer(self):
        from server_center import ServerCenter
        task = Mock()
        ServerCenter._report_progress(task, 8 * 1024**3, 16 * 1024**3)
        task.report_progress.assert_called_once_with(500, 1000)
