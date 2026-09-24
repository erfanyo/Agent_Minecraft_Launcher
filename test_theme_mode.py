"""Manual appearance must override OS color hints and repaint Qt defaults."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from frameless_titlebar import FramelessTitleBar
from ui_style import apply_global_dark_palette
from ui_tokens import is_dark_mode, set_theme_mode


class ThemeModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        set_theme_mode('system')
        apply_global_dark_palette(cls.app)

    def test_manual_light_and_dark_palette(self):
        set_theme_mode('light')
        apply_global_dark_palette(self.app)
        self.assertFalse(is_dark_mode())
        self.assertGreater(self.app.palette().color(QPalette.ColorRole.Window).lightness(), 200)
        set_theme_mode('dark')
        apply_global_dark_palette(self.app)
        self.assertTrue(is_dark_mode())
        self.assertLess(self.app.palette().color(QPalette.ColorRole.Window).lightness(), 100)

    def test_title_changes_between_modes(self):
        from PySide6.QtWidgets import QWidget
        parent = QWidget()
        title = FramelessTitleBar(parent, 'AMCL')
        set_theme_mode('light')
        title.refresh_theme()
        self.assertIn('#1f2430', title.title_label.styleSheet())
        set_theme_mode('dark')
        title.refresh_theme()
        self.assertIn('#e7ecf5', title.title_label.styleSheet())
        title.close()
        parent.close()


if __name__ == '__main__':
    unittest.main()
