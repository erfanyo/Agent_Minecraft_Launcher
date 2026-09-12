import unittest
from unittest.mock import Mock


class ZhipuTests(unittest.TestCase):
    def test_saved_settings_refresh_dock(self):
        from assistant import AIChatDock
        dock = Mock()
        settings = {'ai_strategy': 'cloud_first', 'ai_cloud_model': 'glm-4.7-flash'}
        AIChatDock.apply_settings(dock, settings)
        self.assertIs(dock.settings, settings)
        for name in ('_rebuild_strategy_menu', '_update_permission_label',
                     'update_vision_ui', 'update_local_status', 'maybe_preload_local'):
            getattr(dock, name).assert_called_once_with()

    def test_keys_are_separate_and_persisted(self):
        from PySide6.QtWidgets import QApplication
        from assistant import AISettingsForm
        app = QApplication.instance() or QApplication([])
        form = AISettingsForm({'ai_cloud_provider': 'deepseek', 'ai_cloud_api_key': 'ds-test'})
        self.assertEqual(form.cloud_api_key.echoMode(), form.cloud_api_key.EchoMode.Password)
        form.cloud_provider.setCurrentIndex(form.cloud_provider.findData('zhipu'))
        self.assertEqual(form.cloud_api_key.text(), '')
        form.cloud_api_key.setText('glm-test')
        form.cloud_provider.setCurrentIndex(form.cloud_provider.findData('deepseek'))
        self.assertEqual(form.cloud_api_key.text(), 'ds-test')
        saved = form.values()
        self.assertEqual(saved['ai_cloud_api_keys']['zhipu'], 'glm-test')
        restored = AISettingsForm(saved)
        restored.cloud_provider.setCurrentIndex(restored.cloud_provider.findData('zhipu'))
        self.assertEqual(restored.cloud_api_key.text(), 'glm-test')
        form.close()
        restored.close()

    def test_preset(self):
        import assistant
        form = Mock()
        form.cloud_provider.currentData.return_value = 'zhipu'
        assistant.AISettingsForm._fill_cloud_defaults(form)
        form.cloud_base_url.setText.assert_called_once_with('https://open.bigmodel.cn/api/paas/v4')
        form.cloud_model.setText.assert_called_once_with('glm-4.7-flash')
        self.assertTrue(any('GLM-4.7-Flash' in label and key == 'zhipu' for label, key in assistant._CLOUD_PROVIDERS))
