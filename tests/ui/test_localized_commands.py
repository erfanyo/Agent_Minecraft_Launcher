import copy
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from launcher_app.core import i18n
from launcher_app.ui.instance_manager import InstanceManagerDialog

pytestmark = pytest.mark.ui


@pytest.mark.parametrize('language', ['en', 'ja', 'ar'])
def test_translated_labels_keep_original_command_identity(qtbot, monkeypatch, tmp_path, language):
    for key in ('_current', '_lang_pack_id', '_lang_pack', 'PACK_DIR', '_PACKS'):
        monkeypatch.setattr(i18n, key, copy.deepcopy(getattr(i18n, key)))
    i18n.load_packs_from_dir(str(Path(__file__).resolve().parents[2] / 'languages'))
    i18n.set_language(language)
    view = InstanceManagerDialog()
    qtbot.addWidget(view)
    view.inst_dir = str(tmp_path)
    view.inst_id = 'Preview'
    view._inst_base = '1.20.1'
    panel = view._build_command_tab()
    qtbot.addWidget(panel)
    assert view.cmd_cat_combo.currentData() == '天气/时间'
    assert view.cmd_cat_combo.currentText() == i18n.t('天气/时间')
    first = view.cmd_template_list.item(0)
    expected_name = view.cmd_templates['天气/时间'][0][0]
    assert first.data(Qt.ItemDataRole.UserRole) == expected_name
    assert first.text() == i18n.t(expected_name)
    assert view._cmd_build_command() == 'weather rain'
    # Category lookup must use the unchanged source ID, never translated text.
    view.cmd_cat_combo.setCurrentIndex(1)
    assert view._cmd_current_template() is not None
