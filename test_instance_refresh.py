import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from instance_catalog_service import InstanceCatalogService
from instance_catalog_service import fingerprint


class RefreshTests(unittest.TestCase):
    def test_record_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as root:
            service = InstanceCatalogService(lambda: root, lambda i: str(Path(root, 'versions', i)))
            rows = [{'id': 'demo', 'base': '1.21.1', 'loader': None}]
            service.write_record(rows)
            record = Path(root, 'versions', '实例记录.json')
            before = record.stat().st_mtime_ns
            service.write_record(rows)
            self.assertEqual(before, record.stat().st_mtime_ns)

    def test_delayed_copy_and_new_versions_directory(self):
        with tempfile.TemporaryDirectory() as root:
            before = fingerprint(root)
            folder = Path(root, 'versions', 'demo')
            folder.mkdir(parents=True)
            empty = fingerprint(root)
            self.assertNotEqual(before, empty)
            (folder / 'demo.json').write_text('{"id":"demo"}')
            ready = fingerprint(root)
            self.assertNotEqual(empty, ready)
            Path(root, 'versions', '实例记录.json').write_text('{}')
            self.assertEqual(ready, fingerprint(root))

    def test_cancel_keeps_game_directory(self):
        from PySide6.QtWidgets import QApplication, QLineEdit, QFileDialog
        from settings.center import SettingsCenter
        app = QApplication.instance() or QApplication([])
        owner = Mock()
        owner.game_dir_edit = QLineEdit('E:/test/.minecraft')
        with patch.object(QFileDialog, 'getExistingDirectory', return_value='') as dialog:
            SettingsCenter._browse_game_dir(owner)
        self.assertEqual(owner.game_dir_edit.text(), 'E:/test/.minecraft')
        self.assertEqual(dialog.call_args.args[3], QFileDialog.Option.DontUseNativeDialog)

    def test_home_path_combo_rebuild_does_not_emit_change(self):
        from PySide6.QtWidgets import QApplication, QComboBox
        from version_home import VersionHome
        app = QApplication.instance() or QApplication([])
        owner = Mock()
        owner.game_dir_combo = QComboBox()
        owner._game_dirs.return_value = ['D:/other/.minecraft']
        changed = Mock()
        owner.game_dir_combo.currentIndexChanged.connect(changed)
        with patch('settings.load_settings', return_value={
                'game_dir': 'E:/test/.minecraft',
                'game_dirs_history': ['D:/other/.minecraft']}):
            VersionHome._fill_game_dir_combo(owner)
        changed.assert_not_called()
        self.assertEqual(owner.game_dir_combo.itemData(0), 'E:/test/.minecraft')
        self.assertEqual(owner.game_dir_combo.itemData(owner.game_dir_combo.count() - 1), '__add__')

    def test_home_cancel_only_restores_combo(self):
        from PySide6.QtWidgets import QApplication, QFileDialog
        from version_home import VersionHome
        app = QApplication.instance() or QApplication([])
        owner = Mock()
        with patch.object(QFileDialog, 'getExistingDirectory', return_value='') as dialog:
            VersionHome._add_new_game_dir(owner)
        owner._fill_game_dir_combo.assert_called_once_with()
        owner._set_game_dir.assert_not_called()
        self.assertEqual(dialog.call_args.args[3], QFileDialog.Option.DontUseNativeDialog)

    def test_home_path_change_requests_one_refresh(self):
        from version_home import VersionHome
        owner = Mock()
        owner._game_dirs.return_value = []
        with patch('settings.load_settings', return_value={}) as load, \
             patch('settings.save_settings') as save, \
             patch('paths.set_game_dir') as set_dir:
            VersionHome._set_game_dir(owner, 'E:/new/.minecraft')
        set_dir.assert_called_once_with('E:/new/.minecraft')
        owner.refresh_requested.emit.assert_called_once_with()
        owner._fill_game_dir_combo.assert_called_once_with()
        save.assert_called_once()


if __name__ == '__main__':
    unittest.main()
