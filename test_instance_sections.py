# -*- coding: utf-8 -*-
"""插件「实例详情分区」注册点单测。

为什么值得单独锁:分区是**插件往实例详情里塞页面**的唯一通道,判错会导致
①装了 mod 却看不到页(用户以为坏了)②没装 mod 却冒出一个空页(红线)。
另外「注册失败要回滚」和「不重名」是插件系统自己的正确性。
"""
import unittest

import plugin_manager as pm
import plugin_prompt as pp


def _api(plugin_id='demo'):
    """直接构造真 PluginAPI(注册点只依赖 plugin_id)。"""
    return pm.build_api(plugin_id)


class RegisterValidationTests(unittest.TestCase):
    def setUp(self):
        pm.INSTANCE_SECTIONS.clear()

    def tearDown(self):
        pm.INSTANCE_SECTIONS.clear()

    def test_registers_and_reads_back(self):
        api = _api()
        api.register_instance_section('示例', lambda ctx: None, watch_mods=('demo',))
        self.assertEqual(len(pm.INSTANCE_SECTIONS), 1)
        plugin_id, label, mods, _build = pm.INSTANCE_SECTIONS[0]
        self.assertEqual((plugin_id, label, mods), ('demo', '示例', ('demo',)))

    def test_single_string_watch_mods_normalized(self):
        api = _api()
        api.register_instance_section('示例', lambda ctx: None, watch_mods='kubejs')
        self.assertEqual(pm.INSTANCE_SECTIONS[0][2], ('kubejs',))

    def test_blank_and_duplicate_keys_dropped(self):
        api = _api()
        api.register_instance_section('示例', lambda ctx: None,
                                      watch_mods=('', '  ', 'ok'))
        self.assertEqual(pm.INSTANCE_SECTIONS[0][2], ('ok',))

    def test_no_watch_mods_means_always(self):
        api = _api()
        api.register_instance_section('示例', lambda ctx: None)
        self.assertEqual(pm.INSTANCE_SECTIONS[0][2], ())

    def test_empty_label_rejected(self):
        api = _api()
        with self.assertRaises(ValueError):
            api.register_instance_section('   ', lambda ctx: None)

    def test_non_callable_rejected(self):
        api = _api()
        with self.assertRaises(ValueError):
            api.register_instance_section('示例', 'not-callable')

    def test_duplicate_label_rejected(self):
        api = _api()
        api.register_instance_section('示例', lambda ctx: None)
        with self.assertRaises(ValueError):
            _api('other').register_instance_section('示例', lambda ctx: None)


class SectionsForTests(unittest.TestCase):
    def setUp(self):
        pm.INSTANCE_SECTIONS.clear()

    def tearDown(self):
        pm.INSTANCE_SECTIONS.clear()

    def test_gating_by_mod(self):
        api = _api()
        api.register_instance_section('皮肤', lambda ctx: 'skin', watch_mods=('ysm',))
        api.register_instance_section('枪包', lambda ctx: 'gun', watch_mods=('tacz',))
        api.register_instance_section('总是', lambda ctx: 'always')

        labels = [row[0] for row in pm.instance_sections_for(lambda *k: False)]
        self.assertEqual(labels, ['总是'])
        labels = [row[0] for row in pm.instance_sections_for(lambda *k: 'ysm' in k)]
        self.assertEqual(labels, ['皮肤', '总是'])

    def test_predicate_receives_all_keys(self):
        api = _api()
        api.register_instance_section('枪包', lambda ctx: None,
                                      watch_mods=('tacz', 'timeless'))
        seen = []

        def has_mod(*keys):
            seen.append(keys)
            return True

        pm.instance_sections_for(has_mod)
        self.assertEqual(seen, [('tacz', 'timeless')])

    def test_registration_order_preserved(self):
        api = _api()
        for name in ('一', '二', '三'):
            api.register_instance_section(name, lambda ctx: None)
        labels = [row[0] for row in pm.instance_sections_for(lambda *k: True)]
        self.assertEqual(labels, ['一', '二', '三'])



class ContextTests(unittest.TestCase):
    def test_defaults_are_safe(self):
        ctx = pm.InstanceSectionContext('inst', 'dir', 'game')
        self.assertEqual(ctx.instance_id, 'inst')
        self.assertEqual(ctx.instance_dir, 'dir')
        self.assertEqual(ctx.game_dir, 'game')
        self.assertFalse(ctx.has_mod('anything'))
        ctx.open_dir('x')      # 没给回调也不该炸
        ctx.status('hi')

    def test_callbacks_wired(self):
        opened, said = [], []
        ctx = pm.InstanceSectionContext('inst', 'dir', 'game',
                                        has_mod=lambda *keys: keys == ('ysm',),
                                        open_dir=opened.append,
                                        status=said.append)
        self.assertTrue(ctx.has_mod('ysm'))
        self.assertFalse(ctx.has_mod('tacz'))
        ctx.open_dir('/tmp')
        ctx.status('好了')
        self.assertEqual(opened, ['/tmp'])
        self.assertEqual(said, ['好了'])


class LoadAllResetTests(unittest.TestCase):
    def test_load_all_clears_previous_sections(self):
        """重扫插件时必须清干净:否则禁用插件后它的分区还挂在菜单里。"""
        pm.INSTANCE_SECTIONS.clear()
        pm.INSTANCE_SECTIONS.append(('ghost', '幽灵页', (), lambda ctx: None))
        pm.load_all({})
        self.assertEqual([row[0] for row in pm.INSTANCE_SECTIONS if row[0] == 'ghost'], [])


