import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from java_manager import _java_candidates, list_java_installations, java_major


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


if __name__ == '__main__':
    unittest.main()
