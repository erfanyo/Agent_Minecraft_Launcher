# -*- coding: utf-8 -*-
"""服务端玩家名单(白名单/OP/封禁)单测。

关键行为:解析失败**拒绝写**(否则等于把名单删了)、备份不覆盖、
新增条目按文件类型补齐字段、大小写不敏感查找。
"""
import json
import os
import tempfile
import unittest
from unittest import mock

import server_players as sp


class ParseTests(unittest.TestCase):
    def test_parses_array(self):
        entries, error = sp.parse_entries('[{"uuid":"u","name":"Steve"}]')
        self.assertEqual(error, '')
        self.assertEqual(entries[0]['name'], 'Steve')

    def test_empty_file_is_empty_list_not_error(self):
        self.assertEqual(sp.parse_entries(''), ([], ''))
        self.assertEqual(sp.parse_entries('   \n'), ([], ''))

    def test_invalid_json_reports_error_and_no_entries(self):
        entries, error = sp.parse_entries('{not json')
        self.assertIsNone(entries)      # 关键:None 表示不可写
        self.assertTrue(error)

    def test_non_array_reports_error(self):
        entries, error = sp.parse_entries('{"a":1}')
        self.assertIsNone(entries)
        self.assertIn('数组', error)

    def test_non_dict_items_skipped(self):
        entries, error = sp.parse_entries('[1, {"name":"Alex"}, "x"]')
        self.assertEqual(error, '')
        self.assertEqual([e['name'] for e in entries], ['Alex'])

    def test_render_round_trip(self):
        data = [{'uuid': 'u', 'name': 'Steve'}]
        self.assertEqual(sp.parse_entries(sp.render_entries(data))[0], data)


class FindTests(unittest.TestCase):
    def setUp(self):
        self.entries = [{'uuid': '1', 'name': 'Steve'},
                        {'ip': '10.0.0.1', 'reason': 'x'}]

    def test_find_case_insensitive(self):
        self.assertEqual(sp.find_index(self.entries, 'steve'), 0)

    def test_find_ip_entry(self):
        self.assertEqual(sp.find_index(self.entries, '10.0.0.1'), 1)

    def test_missing_returns_none(self):
        self.assertIsNone(sp.find_index(self.entries, 'nobody'))
        self.assertIsNone(sp.find_index(self.entries, ''))


class MutateTests(unittest.TestCase):
    def test_add_whitelist_entry(self):
        out = sp.add_entry([], 'whitelist', name='Steve', uuid='u1')
        self.assertEqual(out, [{'uuid': 'u1', 'name': 'Steve'}])

    def test_add_op_fills_level(self):
        out = sp.add_entry([], 'ops', name='Alex', uuid='u2', level=2)
        self.assertEqual(out[0]['level'], 2)
        self.assertFalse(out[0]['bypassesPlayerLimit'])

    def test_add_banned_player_has_reason_and_created(self):
        out = sp.add_entry([], 'banned-players', name='Griefer', reason='破坏')
        self.assertEqual(out[0]['reason'], '破坏')
        self.assertIn('created', out[0])
        self.assertEqual(out[0]['expires'], 'forever')

    def test_banned_ips_stores_ip_key(self):
        out = sp.add_entry([], 'banned-ips', name='10.0.0.9')
        self.assertEqual(out[0]['ip'], '10.0.0.9')
        self.assertNotIn('name', out[0])

    def test_duplicate_add_is_noop(self):
        first = sp.add_entry([], 'whitelist', name='Steve')
        again = sp.add_entry(first, 'whitelist', name='steve')
        self.assertEqual(len(again), 1)

    def test_empty_name_raises(self):
        with self.assertRaises(ValueError):
            sp.add_entry([], 'whitelist', name='  ')

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            sp.add_entry([], 'whatever', name='x')

    def test_remove(self):
        entries = [{'name': 'A'}, {'name': 'B'}]
        self.assertEqual(sp.remove_entry(entries, 'a'), [{'name': 'B'}])

    def test_remove_missing_is_noop(self):
        entries = [{'name': 'A'}]
        self.assertEqual(sp.remove_entry(entries, 'Z'), entries)

    def test_original_not_mutated(self):
        entries = [{'name': 'A'}]
        sp.add_entry(entries, 'whitelist', name='B')
        sp.remove_entry(entries, 'A')
        self.assertEqual(entries, [{'name': 'A'}])


class IOTests(unittest.TestCase):
    def _server(self, temp, kind='whitelist', text=None):
        root = os.path.join(temp, 'server')
        os.makedirs(root, exist_ok=True)
        if text is not None:
            with open(sp.file_path(root, kind), 'w', encoding='utf-8') as f:
                f.write(text)
        return root

    def test_missing_file_reads_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(sp.read_entries(self._server(temp), 'whitelist'),
                             ([], ''))

    def test_apply_creates_file_with_backup_of_previous(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp, text='[{"uuid":"old","name":"Old"}]')
            entries = [{'uuid': 'new', 'name': 'New'}]
            result = sp.apply_entries(root, 'whitelist', entries)
            self.assertTrue(result['ok'], result)
            saved, _ = sp.read_entries(root, 'whitelist')
            self.assertEqual(saved, entries)
            backup = sp.file_path(root, 'whitelist') + sp.BACKUP_SUFFIX
            self.assertTrue(os.path.isfile(backup))
            with open(backup, encoding='utf-8') as f:
                self.assertIn('Old', f.read())

    def test_corrupt_file_is_never_overwritten(self):
        """核心安全行为:读不出来的名单文件绝不覆盖。"""
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp, text='{broken')
            path = sp.file_path(root, 'whitelist')
            with open(path, encoding='utf-8') as stream:
                before = stream.read()
            result = sp.apply_entries(root, 'whitelist', [{'name': 'X'}])
            self.assertFalse(result['ok'])
            with open(path, encoding='utf-8') as stream:
                after = stream.read()
            self.assertEqual(before, after)

    def test_running_server_refuses(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp, text='[]')
            with mock.patch.object(sp, 'server_running', return_value=True):
                result = sp.apply_entries(root, 'whitelist', [{'name': 'X'}])
            self.assertFalse(result['ok'])
            self.assertIn('正在运行', result['message'])

    def test_running_override_allows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp, text='[]')
            with mock.patch.object(sp, 'server_running', return_value=True):
                result = sp.apply_entries(root, 'whitelist', [{'name': 'X'}],
                                          allow_running=True)
            self.assertTrue(result['ok'], result)

    def test_backup_not_overwritten_on_second_save(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp, text='[{"name":"First"}]')
            sp.apply_entries(root, 'whitelist', [{'name': 'Second'}])
            sp.apply_entries(root, 'whitelist', [{'name': 'Third'}])
            with open(sp.file_path(root, 'whitelist') + sp.BACKUP_SUFFIX,
                      encoding='utf-8') as f:
                self.assertIn('First', f.read())

    def test_all_kinds_have_distinct_files(self):
        paths = {kind: sp.filename_for(kind) for kind in sp.FILES}
        self.assertEqual(len(set(paths.values())), len(paths))
        self.assertEqual(paths['ops'], 'ops.json')
        self.assertEqual(paths['banned-ips'], 'banned-ips.json')


if __name__ == '__main__':
    unittest.main()
