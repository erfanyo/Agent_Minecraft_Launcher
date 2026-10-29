import copy
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QLabel, QPushButton
from launcher_app.core import i18n
from launcher_app.ui.ui_style import refresh_theme
from launcher_app.ui.ui_tokens import set_theme_mode, theme_mode
from settings.center import SettingsCenter

pytestmark = pytest.mark.ui


@pytest.mark.parametrize('theme', ['light', 'dark'])
@pytest.mark.parametrize('page', ['Game', 'Language', 'Appearance', 'System'])
def test_english_settings_preview(qtbot, monkeypatch, request, theme, page):
    for key in ('_current', '_lang_pack_id', '_lang_pack', 'PACK_DIR', '_PACKS'):
        monkeypatch.setattr(i18n, key, copy.deepcopy(getattr(i18n, key)))
    i18n.load_packs_from_dir(str(Path(__file__).resolve().parents[2] / 'languages'))
    i18n.set_language('en')
    old_theme = theme_mode()
    set_theme_mode(theme)
    refresh_theme()
    try:
        with patch.object(SettingsCenter, '_refresh_java_list'), \
             patch('launcher_app.extensions.plugin_manager.discover_plugins_meta', return_value={}):
            center = SettingsCenter({'language': 'en'})
        qtbot.addWidget(center)
        center.resize(1080, 760)
        labels = center.shell.menu.items()
        index = labels.index(page)
        center.shell.stack.setCurrentIndex(index)
        center.show()
        qtbot.wait(30)
        palette = center.palette()
        text_lightness = palette.color(QPalette.ColorRole.WindowText).lightness()
        background_lightness = palette.color(QPalette.ColorRole.Window).lightness()
        assert (text_lightness > background_lightness) == (theme == 'dark')
        if page == 'Game':
            assert any(label.text() == 'Memory allocation' for label in center.findChildren(QLabel))
        if page == 'Language':
            assert sum(center.language_combo.itemData(i) == 'en' for i in range(center.language_combo.count())) == 1
        if page == 'System':
            assert any(button.text() == 'Restore all dismissed notices' for button in center.findChildren(QPushButton))
        folder = Path(request.config.getoption('--ui-artifacts')) / 'english-preview'
        folder.mkdir(parents=True, exist_ok=True)
        assert center.grab().save(str(folder / f'{theme}-{page.lower()}.png'))
    finally:
        set_theme_mode(old_theme)
        refresh_theme()
