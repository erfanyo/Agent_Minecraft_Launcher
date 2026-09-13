import os
from pathlib import Path
import tempfile
import tarfile
import unittest
import zipfile
from unittest.mock import patch
from java_manager import (_java_candidates, java_download_urls, java_version_probe,
                          ensure_java, list_java_installations, java_major)
from loaders import loader_processor_java_major


class JavaDiscoveryTests(unittest.TestCase):
    def test_collections_environment_siblings_registry_and_dedup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = [root / 'custom' / f'jdk-{major}' / 'bin' / 'java.exe' for major in (17, 21, 26)]
            paths += [root / 'registered' / 'bin' / 'java.exe', root / 'vendor' / 'jdk8' / 'bin' / 'java.exe']
            for path in paths:
                path.parent.mkdir(parents=True)
                path.touch()
            env = {'PATH': '"' + str(paths[0].parent) + '"', 'JAVA_HOME': str(paths[0].parent.parent)}
            with patch.dict(os.environ, env, clear=True), \
                 patch('java_manager._java_platform', return_value=('windows', '.zip', 'java.exe')), \
                 patch('java_manager._java_search_roots', return_value=[str(root / 'vendor')]), \
                 patch('java_manager._registry_java_homes', return_value=[str(paths[3].parent.parent)]):
                found = _java_candidates(str(root / 'runtime'), [str(paths[0])])
            self.assertEqual(set(found), {str(path) for path in paths})
            self.assertEqual(len(found), len(paths))

    def test_invalid_runtime_excluded_and_versions_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = [Path(temp, str(n), 'java.exe') for n in range(3)]
            for path in paths:
                path.parent.mkdir()
                path.touch()
            with patch('java_manager._java_candidates', return_value=list(map(str, paths))), \
                 patch('java_manager.java_major', side_effect=[21, 0, 17]):
                found = list_java_installations(temp)
            self.assertEqual([item['major'] for item in found], [17, 21])

    def test_version_capture_uses_separate_files(self):
        captures = []
        def probe(args, stdout, **kwargs):
            captures.append(stdout)
            stdout.write(b'openjdk version "21.0.12"')
        with patch('java_manager.subprocess.run', side_effect=probe):
            self.assertEqual(java_major('first'), 21)
            self.assertEqual(java_major('second'), 21)
        self.assertIsNot(captures[0], captures[1])
        self.assertTrue(all(file.closed for file in captures))

    def test_loader_processors_follow_minecraft_java_requirement(self):
        base = {"javaVersion": {"majorVersion": 21}}
        self.assertEqual(loader_processor_java_major(base, "1.21.1"), 21)
        self.assertEqual(loader_processor_java_major({}, "1.20.1"), 17)

    def test_java_download_has_independent_windows_fallback(self):
        sources = java_download_urls(21, "windows", "x64")
        self.assertEqual([name for name, _url in sources],
                         ["Eclipse Temurin", "Amazon Corretto"])
        self.assertTrue(all("21" in url for _name, url in sources))

    def test_linux_java_download_uses_tar_runtime(self):
        sources = java_download_urls(21, "linux", "x64")
        self.assertEqual([name for name, _url in sources], ["Eclipse Temurin"])
        self.assertIn("/linux/x64/jre/", sources[0][1])

    def test_linux_runtime_extracts_java_without_exe_suffix(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp, 'source.tar.gz')
            payload = Path(temp, 'java')
            payload.write_bytes(b'dummy')
            with tarfile.open(archive, 'w:gz') as package:
                package.add(payload, arcname='jdk/bin/java')
            runtime = Path(temp, 'runtime')

            def copy_download(_url, destination, **_kwargs):
                Path(destination).write_bytes(archive.read_bytes())

            with patch('java_manager.find_java', return_value=None), \
                 patch('java_manager.download_file', side_effect=copy_download), \
                 patch('java_manager.java_version_probe', return_value=(21, '')), \
                 patch('java_manager._java_platform', return_value=('linux', '.tar.gz', 'java')):
                result = ensure_java(str(runtime), 21)

            self.assertTrue(result.endswith(os.path.join('jdk', 'bin', 'java')))

    def test_java_probe_preserves_windows_launch_error(self):
        with patch('java_manager.subprocess.run', side_effect=OSError(193, 'not a valid application')):
            major, reason = java_version_probe('java.exe')
        self.assertEqual(major, 0)
        self.assertIn('not a valid application', reason)

    def test_missing_vc_runtime_is_repaired_then_same_java_is_rechecked(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp, 'source.zip')
            with zipfile.ZipFile(archive, 'w') as package:
                package.writestr('jdk/bin/java.exe', b'dummy')
            runtime = Path(temp, 'runtime')

            def copy_download(_url, destination, **_kwargs):
                Path(destination).write_bytes(archive.read_bytes())

            with patch('java_manager.find_java', return_value=None), \
                 patch('java_manager.download_file', side_effect=copy_download), \
                 patch('java_manager.java_version_probe', side_effect=[
                     (0, 'Error: could not find java.dll'), (21, '')]), \
                 patch('java_manager._java_platform', return_value=('windows', '.zip', 'java.exe')), \
                 patch('java_manager._is_windows', return_value=True), \
                 patch('windows_runtime_support.install_vc_runtime',
                       return_value=(True, '')) as repair:
                result = ensure_java(str(runtime), 21)

            self.assertTrue(result.endswith(os.path.join('jdk', 'bin', 'java.exe')))
            repair.assert_called_once()


if __name__ == '__main__':
    unittest.main()
