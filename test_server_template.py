import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from server_export import export_server_template, server_content_allowed
from archive_inspection import inspect_archive


class TemplateTests(unittest.TestCase):
    def test_template_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mod = root / 'mods/a.jar'
            mod.parent.mkdir()
            mod.write_bytes(b'test')
            out = root / 'export.zip'
            export_server_template(root, out, [(str(mod), 'mods/a.jar')], '1.19.2', 'forge', '43.3.8')
            report = inspect_archive(out)
            self.assertEqual(report['contentProfile'], 'server-content')
            self.assertEqual(report['declaredRuntime']['loaderVersion'], '43.3.8')
            self.assertIsNone(report['minecraftVersion'])  # declaration is not verified evidence
            with self.assertRaises(ValueError):
                export_server_template(root, out, [(str(mod), 'mods/a.jar')], '1.19.2', 'forge', '43.3.8')

    def test_filters(self):
        for name in ('../escape', 'server.properties', 'saves/world.dat', 'mods/a.jar.disabled',
                     'config/private.key', 'kubejs/run.bat', 'config/.secret'):
            self.assertFalse(server_content_allowed(name), name)
        self.assertTrue(server_content_allowed('config/mod.toml'))

    def test_defaults_and_disabled_tree(self):
        from PySide6.QtWidgets import QApplication
        from export_modpack import PackExportDialog
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'mods').mkdir()
            for name, side in [('client', 'client'), ('both', '*')]:
                with zipfile.ZipFile(root / f'mods/{name}.jar', 'w') as archive:
                    archive.writestr('fabric.mod.json', json.dumps({'id': name, 'environment': side}))
            (root / 'config').mkdir()
            (root / 'config/test.toml').write_text('private')
            (root / 'accounts.json').write_text('secret')
            dlg = PackExportDialog('test', temp, base='1.19.2', loader='fabric', server_mode=True)
            selected = {relative.replace('\\', '/') for _, relative in dlg._selected_files()}
            self.assertEqual(selected, {'mods/both.jar'})
            dlg._check_all(True)
            selected = {relative.replace('\\', '/') for _, relative in dlg._selected_files()}
            self.assertNotIn('accounts.json', selected)
            dlg.close()
