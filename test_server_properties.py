# -*- coding: utf-8 -*-
"""server.properties 解析/校验/落盘单测。

纯函数部分不碰磁盘;落盘部分用 TemporaryDirectory,并验证
「运行中拒绝写」「写前备份」「保留注释与未知键」三条关键行为。
"""
import os
import tempfile
import unittest
from unittest import mock

import server_properties as sp
import server_properties_io as sp_io   # 不别名成 io:避免遮蔽标准库 io


SAMPLE = """#Minecraft server properties
#Sat Sep 21 20:00:00 CST 2026
enable-command-block=false
gamemode=survival
level-name=world
motd=A Minecraft Server
online-mode=true
server-port=25565
# custom note kept by the pack author
my-custom-key=keep-me
"""

#: 含中文注释的版本(实际文件是 UTF-8,读取层要能识别)。
SAMPLE_UTF8 = SAMPLE.replace('# custom note kept by the pack author',
                             '# 自定义注释:整合包作者写的')


class ParseTests(unittest.TestCase):
    def test_parses_entries_and_comments(self):
        records = sp.parse(SAMPLE)
        entries = [r for r in records if r['kind'] == 'entry']
        comments = [r for r in records if r['kind'] == 'comment']
        self.assertEqual(len(entries), 7)
        self.assertTrue(comments)          # 注释与空行都被保留

    def test_as_dict_takes_last_duplicate(self):
        """同名键后出现者生效,与 Minecraft 读取行为一致。"""
        records = sp.parse('server-port=1\nserver-port=2\n')
        self.assertEqual(sp.as_dict(records)['server-port'], '2')

    def test_serialize_round_trips_comments_and_unknown_keys(self):
        """核心保证:解析再写回,注释与未知键一字不差。"""
        records = sp.parse(SAMPLE)
        out = sp.serialize(records)
        self.assertIn('#Minecraft server properties', out)
        self.assertIn('# custom note kept by the pack author', out)
        self.assertIn('my-custom-key=keep-me', out)
        self.assertEqual(sp.as_dict(sp.parse(out)), sp.as_dict(records))

    def test_values_with_equals_and_spaces(self):
        records = sp.parse('motd=hello = world\nkey = spaced \n')
        values = sp.as_dict(records)
        self.assertEqual(values['motd'], 'hello = world')
        self.assertEqual(values['key'], 'spaced')

    def test_empty_and_crlf_input(self):
        self.assertEqual(sp.parse(''), [])
        records = sp.parse('a=1\r\nb=2\r\n')
        self.assertEqual(sp.as_dict(records), {'a': '1', 'b': '2'})

    def test_garbage_line_preserved_not_dropped(self):
        records = sp.parse('this line has no equals\n')
        self.assertEqual(records[0]['kind'], 'unknown')
        self.assertIn('no equals', sp.serialize(records))


class SetValuesTests(unittest.TestCase):
    def test_existing_key_updated_in_place(self):
        records = sp.parse(SAMPLE)
        out = sp.set_values(records, {'server-port': 25566})
        self.assertEqual(sp.as_dict(out)['server-port'], '25566')
        # 顺序不变(仍在原来那一行),而不是被挪到末尾
        keys = [r['key'] for r in out if r['kind'] == 'entry']
        self.assertEqual(keys.index('server-port'), 5)

    def test_new_key_appended(self):
        out = sp.set_values(sp.parse('a=1\n'), {'brand-new': 'x'})
        self.assertEqual(sp.as_dict(out)['brand-new'], 'x')

    def test_booleans_stringified_lowercase(self):
        out = sp.set_values(sp.parse(''), {'online-mode': False, 'pvp': True})
        values = sp.as_dict(out)
        self.assertEqual(values['online-mode'], 'false')
        self.assertEqual(values['pvp'], 'true')

    def test_original_list_not_mutated(self):
        records = sp.parse('a=1\n')
        sp.set_values(records, {'a': '2'})
        self.assertEqual(sp.as_dict(records)['a'], '1')


class ValidateTests(unittest.TestCase):
    def test_bool_accepts_common_spellings(self):
        self.assertTrue(sp.validate('online-mode', 'true')[0])
        self.assertTrue(sp.validate('online-mode', 'yes')[0])
        self.assertTrue(sp.validate('online-mode', '1')[0])
        ok, message = sp.validate('online-mode', 'maybe')
        self.assertFalse(ok)
        self.assertIn('true', message)

    def test_int_rejects_text(self):
        self.assertFalse(sp.validate('server-port', 'abc')[0])
        self.assertTrue(sp.validate('server-port', '25565')[0])

    def test_port_range(self):
        self.assertFalse(sp.validate('server-port', '70000')[0])
        self.assertFalse(sp.validate('server-port', '0')[0])

    def test_enum(self):
        self.assertTrue(sp.validate('gamemode', 'creative')[0])
        self.assertFalse(sp.validate('gamemode', 'nope')[0])

    def test_validate_all_reports_every_problem(self):
        problems = sp.validate_all({'server-port': 'x', 'online-mode': 'q'})
        self.assertEqual(len(problems), 2)
        self.assertEqual({key for key, _ in problems},
                         {'server-port', 'online-mode'})

    def test_danger_and_secret_flags(self):
        self.assertTrue(sp.is_dangerous('level-name'))
        self.assertTrue(sp.is_secret('rcon.password'))
        self.assertFalse(sp.is_dangerous('motd'))


