"""Floating resource panels must not inherit a black compositor backing."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from resource_center import PopupCard
from ui_style import popup_panel_style, set_style, current_color


class PopupSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_popup_has_opaque_theme_background(self):
        popup = PopupCard()
        popup.resize(200, 120)
        set_style(popup, popup_panel_style)
        popup.show()
        self.app.processEvents()
        rendered = popup.grab().toImage().pixelColor(100, 60)
        expected = QColor(current_color('bg1'))
        self.assertEqual(rendered.rgb(), expected.rgb())
        wallpaper = QPixmap(200, 120)
        wallpaper.fill(QColor('#3070b0'))
        popup.set_shared_view(wallpaper, 0, 0, 0)
        self.app.processEvents()
        self.assertEqual(popup.grab().toImage().pixelColor(100, 60).rgb(),
                         QColor('#3070b0').rgb())
        popup.close()


if __name__ == '__main__':
    unittest.main()
