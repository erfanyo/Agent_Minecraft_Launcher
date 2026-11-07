import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import zipfile
import os
from launcher_app.resources.modpack import detect_modpack_format


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
        from launcher_app.ui.pack_import_controller import PackImportController
        with tempfile.TemporaryDirectory() as root:
            pack = Path(root, 'server.zip')
            with zipfile.ZipFile(pack, 'w') as archive:
                archive.writestr('server.properties', '')
            route, submit = Mock(), Mock()
            controller = PackImportController(
                parent=None, smart_enabled=lambda: False, smart_import=Mock(), choose_archive=Mock(),
                check_archive=Mock(), import_server=route, import_directory=Mock(), submit=submit,
                game_root=lambda: root, show_status=Mock())
            # Routing starts after the separately tested safety preflight.
            controller.import_archive(str(pack), safety_checked=True, classic=False)
            route.assert_called_once_with(str(pack))
            submit.assert_not_called()

    def test_client_still_detected(self):
        with tempfile.TemporaryDirectory() as root:
            pack = Path(root, 'client.mrpack')
            with zipfile.ZipFile(pack, 'w') as archive:
                archive.writestr('modrinth.index.json', '{}')
            self.assertEqual(detect_modpack_format(pack), 'modrinth')