class IoTests(unittest.TestCase):
    def _server(self, temp, text=SAMPLE, encoding='latin-1'):
        root = os.path.join(temp, 'server')
        os.makedirs(root, exist_ok=True)
        if text is not None:
            with open(sp_io.properties_path(root), 'w', encoding=encoding) as f:
                f.write(text)
        return root

    def test_plan_update_reports_problems_without_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp)
            plan = sp_io.plan_update(root, {'server-port': 'not-a-number'})
            self.assertFalse(plan['ok'])
            self.assertTrue(plan['problems'])
            # 原文件未被改动
            self.assertEqual(sp_io.read_values(root)['server-port'], '25565')

    def test_apply_writes_and_backs_up(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp)
            result = sp_io.apply_update(root, {'server-port': '25566',
                                               'motd': 'new-server'})
            self.assertTrue(result['ok'], result)
            self.assertEqual(sp_io.read_values(root)['server-port'], '25566')
            backup = sp_io.properties_path(root) + sp_io.BACKUP_SUFFIX
            self.assertTrue(os.path.isfile(backup))
            with open(backup, encoding='latin-1') as f:
                self.assertIn('server-port=25565', f.read())

    def test_backup_not_overwritten_on_second_save(self):
        """第二次保存不能覆盖最早的原始备份。"""
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp)
            sp_io.apply_update(root, {'server-port': '1000'})
            sp_io.apply_update(root, {'server-port': '2000'})
            with open(sp_io.properties_path(root) + sp_io.BACKUP_SUFFIX,
                      encoding='latin-1') as f:
                self.assertIn('server-port=25565', f.read())

    def test_apply_preserves_comments_and_unknown_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp)
            sp_io.apply_update(root, {'motd': 'changed'})
            text, _ = sp_io.read_text(sp_io.properties_path(root))
            self.assertIn('my-custom-key=keep-me', text)
            self.assertIn('# custom note kept by the pack author', text)

    def test_utf8_file_with_chinese_comment_is_detected(self):
        """真实场景:整合包作者用 UTF-8 存了中文注释,读取层要认出来并原样保留。"""
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp, text=SAMPLE_UTF8, encoding='utf-8')
            text, encoding = sp_io.read_text(sp_io.properties_path(root))
            self.assertEqual(encoding, 'utf-8')
            self.assertIn('自定义注释', text)
            sp_io.apply_update(root, {'motd': 'changed'})
            after, _ = sp_io.read_text(sp_io.properties_path(root))
            self.assertIn('自定义注释', after)      # 保存后中文注释没被破坏

    def test_running_server_refuses_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp)
            with mock.patch.object(sp_io, 'server_running', return_value=True):
                result = sp_io.apply_update(root, {'motd': 'nope'})
            self.assertFalse(result['ok'])
            self.assertIn('正在运行', result['message'])
            self.assertNotEqual(sp_io.read_values(root)['motd'], 'nope')

    def test_allow_running_override(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp)
            with mock.patch.object(sp_io, 'server_running', return_value=True):
                result = sp_io.apply_update(root, {'motd': 'forced'},
                                            allow_running=True)
            self.assertTrue(result['ok'], result)

    def test_empty_changes_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp)
            self.assertFalse(sp_io.apply_update(root, {})['ok'])

    def test_missing_file_can_be_created(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp, text=None)
            self.assertEqual(sp_io.read_values(root), {})
            result = sp_io.apply_update(root, {'server-port': '25565'})
            self.assertTrue(result['ok'], result)
            self.assertEqual(sp_io.read_values(root)['server-port'], '25565')

    def test_cjk_value_falls_back_to_utf8(self):
        """中文 motd 无法用 latin-1 编码 → 明确退回 UTF-8 并在返回值里体现。"""
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp)
            plan = sp_io.plan_update(root, {'motd': '中文标语'})
            self.assertEqual(plan['encoding'], 'utf-8')
            result = sp_io.apply_update(root, {'motd': '中文标语'})
            self.assertTrue(result['ok'])
            self.assertIn('UTF-8', result['message'].upper())


if __name__ == '__main__':
    unittest.main()
