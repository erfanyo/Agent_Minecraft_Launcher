import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QLabel

from settings_center import SettingsCenter


class SettingsLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch.object(SettingsCenter, '_refresh_java_list'), \
             patch('plugin_manager.discover_plugins_meta', return_value={}):
            self.center = SettingsCenter({})
        self.addCleanup(self.center.close)

    def test_language_and_personalization_are_separate_pages(self):
        labels = self.center.shell.menu.items()
        self.assertIn('语言', labels)
        self.assertIn('个性化', labels)
        self.assertNotIn('界面', labels)
        language_page = self.center.shell.stack.widget(labels.index('语言'))
        personalization_page = self.center.shell.stack.widget(labels.index('个性化'))
        self.assertTrue(language_page.isAncestorOf(self.center.language_combo))
        self.assertTrue(language_page.isAncestorOf(self.center.sync_minecraft_language_check))
        self.assertTrue(personalization_page.isAncestorOf(self.center.ui_mode_combo))
        self.assertFalse(personalization_page.isAncestorOf(self.center.language_combo))

    def test_software_info_credits_easytier(self):
        labels = self.center.shell.menu.items()
        self.assertIn('软件信息', labels)
        page = self.center.shell.stack.widget(labels.index('软件信息'))
        text = '\n'.join(label.text() for label in page.findChildren(QLabel))
        self.assertIn('鸣谢', text)
        self.assertIn('EasyTier', text)
        self.assertIn('LGPL-3.0', text)
        self.assertIn('github.com/EasyTier/EasyTier', text)


if __name__ == '__main__':
    unittest.main()
