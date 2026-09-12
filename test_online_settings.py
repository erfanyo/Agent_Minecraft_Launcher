import unittest
from unittest.mock import patch, Mock
from PySide6.QtWidgets import QApplication, QWidget
from online_center import OnlineCenter


class OnlineSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_loaded_plugin_has_lazy_settings(self):
        builder = Mock(side_effect=QWidget)
        with patch('plugin_manager.CENTER_PAGES', {'online': [('lan_bridge', 'settings', 'EasyTier 设置', builder)]}):
            center = OnlineCenter()
        self.assertIn('EasyTier 设置', center.shell.menu.items())
        builder.assert_not_called()
        center.shell.switch_by_label('EasyTier 设置')
        builder.assert_called_once()
        center.shell.switch_by_label('EasyTier 设置')
        builder.assert_called_once()
        center.deleteLater()

    def test_unloaded_plugin_has_no_settings(self):
        with patch('plugin_manager.CENTER_PAGES', {}):
            center = OnlineCenter()
        self.assertNotIn('EasyTier 设置', center.shell.menu.items())
        center.deleteLater()


if __name__ == '__main__':
    unittest.main()
