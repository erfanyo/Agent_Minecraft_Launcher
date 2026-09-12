"""Exercise window event handlers without starting launcher services."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
from PySide6.QtCore import Qt, QUrl


def handler(name):
    tree = ast.parse(Path(__file__).with_name('main.py').read_text(encoding='utf-8-sig'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MainWindow')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = {'os': os, 'Qt': Qt}
    exec(compile(ast.Module(body=[method], type_ignores=[]), 'main.py', 'exec'), namespace)
    return namespace[name], namespace


class WindowImportTests(unittest.TestCase):
    def test_parent_drop_routes_folders_and_archives_separately(self):
        with tempfile.TemporaryDirectory() as root:
            owner = Mock()
            owner._on_my_instances_page.return_value = True
            event = Mock()
            event.mimeData.return_value.urls.return_value = [
                QUrl.fromLocalFile(root), QUrl.fromLocalFile(root),
                QUrl.fromLocalFile(root + '/pack.zip')]
            method, _ = handler('dropEvent')
            with patch('folder_instance_import.start_import') as start:
                method(owner, event)
            start.assert_called_once_with(owner, [QUrl.fromLocalFile(root).toLocalFile()])
            owner.install_modpack_from_path.assert_called_once_with(
                QUrl.fromLocalFile(root + '/pack.zip').toLocalFile())
            event.setDropAction.assert_called_once_with(Qt.DropAction.CopyAction)

    def test_changes_during_scan_are_retried(self):
        owner = Mock()
        owner.settings = {}
        owner.instance_list.currentItem.return_value = None
        owner.instance_catalog.refresh.return_value = []
        method, namespace = handler('refresh_instances')
        namespace['paths'] = SimpleNamespace(GAME_DIR='game')
        with patch('instance_catalog_service.fingerprint', side_effect=['before', 'after']) as fingerprint:
            method(owner)
            self.assertNotEqual(owner._instance_fingerprint, fingerprint('game'))
        owner.home_panel.set_current_instances.assert_called_once_with([])

    def test_watch_new_root_and_instance_contents(self):
        with tempfile.TemporaryDirectory() as root:
            child = Path(root, 'versions', 'demo')
            child.mkdir(parents=True)
            owner = Mock()
            owner._inst_watcher.directories.return_value = []
            method, namespace = handler('_watch_versions_dir')
            namespace['paths'] = SimpleNamespace(GAME_DIR=root)
            method(owner)
            owner._inst_watcher.addPath.assert_any_call(root)
            owner._inst_watcher.addPaths.assert_called_once_with([str(child)])


if __name__ == '__main__':
    unittest.main()
