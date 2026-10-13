import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
import shutil
from server_staging import server_staging_directory


class ServerStagingTests(unittest.TestCase):
    def test_nonempty_windows_directory_is_retried(self):
        error = OSError('Directory not empty')
        error.winerror = 145
        real_remove = shutil.rmtree
        calls = []
        def remove(folder):
            calls.append(folder)
            if len(calls) == 1:
                raise error
            real_remove(folder)
        with tempfile.TemporaryDirectory() as parent, \
                patch('server_staging.shutil.rmtree', side_effect=remove), \
                patch('server_staging.time.sleep'):
            with server_staging_directory(prefix='.test-', dir=parent) as folder:
                Path(folder, 'file').write_text('test')
            self.assertFalse(Path(folder).exists())
            self.assertEqual(len(calls), 2)

    def test_cleanup_failure_preserves_original_error(self):
        error = OSError('Directory not empty')
        error.winerror = 145
        with tempfile.TemporaryDirectory() as parent:
            with patch('server_staging.shutil.rmtree', side_effect=error), \
                    patch('server_staging.time.sleep'), \
                    self.assertRaisesRegex(RuntimeError, 'installer failed') as caught:
                with server_staging_directory(prefix='.test-', dir=parent):
                    raise RuntimeError('installer failed')
            self.assertTrue(caught.exception.__notes__)

    def test_cleanup_failure_does_not_turn_success_into_failure(self):
        error = PermissionError('busy')
        status = []
        with tempfile.TemporaryDirectory() as parent:
            with patch('server_staging.shutil.rmtree', side_effect=error), \
                    patch('server_staging.time.sleep'):
                with server_staging_directory(prefix='.test-', dir=parent, status=status.append) as folder:
                    Path(folder, 'file').write_text('test')
            self.assertTrue(Path(folder).exists())
            self.assertEqual(len(status), 1)
