"""Plugin discovery should never interrupt the launcher with a modal dialog."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QPushButton

from main import MainWindow


class PluginDiscoveryNoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_discovery_is_non_modal_and_remembers_choice(self):
        class Probe(MainWindow):
            def __init__(self):
                QMainWindow.__init__(self)
                self.settings = {}

            def closeEvent(self, event):
                QMainWindow.closeEvent(self, event)

        window = Probe()
        window.show()
        with patch('plugin_prompt.installed_mod_names', return_value={'kubejs.jar'}), \
             patch('plugin_prompt.missing_candidates', return_value=[('helper', '辅助插件', ('kubejs',))]), \
             patch('main.load_settings', return_value={}), \
             patch('main.save_settings') as saved, \
             patch('main.QMessageBox.question', side_effect=AssertionError('modal dialog opened')):
            window.maybe_prompt_plugin_for_mods()
            notice = window._plugin_notice
            self.assertIsNotNone(notice)
            self.assertTrue(notice.isVisible())
            self.assertTrue(window.isEnabled())
            enable = next(button for button in notice.findChildren(QPushButton)
                          if button.text() == '启用插件')
            enable.click()
            self.assertIsNone(window._plugin_notice)
            self.assertIn('helper', saved.call_args.args[0]['plugins_enabled'])
            self.assertIn('helper', saved.call_args.args[0]['plugin_prompt_seen'])
        window.close()

    def test_multiple_suggestions_appear_one_at_a_time(self):
        class Probe(MainWindow):
            def __init__(self):
                QMainWindow.__init__(self)
                self.settings = {}

            def closeEvent(self, event):
                QMainWindow.closeEvent(self, event)

        window = Probe()
        window.show()
        window._plugin_notice_queue = [
            {'id': 'one', 'name': '第一个', 'mods': ('a',)},
            {'id': 'two', 'name': '第二个', 'mods': ('b',)},
        ]
        with patch('main.load_settings', return_value={}), patch('main.save_settings') as saved:
            window._show_next_plugin_notice()
            first = window._plugin_notice
            later = next(button for button in first.findChildren(QPushButton)
                         if button.text() == '暂不启用')
            later.click()
            self.assertIn('one', saved.call_args.args[0]['plugin_prompt_declined'])
            self.app.processEvents()
            self.assertIsNotNone(window._plugin_notice)
            self.assertIn('第二个', window._plugin_notice.widget().findChild(QLabel).text())
        window.close()


if __name__ == '__main__':
    unittest.main()
