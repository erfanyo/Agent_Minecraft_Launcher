"""Global scroll styling must cover the viewport and native track."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QScrollArea, QWidget

from ui_background import scroll_surface_qss


class ScrollSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_viewport_and_scrollbar_are_styled(self):
        css = scroll_surface_qss()
        self.assertIn('QScrollArea > QWidget', css)
        self.assertIn('QScrollBar:vertical', css)
        self.assertIn('QScrollBar:horizontal', css)
        self.app.setStyleSheet(css)
        area = QScrollArea()
        area.setWidget(QWidget())
        area.resize(120, 80)
        area.show()
        self.app.processEvents()
        self.assertTrue(area.viewport().isVisible())
        area.close()
        self.app.setStyleSheet('')


if __name__ == '__main__':
    unittest.main()
