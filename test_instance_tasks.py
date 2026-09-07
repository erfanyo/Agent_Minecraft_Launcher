"""Regression tests for stable names, cancellation and resumable pack imports."""
import hashlib
import json
import os
import tempfile
import threading
import unittest
import zipfile
from unittest.mock import patch
from instance_metadata import atomic_json, rename_display
from instances import scan_instances
from task_context import TaskCancelled, cancel_event

class InstanceTests(unittest.TestCase):
    def test_physical_rename_and_rollback(self):
        from instance_metadata import rename_instance
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, 'versions', '1.20.1')
            atomic_json(os.path.join(folder, '1.20.1.json'), {'id': '1.20.1'})
            atomic_json(os.path.join(folder, 'launch_options.json'), {'memory_gb': 6})
            child = os.path.join(root, 'versions', 'forge', 'forge.json')
            atomic_json(child, {'id': 'forge', 'inheritsFrom': '1.20.1'})
            rename_instance(root, '1.20.1', '游戏')
            self.assertFalse(os.path.exists(folder))
            new = os.path.join(root, 'versions', '游戏')
            self.assertTrue(os.path.isfile(os.path.join(new, '游戏.json')))
            self.assertTrue(os.path.isfile(os.path.join(new, 'launch_options.json')))
            with open(child, encoding='utf-8') as file:
                self.assertEqual(json.load(file)['inheritsFrom'], '游戏')
            items = {i['id']: i for i in scan_instances(root)}
            self.assertEqual(items['游戏']['base'], '1.20.1')
            self.assertEqual(items['forge']['base'], '1.20.1')
            count = [0]
            def fail_second(path, value):
                count[0] += 1
                if count[0] == 2:
                    raise OSError('simulated disk error')
                atomic_json(path, value)
            with patch('instance_metadata.atomic_json', side_effect=fail_second):
                with self.assertRaises(OSError):
                    rename_instance(root, '游戏', '新版')
            with open(os.path.join(new, '游戏.json'), encoding='utf-8') as file:
                self.assertEqual(json.load(file)['id'], '游戏')
            self.assertFalse(os.path.exists(os.path.join(root, 'versions', '新版')))

    def test_launch_preparation_keeps_event_loop_responsive(self):
        import time
        from types import SimpleNamespace
        from PySide6.QtCore import QEventLoop, QTimer
        from PySide6.QtWidgets import QApplication, QWidget
        from main import MainWindow
        app = QApplication.instance() or QApplication([])
        loop = QEventLoop()
        ticks = []
        window = QWidget()
        window.selected_version = {'id': 'test'}
        window.settings = {}
        window.game_process = None
        window._launch_task = None
        window.download_tasks = SimpleNamespace(is_running=False)
        window.launch_btn = SimpleNamespace(setEnabled=lambda value: None)
        window.dl_indicator = SimpleNamespace(set_progress=lambda *a: None, setToolTip=lambda *a: None, show=lambda: None)
        window.statusBar = lambda: SimpleNamespace(showMessage=lambda text: None)
        window._on_download_status = lambda text: None
        window._on_download_progress = lambda *a: None
        window._on_download_cancelled = loop.quit
        window._on_launch_prepare_failed = lambda error: loop.quit()
        delivered = []
        window._start_prepared_game = lambda plan, version: (delivered.append(plan), loop.quit())
        def prepare(*a, **kw):
            time.sleep(0.15)
            return 'ready'
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(10)
        with patch('main.GameLaunchService') as service:
            service.return_value.prepare.side_effect = prepare
            MainWindow.launch_selected(window)
            QTimer.singleShot(2000, loop.quit)
            loop.exec()
        timer.stop()
        self.assertEqual(delivered, ['ready'])
        self.assertGreater(len(ticks), 2)

    def test_cancel_patch_process(self):
        import sys
        import time
        from task_context import run_process
        event = threading.Event()
        token = cancel_event.set(event)
        timer = threading.Timer(0.15, event.set)
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(TaskCancelled):
                run_process([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=10)
            self.assertLess(time.monotonic() - started, 5)
        finally:
            timer.cancel()
            cancel_event.reset(token)

    def test_inheritance_cycle_is_reported(self):
        from launcher import resolve_inherited_json
        with patch('launcher.load_version_json', return_value={'id': 'cycle', 'inheritsFrom': 'cycle'}):
            with self.assertRaisesRegex(ValueError, '循环继承'):
                resolve_inherited_json('cycle', 'unused')

    def test_name_keeps_files_and_parent_reference(self):
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, 'versions', '1.20.1')
            atomic_json(os.path.join(folder, '1.20.1.json'), {'id': '1.20.1'})
            atomic_json(os.path.join(folder, 'launch_options.json'), {'memory_gb': 6})
            other = os.path.join(root, 'versions', 'forge', 'forge.json')
            atomic_json(other, {'id': 'forge', 'inheritsFrom': '1.20.1'})
            rename_display(root, '1.20.1', '我的世界')
            items = {i['id']: i for i in scan_instances(root)}
            self.assertEqual(items['1.20.1']['name'], '我的世界')
            self.assertEqual(items['1.20.1']['base'], '1.20.1')
            self.assertEqual(items['forge']['base'], '1.20.1')
            self.assertTrue(os.path.isfile(os.path.join(folder, 'launch_options.json')))
            with self.assertRaises(ValueError):
                rename_display(root, 'forge', '我的世界')

    def test_cancel_during_stream_removes_partial(self):
        from downloader import download_file
        event = threading.Event()
        class Response:
            headers = {'content-length': '8'}
            def raise_for_status(self): pass
            def close(self): pass
            def iter_content(self, **kwargs):
                yield b'abcd'
                event.set()
                yield b'efgh'
        token = cancel_event.set(event)
        try:
            with tempfile.TemporaryDirectory() as root, patch('downloader.requests.get', return_value=Response()):
                dest = os.path.join(root, 'partial.jar')
                with self.assertRaises(TaskCancelled):
                    download_file('https://example.org', dest)
                self.assertFalse(os.path.exists(dest))
        finally:
            cancel_event.reset(token)

    def test_import_resume_downloads_only_missing_files(self):
        from modpack import import_modpack
        with tempfile.TemporaryDirectory() as root:
            pack = os.path.join(root, 'pack.mrpack')
            index = {'name': 'Pack', 'dependencies': {'minecraft': '1.20.1'},
                     'files': [{'path': 'mods/' + n, 'hashes': {'sha1': hashlib.sha1(b'ok').hexdigest()},
                                'downloads': ['https://example.org/' + n]} for n in ['a.jar', 'b.jar']]}
            with zipfile.ZipFile(pack, 'w') as archive:
                archive.writestr('modrinth.index.json', json.dumps(index))
            calls = []
            failed = [True]
            def download(url, dest, **kwargs):
                calls.append(os.path.basename(dest))
                if dest.endswith('b.jar') and failed[0]:
                    raise RuntimeError('timeout')
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, 'wb') as file: file.write(b'ok')
            with patch('modpack._ensure_base'), patch('modpack._install_loader_from_deps', return_value=None), patch('modpack.download_with_mirror', side_effect=download):
                with self.assertRaisesRegex(RuntimeError, 'timeout'):
                    import_modpack(pack, root)
                failed[0] = False
                self.assertEqual(import_modpack(pack, root), 'Pack')
            self.assertEqual(calls.count('a.jar'), 1)
            self.assertEqual(calls.count('b.jar'), 2)

if __name__ == '__main__':
    unittest.main()
