import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from folder_instance_import import import_folder


class FolderTests(unittest.TestCase):
    def test_import_keeps_source_and_refuses_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp, 'source', 'versions', 'demo')
            src.mkdir(parents=True)
            (src / 'demo.json').write_text(json.dumps({'id': 'demo', 'mainClass': 'Main'}))
            (src / 'demo.jar').write_bytes(b'client')
            (src / 'mods').mkdir()
            (src / 'mods' / 'keep.jar').write_bytes(b'mod')
            dest = str(Path(temp, 'target'))
            with patch('instance_maintenance.assert_stopped'):
                self.assertEqual(import_folder(str(src), dest), 'demo')
                with self.assertRaises(ValueError):
                    import_folder(str(src), dest)
            self.assertTrue((src / 'mods' / 'keep.jar').exists())
            self.assertEqual(Path(dest, 'versions', 'demo', 'mods', 'keep.jar').read_bytes(), b'mod')

    def test_wrong_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                import_folder(temp, str(Path(temp, 'target')))

    def test_existing_instance_refresh_only(self):
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp, 'versions', 'demo')
            src.mkdir(parents=True)
            (src / 'demo.json').write_text('{}')
            self.assertEqual(import_folder(str(src), temp), 'demo')


if __name__ == '__main__':
    unittest.main()
