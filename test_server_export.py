import json
import tempfile
import unittest
from pathlib import Path
import zipfile
from server_export import export_runtime_pack
from archive_inspection import inspect_archive
from test_server_launch import ServerLaunchTests


class ExportTests(unittest.TestCase):
    def test_fabric_runtime_pack_contains_launcher_server_and_libraries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp, 'fabric')
            library = root / 'libraries/net/fabricmc/fabric-loader/0.19.5/fabric-loader-0.19.5.jar'
            library.parent.mkdir(parents=True)
            library.write_bytes(b'loader')
            (root / 'fabric-server-launch.jar').write_bytes(b'launcher')
            (root / 'fabric-server-launcher.properties').write_text('serverJar=server.jar')
            with zipfile.ZipFile(root / 'server.jar', 'w') as archive:
                archive.writestr('version.json', json.dumps({'id': '1.21.1'}))
            (root / 'eula.txt').write_text('eula=true')
            output = Path(temp, 'fabric.zip')
            export_runtime_pack(root, output)
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                self.assertIn('server/fabric-server-launch.jar', names)
                self.assertIn('server/server.jar', names)
                self.assertIn('server/fabric-server-launcher.properties', names)
                self.assertNotIn('server/eula.txt', names)
                manifest = json.loads(archive.read('amcl-server-pack.json'))
                self.assertEqual(manifest['loaderVersion'], '0.19.5')
            self.assertEqual(inspect_archive(output)['loader'], 'fabric')

    def test_round_trip_manifest_and_omissions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp, 'private-local-name')
            root.mkdir()
            args = ServerLaunchTests().fixture(root)
            # Fixture works on either host; add the other platform's equivalent.
            args.with_name('unix_args.txt').write_text(args.read_text(), encoding='utf-8')
            Path(root, 'server.properties').write_text('rcon.password=PRIVATE_TEST_SECRET')
            Path(root, 'whitelist.json').write_text('PRIVATE_PLAYER')
            Path(root, 'config').mkdir()
            Path(root, 'config/key.json').write_text('PRIVATE_KEY')
            output = Path(temp, 'export.zip')
            export_runtime_pack(root, output)
            with zipfile.ZipFile(output) as archive:
                data = archive.read('amcl-server-pack.json').decode('utf-8')
                manifest = json.loads(data)
                self.assertEqual(manifest['minecraftVersion'], '1.19.2')
                self.assertEqual(manifest['loaderVersion'], '43.3.8')
                self.assertNotIn('startCommand', manifest)
                self.assertNotIn(str(root), data)
                self.assertFalse(any('properties' in name or 'config/' in name or 'whitelist' in name for name in archive.namelist()))
            report = inspect_archive(output)
            self.assertEqual(report['serverRoot'], 'server')
            self.assertEqual(report['contentProfile'], 'runtime-and-mods')
            with self.assertRaises(ValueError):
                export_runtime_pack(root, output)
