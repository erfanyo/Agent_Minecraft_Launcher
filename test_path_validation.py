import os
import tempfile
import unittest

from path_validation import assess_game_path


class PathValidationTests(unittest.TestCase):
    def test_empty_path_is_an_error(self):
        self.assertTrue(assess_game_path('').errors)

    def test_chinese_path_is_an_overridable_warning(self):
        result = assess_game_path(os.path.join(os.getcwd(), '中文实例'), {})
        self.assertFalse(result.errors)
        self.assertTrue(any('中文' in item for item in result.warnings))

    def test_network_and_long_paths_are_warned(self):
        result = assess_game_path('\\\\server\\share\\' + 'a' * 130, {})
        self.assertTrue(any('网络' in item for item in result.warnings))
        self.assertTrue(any('很长' in item for item in result.warnings))

    def test_existing_file_is_rejected(self):
        with tempfile.NamedTemporaryFile() as file:
            self.assertTrue(assess_game_path(file.name, {}).errors)


if __name__ == '__main__':
    unittest.main()
