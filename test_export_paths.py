from pathlib import Path
import tempfile
import unittest

from export_paths import compose_zip_destination


class ExportPathTests(unittest.TestCase):
    def test_directory_and_filename_are_composed_separately(self):
        with tempfile.TemporaryDirectory() as temp:
            result = compose_zip_destination(temp, 'candidate')
            self.assertEqual(Path(result), Path(temp).absolute() / 'candidate.zip')
            self.assertEqual(compose_zip_destination(temp, 'ready.ZIP'),
                             str(Path(temp).absolute() / 'ready.ZIP'))

    def test_filename_cannot_escape_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            for name in ('../outside', 'sub/file', 'bad:name', 'trailing. '):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    compose_zip_destination(temp, name)


if __name__ == '__main__':
    unittest.main()
