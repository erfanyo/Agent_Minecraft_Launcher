import os
import unittest
from unittest.mock import patch

from os_platform.process import sanitized_subprocess_environment


class ExternalProcessEnvironmentTests(unittest.TestCase):
    def test_frozen_bundle_directory_is_removed_from_path(self):
        bundle = os.path.abspath(os.path.join('tmp', '_MEI-test'))
        keep = os.path.abspath(os.path.join('tools', 'java', 'bin'))
        source = {'PATH': os.pathsep.join([bundle, os.path.join(bundle, 'PySide6'), keep])}
        with patch('os_platform.process.sys.frozen', True, create=True), \
             patch('os_platform.process.sys._MEIPASS', bundle, create=True):
            cleaned = sanitized_subprocess_environment(source)
        self.assertEqual(cleaned['PATH'], keep)

    def test_dedicated_external_runtime_is_exposed_to_child(self):
        bundle = os.path.abspath(os.path.join('tmp', '_MEI-test'))
        runtime = os.path.join(os.path.normcase(os.path.realpath(bundle)), 'external-runtime')
        with patch('os_platform.process.sys.frozen', True, create=True), \
             patch('os_platform.process.sys._MEIPASS', bundle, create=True), \
             patch('os_platform.process.os.path.isdir', side_effect=lambda path: path == runtime):
            cleaned = sanitized_subprocess_environment({'PATH': ''})
        self.assertEqual(cleaned['PATH'], runtime)


if __name__ == '__main__':
    unittest.main()
