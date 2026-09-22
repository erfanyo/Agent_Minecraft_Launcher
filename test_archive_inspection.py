import tempfile
import unittest
import zipfile
import json
from pathlib import Path
from archive_inspection import inspect_archive
from server_packs import import_server_pack, list_servers


class ArchiveTests(unittest.TestCase):
    def test_dual_roots_and_ignore_command(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, 'pack.zip')
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('bundle/amcl-server-pack.json', json.dumps({
                    'schemaVersion': 1, 'serverRoot': '服务端', 'clientRoot': '客户端',
                    'startCommand': 'never execute this'}))
                archive.writestr('bundle/服务端/server.jar', 'jar')
                archive.writestr('bundle/客户端/mods/a.jar', 'mod')
            report = inspect_archive(path)
            self.assertEqual(report['serverRoot'], '服务端')
            self.assertNotIn('never execute', str(report))
            import_server_pack(path, root, report['sha256'])
            server = list_servers(root)[0]
            self.assertTrue(Path(server['path'], 'server.jar').exists())
            self.assertTrue(Path(server['packagePath'], '客户端/mods/a.jar').exists())

    def pack(self, root, names):
        path = Path(root, 'pack.zip')
        with zipfile.ZipFile(path, 'w') as archive:
            for name in names:
                archive.writestr(name, b'test')
        return path

    def test_unsafe_paths_and_collisions(self):
        for names in (['../escape'], ['C:evil'], ['a/NUL.txt'], ['a./file'],
                      ['mods/A.jar', 'mods/a.jar'], ['a', 'a/b'], ['/absolute']):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as root:
                with self.assertRaises(ValueError):
                    inspect_archive(self.pack(root, names))

    def test_limits(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.pack(root, ['one', 'two'])
            for kwargs in ({'max_files': 1}, {'max_single_file_bytes': 3}, {'max_expanded_bytes': 7}):
                with self.assertRaises(ValueError):
                    inspect_archive(path, **kwargs)

    def test_server_import_and_changed_archive(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.pack(root, ['bundle/server.properties', 'bundle/mods/a.jar'])
            report = inspect_archive(path)
            self.assertEqual(report['packageRoot'], 'bundle')
            self.assertEqual(report['kind'], 'server')
            self.assertFalse(report['scriptsWereExecuted'])
            dest = import_server_pack(path, root, report['sha256'])
            self.assertTrue(Path(dest, 'mods/a.jar').is_file())
            self.assertEqual(len(list_servers(root)), 1)
            self.pack(root, ['changed'])
            with self.assertRaises(ValueError):
                import_server_pack(path, root, report['sha256'])

    def test_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, 'pack.zip')
            with zipfile.ZipFile(path, 'w') as archive:
                info = zipfile.ZipInfo('link')
                info.create_system = 3
                info.external_attr = 0o120777 << 16
                archive.writestr(info, '../outside')
            with self.assertRaises(ValueError):
                inspect_archive(path)
