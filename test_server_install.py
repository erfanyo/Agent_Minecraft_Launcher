import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
import server_install as install


class InstallTests(unittest.TestCase):
    def test_runtime_identity_prefers_detected_values_and_uses_declared_fallback(self):
        identity = install.inferred_runtime_identity({
            'loader': 'unknown', 'minecraftVersion': None,
            'declaredRuntime': {'loader': 'forge', 'minecraftVersion': '1.19.2',
                                'loaderVersion': '43.3.8', 'requiredJava': 17}})
        self.assertEqual(identity, {
            'loader': 'forge', 'minecraftVersion': '1.19.2',
            'loaderVersion': '43.3.8', 'requiredJava': 17})
        detected = install.inferred_runtime_identity({
            'loader': 'neoforge', 'minecraftVersion': '1.21.1',
            'loaderVersion': '21.1.100',
            'declaredRuntime': {'loader': 'forge', 'minecraftVersion': '1.20.1'}})
        self.assertEqual(detected['loader'], 'neoforge')
        self.assertEqual(detected['minecraftVersion'], '1.21.1')

    def test_source(self):
        self.assertIn('/1.19.2-43.3.8/', install.installer_source('forge', '1.19.2', '43.3.8'))
        self.assertIn('/21.1.100/', install.installer_source('neoforge', '1.21.1', '21.1.100'))
        for args in [('forge', '../x', '43.3.8'), ('forge', '1.19.2', '../bad'),
                     ('neoforge', '1.21.1', '20.4.1'), ('forge', '1.16.5', '36.2.42')]:
            with self.assertRaises(ValueError):
                install.installer_source(*args)

    def run_install(self, root, conflict=False, fail_final=False):
        plan = {'loader': 'forge', 'minecraftVersion': '1.19.2', 'entry': 'test'}
        def process(command, **kwargs):
            stage = Path(kwargs['cwd'])
            (stage / 'libraries').mkdir()
            (stage / 'libraries/lib.jar').write_bytes(b'official')
            (stage / 'run.bat').write_text('not copied')
            return Mock(returncode=0)
        with patch.object(install, 'java_version_probe', return_value=(17, '')), \
             patch.object(install.requests, 'get', return_value=Mock(text='a' * 40)), \
             patch.object(install, 'download_with_mirror') as download, \
             patch.object(install, 'run_process', side_effect=process), \
             patch.object(install, 'build_launch_plan', side_effect=[plan, ValueError('bad final')] if fail_final else None,
                          return_value=plan):
            result = install.install_server_runtime(root, 'forge', '1.19.2', '43.3.8', 'java')
            self.assertEqual(download.call_args.kwargs['sha1'], 'a' * 40)
            return result

    def test_publish_missing_only(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'server.properties').write_text('private')
            self.run_install(root)
            self.assertEqual(Path(root, 'libraries/lib.jar').read_bytes(), b'official')
            self.assertFalse(Path(root, 'run.bat').exists())
            self.assertEqual(Path(root, 'server.properties').read_text(), 'private')

    def test_conflict_preserves_file(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root, 'libraries/lib.jar')
            file.parent.mkdir()
            file.write_bytes(b'original')
            with self.assertRaises(ValueError):
                self.run_install(root)
            self.assertEqual(file.read_bytes(), b'original')

    def test_failed_final_check_rolls_back_added_files(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                self.run_install(root, fail_final=True)
            self.assertFalse(Path(root, 'libraries/lib.jar').exists())
