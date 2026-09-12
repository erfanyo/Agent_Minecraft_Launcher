import os
import tempfile
import unittest
from unittest.mock import Mock, patch
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication
from wallpaper_picker import WallpaperDropButton
from settings.center import SettingsCenter


class WallpaperPickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_local_single_image_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'photo.png')
            image = QImage(8, 8, QImage.Format.Format_RGB32)
            image.fill(QColor('blue'))
            self.assertTrue(image.save(path))
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(path)])
            self.assertEqual(os.path.normpath(path), os.path.normpath(WallpaperDropButton.local_image(mime)))
            mime.setUrls([QUrl('https://example.com/photo.png')])
            self.assertEqual('', WallpaperDropButton.local_image(mime))
            mime.setUrls([QUrl.fromLocalFile(path), QUrl.fromLocalFile(path)])
            self.assertEqual('', WallpaperDropButton.local_image(mime))

    def test_import_copies_and_autosaves(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'photo.png')
            image = QImage(8, 8, QImage.Format.Format_RGB32)
            image.fill(QColor('blue'))
            image.save(path)
            owner = Mock()
            owner.wallpaper_source_combo.findData.return_value = 2
            with patch('paths.cache_dir', return_value=directory):
                SettingsCenter._import_wallpaper_image(owner, path)
            self.assertTrue(os.path.isfile(path))
            self.assertTrue(os.path.isfile(os.path.join(directory, os.path.basename(owner._wallpaper_user_path))))
            owner._queue_visual_autosave.assert_called_once()


if __name__ == '__main__':
    unittest.main()
