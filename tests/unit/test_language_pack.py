import copy
from collections import Counter
import json
from pathlib import Path

import pytest
from launcher_app.core import i18n
from launcher_app.core.minecraft_language import minecraft_language_for
from tools.language_pack import audit, catalog
from tools.translate_ui_lmstudio import PROTECTED, protect, restore

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def isolated_i18n(monkeypatch):
    monkeypatch.setattr(i18n, '_PACKS', copy.deepcopy(i18n._PACKS))
    for key in ('_current', '_lang_pack_id', '_lang_pack', 'PACK_DIR'):
        monkeypatch.setattr(i18n, key, copy.deepcopy(getattr(i18n, key)))


def test_english_catalog_has_translations_and_preserves_placeholders():
    data = json.loads((ROOT / 'languages/en.json').read_text(encoding='utf-8'))
    result = audit(catalog(), data['pack'])
    assert not result['missing']
    assert not result['placeholder_mismatches']
    assert data['lang'] == 'en'
    for source, target in data['pack'].items():
        assert Counter(PROTECTED.findall(source)) == Counter(PROTECTED.findall(target))


def test_english_overlay_and_auto_use_english_base(isolated_i18n, monkeypatch):
    i18n.load_packs_from_dir(str(ROOT / 'languages'))
    monkeypatch.setattr(i18n, 'detect_system_language', lambda: 'en')
    for selection in ('en', 'auto'):
        i18n.set_language(selection)
        assert i18n.t('内存分配') == 'Memory allocation'
        assert i18n.get_base_language() == 'en'
        assert minecraft_language_for() == 'en_us'
        assert i18n.t('语言包：{name} ({id})').format(name='Example', id='demo') == 'Language pack: Example (demo)'
    i18n.set_language('zh')
    assert i18n.t('内存分配') == '内存分配'


def test_audit_rejects_added_or_removed_placeholders():
    entries = [{'zh': '已保存 {name}', 'en': ''}]
    assert audit(entries, {'已保存 {name}': 'Saved'})['placeholder_mismatches']
    assert audit(entries, {'已保存 {name}': 'Saved {name} {extra}'})['placeholder_mismatches']
    assert not audit(entries, {'已保存 {name}': 'Saved {name}'})['placeholder_mismatches']


@pytest.mark.parametrize('language', ['ja', 'ko', 'fr', 'es', 'ru', 'ar'])
def test_expanded_packs_cover_registered_sources(language, isolated_i18n):
    data = json.loads((ROOT / f'languages/{language}.json').read_text(encoding='utf-8'))
    result = audit(catalog(), data['pack'])
    assert not result['missing']
    assert not result['placeholder_mismatches']
    assert data['lang'] == language
    for source, target in data['pack'].items():
        assert Counter(PROTECTED.findall(source)) == Counter(PROTECTED.findall(target))
    i18n.register_pack(language, data['name'], data['pack'], language)
    i18n.set_language(language)
    assert i18n.get_base_language() == language
    assert i18n.is_rtl() == (language == 'ar')


def test_model_mask_preserves_code_html_and_required_risk_phrase():
    source = '<a href="https://example.com/">{name}</a> 我已清楚ai制作/第三方插件的风险'
    masked, tokens = protect(source)
    assert restore(masked, tokens) == source
    assert 'https://example.com/' not in masked
    assert '我已清楚' not in masked
    with pytest.raises(ValueError):
        restore(masked.replace('__AMCL_0__', ''), tokens)
