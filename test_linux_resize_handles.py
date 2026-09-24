"""Regression for frameless resize handles being covered by central content."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QDockWidget, QMainWindow, QWidget
from PySide6.QtCore import QPoint, Qt
from unittest.mock import patch

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
            'l': (8, 300), 'r': (791, 300),
            'bl': (15, 585), 'b': (400, 591), 'br': (785, 585),
        }.items():
            self.assertIs(window.childAt(*point), window._resize_handles[name], name)
        # The close button's clickable body is no longer covered by the
        # top-right diagonal resize target.
        self.assertIsNot(window.childAt(785, 20), window._resize_handles['tr'])
        self.assertIsNot(window.childAt(795, 20), window._resize_handles['r'])
        window.close()

    def test_linux_window_mask_rounds_corners(self):
        class Probe(MainWindow):
            def __init__(self):
                QMainWindow.__init__(self)

            def closeEvent(self, event):
                QMainWindow.closeEvent(self, event)

        window = Probe()
        window.resize(800, 600)
        with patch('main.sys.platform', 'linux'):
            window._update_window_shape()
        self.assertFalse(window.mask().contains(QPoint(0, 0)))
        self.assertTrue(window.mask().contains(QPoint(12, 12)))
        window.close()

    def test_linux_rejected_system_resize_does_not_move_left_edge_manually(self):
        from PySide6.QtCore import Qt

        class ResizeWindow(QMainWindow):
            def windowHandle(self):
                return self

            def startSystemResize(self, edge):
                return False

        class Press:
            def button(self):
                return Qt.MouseButton.LeftButton

            def accept(self):
                pass

        window = ResizeWindow()
        handle = MainWindow._ResizeHandle(Qt.Edge.LeftEdge, window)
        with patch('main.sys.platform', 'linux'):
            handle.mousePressEvent(Press())
        self.assertIsNone(handle._drag_origin)
        self.assertIsNone(handle._geo_origin)
        window.close()

    def test_floating_dock_refreshes_central_mask_after_it_grows(self):
        class Probe(MainWindow):
            eventFilter = MainWindow.eventFilter
            _refresh_central_geometry = MainWindow._refresh_central_geometry
            _update_window_shape = MainWindow._update_window_shape
            _mask_outer_children = MainWindow._mask_outer_children
            _place_download_ball = MainWindow._place_download_ball

            def __init__(self):
                QMainWindow.__init__(self)

            def closeEvent(self, event):
                QMainWindow.closeEvent(self, event)

        window = Probe()
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        window.resize(800, 600)
        central = QWidget()
        window.setCentralWidget(central)
        window._background = central
        central.installEventFilter(window)
        dock = QDockWidget('AI', window)
        dock.setWidget(QWidget())
        dock.setMinimumWidth(250)
        window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        window.ai_dock = dock
        dock.installEventFilter(window)
        window.show()
        self.app.processEvents()
        with patch('main.sys.platform', 'linux'):
            window._update_window_shape()
            old_width = central.width()
            dock.setFloating(True)
            self.app.processEvents()
            self.app.processEvents()
            self.assertGreater(central.width(), old_width)
            self.assertTrue(central.mask().contains(QPoint(central.width() - 30, 100)))
        window.close()

    def test_resized_dock_mask_covers_its_new_width(self):
        class Probe(MainWindow):
            eventFilter = MainWindow.eventFilter
            _refresh_central_geometry = MainWindow._refresh_central_geometry
            _update_window_shape = MainWindow._update_window_shape
            _mask_outer_children = MainWindow._mask_outer_children
            _place_download_ball = MainWindow._place_download_ball

            def __init__(self):
                QMainWindow.__init__(self)

            def closeEvent(self, event):
                QMainWindow.closeEvent(self, event)

        window = Probe()
        window.resize(1000, 600)
        central = QWidget()
        window.setCentralWidget(central)
        window._background = central
        central.installEventFilter(window)
        dock = QDockWidget('AI', window)
        dock.setWidget(QWidget())
        window.ai_dock = dock
        window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.installEventFilter(window)
        window.show()
        self.app.processEvents()
        with patch('main.sys.platform', 'linux'):
            window._update_window_shape()
            old_width = dock.width()
            window.resizeDocks([dock], [old_width + 150], Qt.Orientation.Horizontal)
            self.app.processEvents()
            self.app.processEvents()
            self.assertGreater(dock.width(), old_width)
            self.assertTrue(dock.mask().contains(QPoint(dock.width() - 30, 100)))
        window.close()

    def test_linux_root_paints_opaque_dock_gaps(self):
        class Probe(MainWindow):
            def __init__(self):
                QMainWindow.__init__(self)

            def closeEvent(self, event):
                QMainWindow.closeEvent(self, event)

        window = Probe()
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        window.resize(100, 100)
        with patch('main.sys.platform', 'linux'):
            image = window.grab().toImage()
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(image.pixelColor(50, 10).alpha(), 255)
        window.close()

    def test_linux_central_background_does_not_square_outer_corner(self):
        class Probe(MainWindow):
            def __init__(self):
                QMainWindow.__init__(self)

            def closeEvent(self, event):
                QMainWindow.closeEvent(self, event)

        window = Probe()
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        child = QWidget()
        child.setAutoFillBackground(True)
        window.setCentralWidget(child)
        window.resize(100, 100)
        window.show()
        with patch('main.sys.platform', 'linux'):
            window._update_window_shape()
        self.assertFalse(child.mask().contains(QPoint(0, 0)))
        self.assertTrue(child.mask().contains(QPoint(50, 50)))
        window.close()

    def test_windows_rounds_visible_pixels_and_child_background(self):
        class Probe(MainWindow):
            def __init__(self):
                QMainWindow.__init__(self)

            def closeEvent(self, event):
                QMainWindow.closeEvent(self, event)

        window = Probe()
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        child = QWidget()
        child.setAutoFillBackground(True)
        window.setCentralWidget(child)
        window.resize(100, 100)
        window.show()
        with patch('main.sys.platform', 'win32'):
            window._update_window_shape()
            image = window.grab().toImage()
        self.assertFalse(child.mask().contains(QPoint(0, 0)))
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(image.pixelColor(50, 50).alpha(), 255)
        window.close()


if __name__ == '__main__':
    unittest.main()
