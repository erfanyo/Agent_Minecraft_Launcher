# -*- coding: utf-8 -*-
"""「检测到 mod → 提示装插件」机制单测。

重点锁住**不骚扰**这条:拒绝过就不再问、只问一次、没装 mod 不问、
未声明 WATCH_MODS 的插件不参与。
"""
import os
import tempfile
import unittest

import plugin_prompt as pp


class FakePlugin:
    def __init__(self, watch=()):
        if watch:
            self.WATCH_MODS = watch


class WatchedModsTests(unittest.TestCase):
    def test_reads_tuple(self):
        self.assertEqual(pp.watched_mods(FakePlugin(('tacz', 'timeless'))),
                         ('tacz', 'timeless'))

    def test_accepts_single_string(self):
        self.assertEqual(pp.watched_mods(FakePlugin('kubejs')), ('kubejs',))

    def test_missing_attribute_is_empty(self):
        self.assertEqual(pp.watched_mods(FakePlugin()), ())
        self.assertEqual(pp.watched_mods(object()), ())

    def test_blank_entries_ignored(self):
        self.assertEqual(pp.watched_mods(FakePlugin(('', '  ', 'x'))), ('x',))


class InstalledModsTests(unittest.TestCase):
    def _instance(self, game_dir, name, files):
        mods = os.path.join(game_dir, 'versions', name, 'mods')
        os.makedirs(mods, exist_ok=True)
        for file_name in files:
            with open(os.path.join(mods, file_name), 'w', encoding='utf-8') as f:
                f.write('x')

    def test_collects_jar_names_lowercased(self):
        with tempfile.TemporaryDirectory() as temp:
            self._instance(temp, 'pack', ['KubeJS-Forge-2001.jar', 'other.jar.disabled'])
            names = pp.installed_mod_names(temp)
            self.assertIn('kubejs-forge-2001.jar', names)
            self.assertIn('other.jar.disabled', names)

    def test_ignores_underscore_folders(self):
        with tempfile.TemporaryDirectory() as temp:
            self._instance(temp, '_versions', ['hidden.jar'])
            self.assertEqual(pp.installed_mod_names(temp), set())

    def test_missing_dir_is_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(pp.installed_mod_names(temp), set())

    def test_non_mod_files_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            self._instance(temp, 'pack', ['notes.txt', 'config.toml'])
            self.assertEqual(pp.installed_mod_names(temp), set())


class ModPresentTests(unittest.TestCase):
    def test_matches_substring_like_core(self):
        self.assertTrue(pp.mod_present({'kubejs-forge-2001.jar'}, ('kubejs',)))

    def test_any_key_matches(self):
        self.assertTrue(pp.mod_present({'tacz-1.0.jar'}, ('ysm', 'tacz')))

    def test_no_match(self):
        self.assertFalse(pp.mod_present({'other.jar'}, ('kubejs',)))

    def test_empty_inputs(self):
        self.assertFalse(pp.mod_present(set(), ('kubejs',)))
        self.assertFalse(pp.mod_present({'kubejs.jar'}, ()))


class PendingPromptTests(unittest.TestCase):
    CANDIDATES = [('kubejs_tools', 'KubeJS 工具', ('kubejs',)),
                  ('tacz_guns', '枪包管理', ('tacz', 'timeless'))]

    def test_prompts_when_mod_present_and_not_declined(self):
        pending = pp.pending_prompts({}, {'kubejs.jar'}, self.CANDIDATES)
        self.assertEqual([p['id'] for p in pending], ['kubejs_tools'])

    def test_no_prompt_without_the_mod(self):
        self.assertEqual(pp.pending_prompts({}, {'something.jar'},
                                            self.CANDIDATES), [])

    def test_declined_is_never_asked_again(self):
        """核心红线:拒绝过就不再打扰。"""
        settings = {pp.DECLINED_KEY: ['kubejs_tools']}
        pending = pp.pending_prompts(settings, {'kubejs.jar'}, self.CANDIDATES)
        self.assertEqual(pending, [])

    def test_already_seen_is_not_asked_again(self):
        settings = {pp.SEEN_KEY: ['kubejs_tools']}
        self.assertEqual(pp.pending_prompts(settings, {'kubejs.jar'},
                                            self.CANDIDATES), [])

    def test_decline_does_not_block_other_plugins(self):
        settings = {pp.DECLINED_KEY: ['kubejs_tools']}
        pending = pp.pending_prompts(settings, {'kubejs.jar', 'tacz-1.jar'},
                                     self.CANDIDATES)
        self.assertEqual([p['id'] for p in pending], ['tacz_guns'])

    def test_plugin_without_watch_mods_never_prompts(self):
        pending = pp.pending_prompts({}, {'kubejs.jar'},
                                     [('plain', '普通插件', ())])
        self.assertEqual(pending, [])

    def test_corrupt_settings_value_tolerated(self):
        """设置文件被改坏(不是列表)时不能崩。"""
        pending = pp.pending_prompts({pp.DECLINED_KEY: 'kubejs_tools'},
                                     {'kubejs.jar'}, self.CANDIDATES)
        self.assertEqual([p['id'] for p in pending], ['kubejs_tools'])


