import os
import tempfile
import unittest
import zipfile
from plugins.lan_bridge import _select_download_asset, _extract_core


class DownloadTests(unittest.TestCase):
    def test_download_and_checksum_failure(self):
        import io
        import json
        import hashlib
        from unittest.mock import patch
        from plugins.lan_bridge import download_core
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as z:
            z.writestr('easytier-core.exe', b'fake program, never executed')
        payload = buffer.getvalue()
        asset = {'name': 'easytier-windows-x86_64-v2.6.4.zip',
                 'browser_download_url': 'https://github.com/EasyTier/EasyTier/releases/download/v2.6.4/core.zip',
                 'digest': 'sha256:' + hashlib.sha256(payload).hexdigest(), 'size': len(payload)}
        with tempfile.TemporaryDirectory() as folder:
            def request(*args, **kwargs):
                return io.BytesIO(json.dumps({'assets': [asset]}).encode()) if args[0].full_url.endswith('/latest') else io.BytesIO(payload)
            with patch('urllib.request.urlopen', side_effect=request), patch('platform.system', return_value='Windows'), patch('platform.machine', return_value='AMD64'):
                path = download_core(folder)
                self.assertTrue(os.path.isfile(path))
                before = os.listdir(folder)
                asset['digest'] = 'sha256:' + '0' * 64
                with self.assertRaisesRegex(ValueError, 'SHA-256'):
                    download_core(folder)
                self.assertEqual(before, os.listdir(folder))
                self.assertTrue(os.path.isfile(path))

    def test_select_and_require_checksum(self):
        asset = {'name': 'easytier-windows-x86_64-v2.6.4.zip',
                 'browser_download_url': 'https://github.com/EasyTier/EasyTier/releases/download/v2.6.4/core.zip',
                 'digest': 'sha256:' + 'a' * 64}
        self.assertEqual(asset, _select_download_asset({'assets': [asset]}, 'Windows', 'AMD64'))
        with self.assertRaises(ValueError):
            _select_download_asset({'assets': [asset]}, 'Windows', 'unknown')
        asset['digest'] = ''
        with self.assertRaises(ValueError):
            _select_download_asset({'assets': [asset]}, 'Windows', 'AMD64')

    def test_extract_preserves_companion_files(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = os.path.join(folder, 'core.zip')
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('package/easytier-core.exe', b'not executed')
                z.writestr('package/wintun.dll', b'companion')
            core = _extract_core(archive, os.path.join(folder, 'out'), 'easytier-core.exe')
            self.assertTrue(os.path.isfile(core))
            self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(core), 'wintun.dll')))

    def test_reject_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = os.path.join(folder, 'bad.zip')
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('../escape.exe', b'bad')
            with self.assertRaises(ValueError):
                _extract_core(archive, os.path.join(folder, 'out'), 'easytier-core.exe')
            self.assertFalse(os.path.exists(os.path.join(folder, 'escape.exe')))


if __name__ == '__main__':
    unittest.main()
