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


if __name__ == '__main__':
    unittest.main()
