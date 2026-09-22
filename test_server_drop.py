import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import zipfile
import os
from modpack import detect_modpack_format


class ServerDropTests(unittest.TestCase):
    def test_detect_server_layouts(self):
        for name in ('amcl-server-pack.json', 'bundle/server.properties',
                     'bundle/libraries/net/minecraftforge/forge/1.19.2-43.3.8/win_args.txt',
                     'libraries/net/neoforged/neoforge/21.1.100/unix_args.txt'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                pack = Path(root, 'pack.zip')
                with zipfile.ZipFile(pack, 'w') as archive:
                    archive.writestr(name, '{}')
                    # Keep conventional wrapped/unwrapped layout including mods.
                    prefix = 'bundle/' if name.startswith('bundle/') else ''
                    archive.writestr(prefix + 'mods/test.jar', b'test')
                self.assertEqual(detect_modpack_format(pack), 'server')

    def test_drop_routes_without_client_installer(self):
        # Load just the real routing method, without initializing the application.
        source = ast.parse(Path(__file__).with_name('main.py').read_text(encoding='utf-8-sig'))
        method = next(node for node in ast.walk(source)
                      if isinstance(node, ast.FunctionDef) and node.name == 'install_modpack_from_path')
        namespace = {'os': os}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), 'main.py', 'exec'), namespace)
        with tempfile.TemporaryDirectory() as root:
            pack = Path(root, 'server.zip')
            with zipfile.ZipFile(pack, 'w') as archive:
                archive.writestr('server.properties', '')
            window = Mock()
            window.home_panel._server_tab_index = 1
            namespace['install_modpack_from_path'](window, str(pack))
            window.home_panel.tabs.setCurrentIndex.assert_called_once_with(1)
            window.home_panel.server_center.scan_import.assert_called_once_with(str(pack))
            window._run_download.assert_not_called()

    def test_client_still_detected(self):
        with tempfile.TemporaryDirectory() as root:
            pack = Path(root, 'client.mrpack')
            with zipfile.ZipFile(pack, 'w') as archive:
                archive.writestr('modrinth.index.json', '{}')
            self.assertEqual(detect_modpack_format(pack), 'modrinth')