class RememberTests(unittest.TestCase):
    def test_decline_recorded(self):
        data = pp.remember({}, 'kubejs_tools', declined=True)
        self.assertEqual(data[pp.DECLINED_KEY], ['kubejs_tools'])
        self.assertNotIn(pp.SEEN_KEY, data)

    def test_seen_recorded_when_not_declined(self):
        data = pp.remember({}, 'kubejs_tools', declined=False)
        self.assertEqual(data[pp.SEEN_KEY], ['kubejs_tools'])

    def test_no_duplicate_entries(self):
        first = pp.remember({}, 'a', declined=True)
        again = pp.remember(first, 'a', declined=True)
        self.assertEqual(again[pp.DECLINED_KEY], ['a'])

    def test_does_not_mutate_input(self):
        original = {}
        pp.remember(original, 'a', declined=True)
        self.assertEqual(original, {})

    def test_declined_plugin_no_longer_pending_after_remember(self):
        """闭环:记住拒绝之后,同一下载场景不再提示。"""
        candidates = [('kubejs_tools', 'KubeJS 工具', ('kubejs',))]
        installed = {'kubejs.jar'}
        self.assertEqual(len(pp.pending_prompts({}, installed, candidates)), 1)
        settings = pp.remember({}, 'kubejs_tools', declined=True)
        self.assertEqual(pp.pending_prompts(settings, installed, candidates), [])


class RealPluginDiscoveryTests(unittest.TestCase):
    """接真的插件目录跑一遍:避免「机制写了但没有任何插件接得上」的空转。"""

    def setUp(self):
        import plugin_test_support
        plugin_test_support.ensure_plugin_path()

    def test_kubejs_plugin_is_off_by_default_but_watched(self):
        module = pp._load_meta_module('kubejs_tools')
        self.assertIsNotNone(module, '按文件名加载 kubejs_tools 插件失败')
        self.assertFalse(module.PLUGIN_DEFAULT_ENABLED)
        self.assertIn('kubejs', pp.watched_mods(module))

    def test_missing_candidates_finds_kubejs_tools(self):
        ids = [item[0] for item in pp.missing_candidates({})]
        self.assertIn('kubejs_tools', ids)

    def test_enabling_it_removes_it_from_candidates(self):
        settings = {'plugins_enabled': ['kubejs_tools']}
        ids = [item[0] for item in pp.missing_candidates(settings)]
        self.assertNotIn('kubejs_tools', ids)

    def test_explicitly_disabled_plugin_is_not_a_candidate(self):
        """用户自己关掉的插件不能再被当成「还没装」来问——那就是骚扰。"""
        settings = {'plugins_disabled': ['kubejs_tools']}
        ids = [item[0] for item in pp.missing_candidates(settings)]
        self.assertNotIn('kubejs_tools', ids)

    def test_prompt_fires_for_real_candidate(self):
        candidates = pp.missing_candidates({})
        pending = pp.pending_prompts({}, {'kubejs-forge-2001.jar'}, candidates)
        self.assertIn('kubejs_tools', [item['id'] for item in pending])

    def test_prompt_is_silent_without_the_mod(self):
        candidates = pp.missing_candidates({})
        self.assertEqual(pp.pending_prompts({}, {'sodium.jar'}, candidates), [])


if __name__ == '__main__':
    unittest.main()
