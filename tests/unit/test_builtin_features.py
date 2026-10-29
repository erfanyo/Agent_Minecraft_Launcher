from pathlib import Path
from unittest.mock import patch

from launcher_app.extensions import plugin_manager as pm
from launcher_app.features.registry import FEATURE_IDS, settings_pages


def test_formal_features_ignore_old_plugin_disable_flags_and_do_not_download():
    with patch('launcher_app.features.lan_bridge.download_core') as core, \
         patch('launcher_app.features.lan_bridge.download_terracotta') as terracotta:
        loaded = pm.load_all({'plugins_disabled': list(FEATURE_IDS)}, include_builtin=True)
    core.assert_not_called()
    terracotta.assert_not_called()
    assert not (set(loaded) & set(FEATURE_IDS))
    assert 'lan_bridge__lan_status' in pm.TOOLS
    assert 'lan_bridge__lan_setup' in pm.TOOLS
    assert {p[2] for p in pm.CENTER_PAGES['online']} >= {'陶瓦联机', 'EasyTier 设置'}
    assert {row[0] for row in pm.INSTANCE_SECTIONS} >= {
        'create_schematics', 'hotai_patches', 'tacz_gunpacks', 'tlm_packs', 'ysm_skins'}
    assert {row[0] for row in settings_pages()} == {'browser_assistant', 'lan_bridge'}


def test_builtin_ids_cannot_be_installed_or_discovered_as_plugins(tmp_path):
    (tmp_path / 'lan_bridge.py').write_text('raise RuntimeError("obsolete")')
    (tmp_path / 'other.py').write_text('')
    with patch.object(pm, 'PLUGIN_DIR', str(tmp_path)):
        assert [name for name, _ in pm.discover_plugins()] == ['other']
        assert not pm.save_plugin('lan_bridge', 'invalid')['ok']


def test_default_disabled_plugin_is_not_imported_before_user_enables_it(tmp_path):
    path = tmp_path / 'mcp_server.py'
    path.write_text('PLUGIN_DEFAULT_ENABLED = False\nPLUGIN_API_VERSION = 1\n'
                    'raise RuntimeError("must not execute")\ndef register(api): pass\n')
    with patch.object(pm, 'PLUGIN_DIR', str(tmp_path)), patch.object(pm, '_load_plugin_module') as load:
        result = pm.load_all({})
    assert result == {'mcp_server': False}
    load.assert_not_called()


def test_legacy_network_config_is_reused_without_creating_a_new_copy():
    from launcher_app.features import lan_bridge
    config = {'plugin.lan_bridge.easytier_core': 'existing-core.exe',
              'plugin.lan_bridge.terracotta_binary': 'existing-terracotta.exe'}
    pm.load_all(config, include_builtin=True)
    assert lan_bridge._configured_core == 'existing-core.exe'
    assert lan_bridge._terracotta_path == 'existing-terracotta.exe'


def test_official_catalog_only_contains_mcp():
    import json
    data = json.loads((Path(__file__).resolve().parents[2] / 'plugins.json').read_text(encoding='utf-8'))
    assert [row['name'] for row in data['plugins']] == ['mcp_server']