class RealPluginTests(unittest.TestCase):
    """接真的 plugins/ 跑一遍:插件声明与分区是否对得上。"""

    def setUp(self):
        import plugin_test_support
        plugin_test_support.ensure_plugin_path()
        self.ids = ['ysm_skins', 'tacz_gunpacks', 'create_schematics',
                    'tlm_packs', 'hotai_patches']

    def test_all_pack_plugins_are_off_by_default_and_watched(self):
        for plugin_id in self.ids:
            module = pp._load_meta_module(plugin_id)
            self.assertIsNotNone(module, f'{plugin_id} 加载失败')
            self.assertFalse(module.PLUGIN_DEFAULT_ENABLED,
                             f'{plugin_id} 应该是默认关闭(靠检测到 mod 再问)')
            self.assertTrue(module.WATCH_MODS, f'{plugin_id} 没声明 WATCH_MODS')

    def test_sections_appear_after_loading_with_real_mods(self):
        what = pm.load_all({'plugins_enabled': self.ids})
        for plugin_id in self.ids:
            self.assertTrue(what.get(plugin_id), f'{plugin_id} 没装载成功')
        # 同时装齐全部 mod 时,五个分区都该在
        labels = [row[0] for row in pm.instance_sections_for(lambda *k: True)]
        for want in ('皮肤(YSM)', '枪包(TACZ)', '投影原理图', '女仆模型包', 'Hotai 补丁'):
            self.assertIn(want, labels, f'{want} 分区没注册上')
        # 一个 mod 都没装时,一个 mod 专属分区都不该出现
        labels = [row[0] for row in pm.instance_sections_for(lambda *k: False)]
        self.assertEqual(labels, [])

    def test_real_gating_matches_declared_mods(self):
        pm.load_all({'plugins_enabled': self.ids})
        labels = [row[0] for row in pm.instance_sections_for(lambda *k: 'create' in k)]
        self.assertIn('投影原理图', labels)
        self.assertNotIn('皮肤(YSM)', labels)

    def test_disabled_plugin_contributes_nothing(self):
        pm.load_all({})            # 什么都不启用 = 默认关闭的插件都不装
        labels = [row[0] for row in pm.instance_sections_for(lambda *k: True)]
        self.assertEqual(labels, [])


class FakeHost:
    """假实例详情宿主:只有 _plugin_instance_sections 真正用到的那几个属性。"""

    def __init__(self, mods=(), base='/game', inst='pack'):
        self._mods = [f'{m}.jar' for m in mods]
        self.inst_id = inst
        self.inst_dir = f'{base}/versions/{inst}'
        self.game_dir = base
        self.opened = []
        self.messages = []

    def _has_mod(self, *keys):
        low = ' '.join(name.lower() for name in self._mods)
        return any(str(k).lower() in low for k in keys)

    def _open_dir(self, path):
        self.opened.append(path)

    def status_msg(self, text):
        self.messages.append(text)


class InstanceManagerWiringTests(unittest.TestCase):
    """实例详情到底有没有把插件的分区挂到左菜单上(这是最容易接漏的一环)。"""

    def setUp(self):
        import instance_manager as im
        self.im = im
        self.ids = ['ysm_skins', 'tacz_gunpacks', 'create_schematics',
                    'tlm_packs', 'hotai_patches']
        pm.load_all({'plugins_enabled': self.ids})

    def test_sections_are_listed_in_order(self):
        host = FakeHost(mods=['ysm', 'tacz', 'create', 'hotai'])
        rows = self.im._plugin_instance_sections(host)
        labels = [label for label, _fn, _pid in rows]
        self.assertEqual(labels, ['投影原理图', 'Hotai 补丁', '枪包(TACZ)', '皮肤(YSM)'])

    def test_no_section_when_no_mod_installed(self):
        host = FakeHost(mods=['sodium'])
        self.assertEqual(self.im._plugin_instance_sections(host), [])

    def test_build_fn_receives_context_with_instance_paths(self):
        host = FakeHost(mods=['hotai'])
        _label, build_fn, _pid = self.im._plugin_instance_sections(host)[0]
        ctx = self.im._instance_section_ctx(host)
        self.assertEqual(ctx.instance_id, 'pack')
        self.assertEqual(ctx.instance_dir, host.inst_dir)
        self.assertEqual(ctx.game_dir, host.game_dir)
        self.assertTrue(ctx.has_mod('hotai'))
        ctx.open_dir('/somewhere')
        ctx.status('好')
        self.assertEqual(host.opened, ['/somewhere'])
        self.assertEqual(host.messages, ['好'])
        self.assertTrue(callable(build_fn))

    def test_missing_plugin_system_degrades_quietly(self):
        """插件系统没起来时,实例详情必须照常可用(不能抛异常)。"""
        host = FakeHost(mods=['ysm'])
        original = pm.INSTANCE_SECTIONS
        try:
            pm.INSTANCE_SECTIONS = None       # 模拟异常状态
            self.assertEqual(self.im._plugin_instance_sections(host), [])
        finally:
            pm.INSTANCE_SECTIONS = original


if __name__ == '__main__':
    unittest.main()
