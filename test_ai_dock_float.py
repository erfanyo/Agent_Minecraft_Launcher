"""Floating AI dock keeps a usable drag handle and can re-dock."""
import os
import threading
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDockWidget, QMainWindow, QTabWidget, QVBoxLayout, QWidget, QPushButton

from assistant import AIChatDock, AI_DOCK_RETURN_MIME, _DockHeader, _FloatingDockResizeGrip
from main import MainWindow


class FloatingDockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_one_header_handles_tabs_and_floating(self):
        class Probe(QDockWidget):
            _on_floating_changed = AIChatDock._on_floating_changed
            _position_left_resize_grips = AIChatDock._position_left_resize_grips

        main = QMainWindow()
        dock = Probe('AI 助手', main)
        tabs = QTabWidget()
        tabs.addTab(QWidget(), '聊天')
        tabs.addTab(QWidget(), '记录/归档')
        tabs.tabBar().hide()
        dock._dock_header = _DockHeader(dock, tabs)
        dock.setTitleBarWidget(dock._dock_header)
        dock.topLevelChanged.connect(dock._on_floating_changed)
        main.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        main.show()
        dock._dock_header.archive_button.click()
        self.assertEqual(tabs.currentIndex(), 1)
        dock.setFloating(True)
        self.app.processEvents()
        self.assertIsInstance(dock.titleBarWidget(), _DockHeader)
        self.assertFalse(dock.features() & QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.assertIn('双击顶部空白处停靠', dock._dock_header.float_button.toolTip())
        self.assertIn('拖到启动器', dock._dock_header.float_button.toolTip())

        QTest.mouseClick(dock._dock_header.float_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertFalse(dock.isFloating())
        self.assertTrue(dock.features() & QDockWidget.DockWidgetFeature.DockWidgetMovable)
        dock.setFloating(True)
        self.app.processEvents()

        class FailedMove:
            ignored = False
            accepted = False

            def button(self):
                return Qt.MouseButton.LeftButton

            def ignore(self):
                self.ignored = True

            def accept(self):
                self.accepted = True

        class NoSystemMove:
            def startSystemMove(self):
                return False

        original_window_handle = dock.windowHandle
        dock.windowHandle = lambda: NoSystemMove()
        failed_move = FailedMove()
        dock._dock_header.mousePressEvent(failed_move)
        self.assertTrue(failed_move.accepted)
        self.assertFalse(failed_move.ignored)

        class SystemMove:
            called = False

            def startSystemMove(self):
                self.called = True
                return True

        class Press(FailedMove):
            accepted = False

            def accept(self):
                self.accepted = True

        system_move = SystemMove()
        dock.windowHandle = lambda: system_move
        press = Press()
        dock._dock_header.mousePressEvent(press)
        self.assertTrue(system_move.called)
        self.assertTrue(press.accepted)
        self.assertTrue(dock._dock_header._system_move_active)
        dock._dock_header.mouseMoveEvent(press)
        self.assertFalse(press.ignored)
        dock._dock_header.mouseReleaseEvent(press)
        self.assertFalse(dock._dock_header._system_move_active)
        # A second press after dropping the window must start a new move.
        system_move.called = False
        dock._dock_header.mousePressEvent(Press())
        self.assertTrue(system_move.called)
        dock.windowHandle = original_window_handle

        class DoubleClick:
            def button(self):
                return Qt.MouseButton.LeftButton

            def accept(self):
                pass

        dock._dock_header.mouseDoubleClickEvent(DoubleClick())
        self.app.processEvents()
        self.assertFalse(dock.isFloating())
        self.assertIs(dock.titleBarWidget(), dock._dock_header)
        self.assertEqual(dock._dock_header.float_button.toolTip(), '浮出 AI 助手')
        main.close()

    def test_return_drag_docks_without_treating_it_as_modpack(self):
        class Probe(MainWindow):
            _is_ai_dock_return_drag = MainWindow._is_ai_dock_return_drag
            dropEvent = MainWindow.dropEvent

            def __init__(self):
                QMainWindow.__init__(self)
                self.returned = False

            def _expand_ai(self):
                self.returned = True
                self.ai_dock.setFloating(False)

            def closeEvent(self, event):
                QMainWindow.closeEvent(self, event)

        main = Probe()
        dock = QDockWidget('AI', main)
        dock.setWidget(QWidget())
        tabs = QTabWidget()
        tabs.addTab(QWidget(), '聊天')
        dock._dock_header = _DockHeader(dock, tabs)
        dock.setTitleBarWidget(dock._dock_header)
        main.ai_dock = dock
        main.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.setFloating(True)
        self.app.processEvents()

        class Mime:
            def hasFormat(self, value):
                return value == AI_DOCK_RETURN_MIME

        class Drop:
            accepted = False

            def mimeData(self):
                return Mime()

            def source(self):
                return dock._dock_header.float_button

            def setDropAction(self, action):
                self.action = action

            def accept(self):
                self.accepted = True

        event = Drop()
        main.dropEvent(event)
        self.assertTrue(main.returned)
        self.assertTrue(event.accepted)
        self.assertEqual(event.action, Qt.DropAction.MoveAction)
        main.close()

    def test_floating_left_grips_request_the_actual_left_edge(self):
        class Probe(QDockWidget):
            _position_left_resize_grips = AIChatDock._position_left_resize_grips
            _on_floating_changed = AIChatDock._on_floating_changed

        main = QMainWindow()
        dock = Probe('AI', main)
        dock.setWidget(QWidget())
        dock._dock_header = None
        dock._left_resize_grips = (
            _FloatingDockResizeGrip(dock, Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
                                    Qt.CursorShape.SizeFDiagCursor),
            _FloatingDockResizeGrip(dock, Qt.Edge.LeftEdge,
                                    Qt.CursorShape.SizeHorCursor),
            _FloatingDockResizeGrip(dock, Qt.Edge.LeftEdge | Qt.Edge.BottomEdge,
                                    Qt.CursorShape.SizeBDiagCursor),
        )
        dock._other_resize_grips = (
            _FloatingDockResizeGrip(dock, Qt.Edge.RightEdge | Qt.Edge.TopEdge,
                                    Qt.CursorShape.SizeBDiagCursor),
            _FloatingDockResizeGrip(dock, Qt.Edge.RightEdge,
                                    Qt.CursorShape.SizeHorCursor),
            _FloatingDockResizeGrip(dock, Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
                                    Qt.CursorShape.SizeFDiagCursor),
            _FloatingDockResizeGrip(dock, Qt.Edge.BottomEdge,
                                    Qt.CursorShape.SizeVerCursor),
        )
        dock.topLevelChanged.connect(dock._on_floating_changed)
        main.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        main.show()
        self.assertTrue(all(not grip.isVisible() for grip in dock._left_resize_grips))
        dock.setFloating(True)
        self.app.processEvents()
        self.assertTrue(all(grip.isVisible() for grip in dock._left_resize_grips))
        self.assertTrue(all(grip.isVisible() for grip in dock._other_resize_grips))
        self.assertEqual(dock._other_resize_grips[1].width(), 16)
        self.assertEqual(dock._other_resize_grips[1].y(), 30)

        requested = []

        class WindowHandle:
            def startSystemResize(self, edges):
                requested.append(edges)
                return True

        class Press:
            accepted = False

            def button(self):
                return Qt.MouseButton.LeftButton

            def accept(self):
                self.accepted = True

        dock.windowHandle = lambda: WindowHandle()
        for grip in dock._left_resize_grips:
            press = Press()
            grip.mousePressEvent(press)
            self.assertTrue(press.accepted)
        self.assertEqual(requested, [
            Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
            Qt.Edge.LeftEdge,
            Qt.Edge.LeftEdge | Qt.Edge.BottomEdge,
        ])
        dock.setFloating(False)
        self.app.processEvents()
        self.assertTrue(all(not grip.isVisible() for grip in dock._left_resize_grips))
        self.assertTrue(all(not grip.isVisible() for grip in dock._other_resize_grips))
        main.close()

    def test_action_confirmation_is_a_nonmodal_card_and_stop_unblocks_worker(self):
        class Probe(QDockWidget):
            _on_action_confirm_ui = AIChatDock._on_action_confirm_ui
            _stop_agent_run = AIChatDock._stop_agent_run

            def _append_system(self, message):
                self.last_message = message

        dock = Probe()
        container = QWidget()
        QVBoxLayout(container)
        dock.setWidget(container)
        dock.settings = {'ai_response_style': 'plain'}
        dock._agent_cancel = threading.Event()
        dock.show()
        result, finished = [], threading.Event()
        dock._on_action_confirm_ui('list_instances', '查看实例', result, finished)
        self.assertFalse(finished.is_set())
        self.assertIsNotNone(dock._confirm_card)
        self.assertEqual(dock._confirm_card.windowModality(), Qt.WindowModality.NonModal)
        dock._confirm_card.findChildren(QPushButton)[-1].click()
        self.assertTrue(finished.is_set())
        self.assertTrue(dock._agent_cancel.is_set())
        self.assertEqual(result, [(False, False)])
        dock.close()


if __name__ == '__main__':
    unittest.main()
