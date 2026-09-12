import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtWidgets import QApplication
import ui_background as bg


class BlurTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_blur_is_baked_and_original_unchanged(self):
        source = QPixmap(128, 128)
        source.fill(Qt.GlobalColor.black)
        painter = QPainter(source)
        painter.fillRect(64, 0, 64, 128, QColor('white'))
        painter.end()
        blurred = bg._bake_wallpaper_blur(source).toImage()
        self.assertFalse(blurred.isNull())
        self.assertGreater(blurred.pixelColor(60, 64).red(), 0)
        self.assertLess(blurred.pixelColor(68, 64).red(), 255)
        self.assertEqual(0, source.toImage().pixelColor(60, 64).red())

    def test_strength_compatibility_and_limits(self):
        for value, expected in ((True, 24), (False, 0), (12, 12), (90, 80), (-1, 0), ('bad', 0)):
            self.assertEqual(expected, bg.blur_strength({'ui_wallpaper_blur': value}))

    def test_strength_change_invalidates_only_blurred_variant(self):
        settings = {'ui_wallpaper_source': 'preset', 'ui_wallpaper_blur': 10}
        with patch.object(bg, '_wallpaper_cache_key', None), patch.object(bg, '_wallpaper_original', None), patch.object(bg, '_wallpaper_blurred', None), patch.object(bg, '_bake_wallpaper_blur', wraps=bg._bake_wallpaper_blur) as bake:
            bg.load_wallpaper(settings)
            original = bg._wallpaper_original
            settings['ui_wallpaper_blur'] = 40
            result = bg.load_wallpaper(settings)
            self.assertIs(original, bg._wallpaper_original)
            self.assertEqual(40, bake.call_args.args[1])
            self.assertIs(result, bg.load_wallpaper(settings))
            self.assertEqual(2, bake.call_count)

    def test_cache_and_toggle(self):
        settings = {'ui_wallpaper_source': 'preset', 'ui_wallpaper_preset': 'teal', 'ui_wallpaper_blur': True}
        with patch.object(bg, '_wallpaper_cache_key', None), patch.object(bg, '_wallpaper_original', None), patch.object(bg, '_wallpaper_blurred', None), patch.object(bg, '_bake_wallpaper_blur', wraps=bg._bake_wallpaper_blur) as bake:
            first = bg.load_wallpaper(settings)
            settings['ui_wallpaper_mask'] = 30
            self.assertIs(first, bg.load_wallpaper(settings))
            settings['ui_wallpaper_blur'] = False
            self.assertIsNot(first, bg.load_wallpaper(settings))
            settings['ui_wallpaper_blur'] = True
            self.assertIs(first, bg.load_wallpaper(settings))
            self.assertEqual(1, bake.call_count)
            settings['ui_wallpaper_preset'] = 'grass'
            bg.load_wallpaper(settings)
            self.assertEqual(2, bake.call_count)
            settings['ui_wallpaper_source'] = 'none'
            self.assertIsNone(bg.load_wallpaper(settings))


if __name__ == '__main__':
    unittest.main()
