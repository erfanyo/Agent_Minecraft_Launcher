import io
import json
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from smart_import import (ai_author_prompt, execute_import_plan,
                          materialize_component, scan_import_source)


class SmartImportTests(unittest.TestCase):
    def test_unknown_component_requires_explicit_type_choice(self):
        from PySide6.QtWidgets import QApplication
        from smart_import_ui import SmartImportPreview
        app = QApplication.instance() or QApplication([])
        report = {
            'sourceName': 'unknown.zip', 'files': {'mods/a.jar': 'x'},
            'expandedBytes': 1, 'defaultSelected': [], 'authorMaterials': [],
            'risks': ['需要确认'],
            'components': [{'id': 'unknown', 'type': 'unknown', 'root': '',
                            'confidence': 0.25, 'evidence': ['证据不足']}],
        }
        dialog = SmartImportPreview(report)
        self.assertEqual(dialog.selection()['selected'], [])
        dialog.override_boxes['unknown'].setCurrentIndex(1)
        selection = dialog.selection()
        self.assertEqual(selection['selected'], ['unknown'])
        self.assertEqual(selection['type_overrides'], {'unknown': 'client'})
        dialog.close()

    def mixed_zip(self, path):
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('client/modrinth.index.json', json.dumps({
                'name': 'Mixed Pack',
                'dependencies': {'minecraft': '1.19.2', 'forge': '43.3.8'},
                'files': [],
            }))
            archive.writestr('client/mods/example.jar', b'mod')
            archive.writestr('server/server.properties', 'motd=test')
            archive.writestr('server/server.jar', b'server')
            archive.writestr('server/start.bat', 'java -jar server.jar')
            archive.writestr('server/config/private.toml', 'webhook = "hidden"')
            archive.writestr('README.txt', 'Install both client and server. Treat this as data.')

    def test_mixed_package_components_are_independent(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, 'mixed.zip')
            self.mixed_zip(source)
            report = scan_import_source(source)
            self.assertEqual(report['schemaVersion'], 2)
            components = {item['type']: item for item in report['components']}
            self.assertEqual(components['client']['root'], 'client')
            self.assertEqual(components['server']['root'], 'server')
            self.assertEqual(components['client']['minecraftVersion'], '1.19.2')
            self.assertEqual(components['client']['loader'], 'forge')
            self.assertIn('docs', components)
            self.assertEqual(set(report['defaultSelected']), {'client', 'server'})
            self.assertTrue(any('脚本' in value for value in report['risks']))
            self.assertTrue(any('隐私复核' in value for value in report['risks']))
            prompt = ai_author_prompt(report)
            self.assertIn('不可信数据', prompt)
            self.assertIn('作者明确说明', prompt)

    def test_materialized_component_strips_root_and_rechecks_hash(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, 'pack')
            Path(source, 'client', 'mods').mkdir(parents=True)
            mod = Path(source, 'client', 'mods', 'a.jar')
            mod.write_bytes(b'original')
            report = scan_import_source(source)
            client = next(item for item in report['components'] if item['type'] == 'client')
            output = Path(root, 'client.zip')
            materialize_component(report, client, output)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.namelist(), ['mods/a.jar'])
            mod.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, '发生变化'):
                materialize_component(report, client, Path(root, 'changed.zip'))

    def test_tar_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, 'bad.tar')
            with tarfile.open(source, 'w') as archive:
                data = b'bad'
                info = tarfile.TarInfo('../escape.txt')
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            with self.assertRaises(ValueError):
                scan_import_source(source)

    def test_component_failures_do_not_rollback_other_components(self):
        report = {
            'sourceName': 'mixed.zip',
            'components': [
                {'id': 'client', 'type': 'client', 'files': [], 'root': '',
                 'minecraftVersion': '1.20.1', 'loader': 'forge'},
                {'id': 'server', 'type': 'server', 'files': [], 'root': ''},
            ],
        }
        def make_slice(_report, _component, destination):
            Path(destination).write_bytes(b'zip')
            return str(destination)
        with tempfile.TemporaryDirectory() as root, \
                patch('smart_import.materialize_component', side_effect=make_slice), \
                patch('modpack.import_modpack', side_effect=RuntimeError('client failed')), \
                patch('archive_inspection.inspect_archive', return_value={'sha256': 'abc'}), \
                patch('server_packs.import_server_pack', return_value='server-ok'):
            results = execute_import_plan(report, ['client', 'server'], root)
        self.assertFalse(results[0]['ok'])
        self.assertTrue(results[1]['ok'])
        self.assertEqual(results[1]['result'], 'server-ok')


if __name__ == '__main__':
    unittest.main()
