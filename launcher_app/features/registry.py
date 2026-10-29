"""Shipped features use internal registration, never external plugin discovery.

Legacy IDs stay stable for saved configuration and existing AI tool names.
"""
from importlib import import_module

FEATURE_IDS = ('browser_assistant', 'create_schematics', 'hotai_patches', 'kubejs_tools',
               'lan_bridge', 'tacz_gunpacks', 'tlm_packs', 'ysm_skins')
_settings_pages = []


def settings_pages():
    return list(_settings_pages)


def register_all(settings):
    from launcher_app.extensions import plugin_manager as pm
    _settings_pages.clear()

    class FeatureAPI(pm.PluginAPI):
        def register_settings_page(self, builder):
            _settings_pages.append((self.plugin_id, self.feature_name, builder))

    results = {}
    for identity in FEATURE_IDS:
        module = import_module('launcher_app.features.' + identity)
        api = FeatureAPI(identity, settings)
        api.feature_name = module.FEATURE_NAME
        module.register(api)
        results[identity] = True
    return results
