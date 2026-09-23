"""Regression for frameless resize handles being covered by central content."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from main import MainWindow


class ResizeHandleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_handles_stay_above_central_widget(self):
        class Probe(QMainWindow):
            _ResizeHandle = MainWindow._ResizeHandle
            _setup_resize_handles = MainWindow._setup_resize_handles
            _position_resize_handles = MainWindow._position_resize_handles

        window = Probe()
        window.resize(800, 600)
        window._setup_resize_handles()
        window.setCentralWidget(QWidget())
        window.show()
        self.app.processEvents()
        window._position_resize_handles()
        for name, point in {
            'tl': (2, 2), 't': (400, 2), 'tr': (797, 2),
            'l': (2, 300), 'r': (797, 300),
            'bl': (2, 597), 'b': (400, 597), 'br': (797, 597),
        }.items():
            self.assertIs(window.childAt(*point), window._resize_handles[name], name)
        window.close()


if __name__ == '__main__':
    unittest.main()
