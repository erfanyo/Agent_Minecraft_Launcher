import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from advanced_launch import parse_jvm, apply_jvm
from instance_maintenance import current_core, perform, target


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.folder = Path(self.root, 'versions', 'demo')
        self.folder.mkdir(parents=True)
        self.stop = patch('instance_maintenance.assert_stopped')
        self.stop.start()
        self.addCleanup(self.stop.stop)

    def test_reset_preserves_player_data(self):
        for name in ('options.txt', 'launch_options.json', 'optionsof.txt', 'demo.jar'):
            (self.folder / name).write_text('original')
        for name in ('mods', 'saves', 'config'):
            (self.folder / name).mkdir()
            (self.folder / name / 'keep').write_text('keep')
        with patch('settings.load_settings', return_value={'version_isolation': True}):
            result = perform(self.root, 'demo', 'reset')
        self.assertIn('备份', result)
        self.assertFalse((self.folder / 'options.txt').exists())
        self.assertEqual((self.folder / 'saves' / 'keep').read_text(), 'keep')
        self.assertEqual((self.folder / 'mods' / 'keep').read_text(), 'keep')
        self.assertEqual((self.folder / 'config' / 'keep').read_text(), 'keep')
        self.assertEqual((self.folder / 'demo.jar').read_text(), 'original')
        self.assertEqual(len(list(Path(self.root).glob('versions/_maintenance/*/options.txt'))), 1)

    def test_shared_reset_refused(self):
        with patch('settings.load_settings', return_value={'version_isolation': False}):
            with self.assertRaises(ValueError):
                perform(self.root, 'demo', 'reset')

    def test_path_escape(self):
        with self.assertRaises(ValueError):
            target(self.root, '../outside')

    def test_failed_install_preserves_core(self):
        (self.folder / 'demo.jar').write_bytes(b'old')
        with patch('instance_install_service.InstanceInstallService.create_instance', side_effect=RuntimeError('network')):
            with self.assertRaises(RuntimeError):
                perform(self.root, 'demo', 'modify', version='1.21.1')
        self.assertEqual((self.folder / 'demo.jar').read_bytes(), b'old')

    def test_current_core_reads_flattened_neoforge_launch_argument(self):
        detail = {
            'id': 'demo', 'clientVersion': '1.21.1',
            'mainClass': 'cpw.mods.bootstraplauncher.BootstrapLauncher',
            'arguments': {'game': ['--fml.neoForgeVersion', '21.1.250',
                                   '--fml.mcVersion', '1.21.1']},
            'libraries': [],
        }
        (self.folder / 'demo.json').write_text(json.dumps(detail), encoding='utf-8')
        (self.folder / 'amcl_instance.json').write_text(
            json.dumps({'minecraft_version': '1.21.1', 'loader': 'neoforge'}), encoding='utf-8')
        self.assertEqual(current_core(self.root, 'demo'), ('1.21.1', 'neoforge', '21.1.250'))

    def test_modify_keeps_id_and_data(self):
        (self.folder / 'demo.jar').write_bytes(b'old')
        (self.folder / 'options.txt').write_text('keep')
        def install(service, *args, **kwargs):
            folder = Path(service.game_root, 'versions', '1.21.1')
            folder.mkdir(parents=True)
            (folder / '1.21.1.jar').write_bytes(b'new')
            (folder / '1.21.1.json').write_text(json.dumps({'id': '1.21.1', 'mainClass': 'test.Main', 'libraries': []}))
            return '1.21.1'
        with patch('instance_install_service.InstanceInstallService.create_instance', install):
            perform(self.root, 'demo', 'modify', version='1.21.1')
        self.assertEqual((self.folder / 'demo.jar').read_bytes(), b'new')
        self.assertEqual(json.loads((self.folder / 'demo.json').read_text())['id'], 'demo')
        self.assertEqual((self.folder / 'options.txt').read_text(), 'keep')

    def test_jvm_quotes_and_conflicts(self):
        self.assertEqual(parse_jvm('-Dpath="C:\\My Pack\\config"'), ['-Dpath=C:\\My Pack\\config'])
        self.assertEqual(apply_jvm(['java', '-XX:+UseG1GC', 'Main'], '-XX:+UseZGC'), ['java', '-XX:+UseZGC', 'Main'])
        for invalid in ('-Xmx8G', '-jar evil.jar', '"unclosed'):
            with self.assertRaises(ValueError):
                parse_jvm(invalid)

    def test_ui_sections_and_default_fold(self):
        from PySide6.QtWidgets import QApplication, QPushButton
        from instance_manager import InstanceManagerDialog
        app = QApplication.instance() or QApplication([])
        owner = InstanceManagerDialog({'id': 'demo', 'base': '1.21.1', 'loader': None}, self.root)
        self.assertIn('修改', owner.shell.menu.items())
        labels = {button.text() for button in owner.findChildren(QPushButton)}
        self.assertTrue({'修补核心', '补全文件', '重置'} <= labels)
        self.assertFalse(owner.jvm_editor.isChecked())
        self.assertIsNone(owner.jvm_editor.values())
        owner.close()


if __name__ == '__main__':
    unittest.main()
