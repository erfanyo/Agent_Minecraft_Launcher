from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QLabel

from launcher_app.ui.ui_switch import ToggleSwitch
from settings.center import SettingsCenter

pytestmark = pytest.mark.ui


@pytest.mark.parametrize('answer,accepted,enabled', [
    ('', False, False), ('我知道了', True, False),
    ('我已清楚ai制作/第三方插件的风险', True, True)])
def test_enable_requires_exact_confirmation(qtbot, monkeypatch, answer, accepted, enabled):
    switch = ToggleSwitch(True)
    label = QLabel()
    qtbot.addWidget(switch)
    qtbot.addWidget(label)
    owner = SimpleNamespace(settings={}, third_party_plugins_switch=switch, _autosave_hint=label)
    persist = Mock()
    monkeypatch.setattr('settings.center.update_settings', persist)
    monkeypatch.setattr('settings.center.QInputDialog.getText', lambda *args: (answer, accepted))
    SettingsCenter._toggle_third_party_plugins(owner, True)
    assert switch.isChecked() == enabled
    assert owner.settings.get('third_party_plugins_enabled', False) == enabled
    assert persist.call_count == int(enabled)


def test_disable_does_not_require_confirmation(qtbot, monkeypatch):
    switch = ToggleSwitch(False)
    label = QLabel()
    qtbot.addWidget(switch)
    qtbot.addWidget(label)
    owner = SimpleNamespace(settings={'third_party_plugins_enabled': True},
                            third_party_plugins_switch=switch, _autosave_hint=label)
    monkeypatch.setattr('settings.center.update_settings', lambda fn: fn({}))
    prompt = Mock()
    monkeypatch.setattr('settings.center.QInputDialog.getText', prompt)
    SettingsCenter._toggle_third_party_plugins(owner, False)
    assert owner.settings['third_party_plugins_enabled'] is False
    prompt.assert_not_called()
