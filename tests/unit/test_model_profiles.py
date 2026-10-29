import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from launcher_app.ai.model_profiles import api_models, activate_api
from launcher_app.ai.model_cards import ModelCardsPanel, ProviderCard


def settings():
    return {'ai_source': 'cloud', 'ai_strategy': 'cloud_first',
            'ai_cloud_provider': 'custom', 'ai_cloud_model': 'bonsai:27b',
            'ai_model_providers': {
                'deepseek': {'base_url': 'https://api.example.com/v1', 'api_key': 'remote-key',
                             'models': [{'id': 'deepseek-chat'}]},
                'custom': {'name': '本机 Bonsai', 'base_url': 'http://127.0.0.1:8080',
                           'api_key': '', 'models': [{'id': 'other'}, {'id': 'bonsai:27b'}]}}}


def test_all_profiles_are_selectable_with_display_names():
    items = dict(api_models(settings()))
    assert 'cloud:deepseek:deepseek-chat' in items
    assert items['cloud:custom:bonsai:27b'] == '本机 Bonsai · bonsai:27b'


def test_selection_switches_endpoint_and_clears_remote_key():
    s = settings()
    s.update(ai_api_key='remote-key', ai_cloud_api_key='remote-key')
    activate_api(s, 'custom', 'bonsai:27b')
    assert s['ai_base_url'] == s['ai_cloud_base_url'] == 'http://127.0.0.1:8080'
    assert s['ai_api_key'] == s['ai_cloud_api_key'] == ''
    assert s['ai_model'] == 'bonsai:27b'
    assert s['ai_strategy'] == 'cloud_first'


def test_card_autosave_preserves_selected_profile_and_model():
    app = QApplication.instance() or QApplication([])
    panel = ModelCardsPanel(settings())
    data = panel.values()
    assert data['ai_cloud_provider'] == 'custom'
    assert data['ai_model'] == 'bonsai:27b'
    assert data['ai_base_url'] == 'http://127.0.0.1:8080'
    panel.deleteLater()


def test_custom_rename_roundtrip_keeps_identity_and_connection():
    app = QApplication.instance() or QApplication([])
    card = ProviderCard('api', 'custom', settings()['ai_model_providers']['custom'])
    card.display_name.setText('我的本地模型')
    saved = card.collect()
    assert card.title.text() == saved['name'] == '我的本地模型'
    assert card.pid == 'custom'
    assert saved['base_url'] == 'http://127.0.0.1:8080'
    assert saved['models'][1]['id'] == 'bonsai:27b'
    restored = ProviderCard('api', 'custom', saved)
    assert restored.title.text() == '我的本地模型'
    card.deleteLater()
    restored.deleteLater()


def test_autosave_does_not_switch_builtin_back_to_api():
    app = QApplication.instance() or QApplication([])
    s = settings()
    s.update(ai_source='local', ai_strategy='local_first', ai_provider='local_builtin')
    panel = ModelCardsPanel(s)
    data = panel.values()
    assert data['ai_source'] == 'local'
    assert data['ai_strategy'] == 'local_first'
    assert data['ai_provider'] == 'local_builtin'
    panel.deleteLater()
