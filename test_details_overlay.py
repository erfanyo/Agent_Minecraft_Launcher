"""The shared detail tab follows the selected client or server instance."""
import unittest

from PySide6.QtWidgets import QApplication, QStackedWidget, QTabWidget, QWidget

_app = QApplication.instance() or QApplication([])

from i18n import t
from main import MainWindow


class _Content(QWidget):
    def __init__(self):
        super().__init__()
        self.payload = None

    def set_instance(self, instance, _root):
        self.payload = instance

    def set_server(self, server):
        self.payload = server


class _Home:
    _server_mode = False

    def __init__(self):
        self.instance = None
        self.server_center = self

    def current_instance(self):
        return self.instance

    def selected(self):
        return self.server


class _Host:
    _sync_details_tab = MainWindow._sync_details_tab
    _show_instance_details = MainWindow._show_instance_details
    _show_server_details = MainWindow._show_server_details

    def __init__(self):
        self.main_tabs = QTabWidget()
        self.main_tabs.addTab(QWidget(), t("MY_INSTANCES"))
        self.details_stack = QStackedWidget()
        self.details_placeholder = _Content()
        self.details_placeholder.setText = lambda text: setattr(self, "placeholder_text", text)
        self.instance_details = _Content()
        self.server_details = _Content()
        for widget in (self.details_placeholder, self.instance_details, self.server_details):
            self.details_stack.addWidget(widget)
        self._details_tab_idx = self.main_tabs.addTab(self.details_stack, t("INSTANCE_DETAILS"))
        self.home_panel = _Home()

    def close(self):
        self.main_tabs.deleteLater()
        QApplication.processEvents()


class DetailsTabTests(unittest.TestCase):
    def setUp(self):
        self.host = _Host()
        self.addCleanup(self.host.close)

    def test_instance_and_server_share_one_tab(self):
        instance = {"id": "client"}
        server = {"id": "server"}
        self.host._show_instance_details(instance)
        self.assertIs(self.host.main_tabs.currentWidget(), self.host.details_stack)
        self.assertIs(self.host.details_stack.currentWidget(), self.host.instance_details)
        self.assertIs(self.host.instance_details.payload, instance)
        self.host._show_server_details(server)
        self.assertEqual(self.host.main_tabs.count(), 2)
        self.assertIs(self.host.details_stack.currentWidget(), self.host.server_details)
        self.assertIs(self.host.server_details.payload, server)
        self.assertEqual(self.host.main_tabs.tabText(self.host._details_tab_idx), "服务端详情")

    def test_empty_selection_shows_help_in_shared_tab(self):
        self.host._sync_details_tab()
        self.assertIs(self.host.details_stack.currentWidget(), self.host.details_placeholder)
        self.assertIn("实例", self.host.placeholder_text)
        self.host.home_panel._server_mode = True
        self.host.home_panel.server = None
        self.host._sync_details_tab()
        self.assertIs(self.host.details_stack.currentWidget(), self.host.details_placeholder)
        self.assertIn("服务端", self.host.placeholder_text)


if __name__ == "__main__":
    unittest.main()
