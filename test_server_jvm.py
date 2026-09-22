# -*- coding: utf-8 -*-
"""服务端运行配置(user_jvm_args.txt)单测。

要点:
- 解析/合并保留注释与未知行(用户和整合包作者都会手工加东西)
- 内存不重复叠加,而是替换
- 校验口径与启动侧一致:放行内存 + 常用 GC 开关,其余在**写入前**就挡住
- 落盘:运行中拒绝、备份不覆盖、原子写
"""
import os
import tempfile
import unittest
from unittest import mock

import server_jvm as sj
import server_jvm_io as sj_io


SAMPLE = """# 服务端 JVM 参数
-Xmx4G
-Xms2G
-XX:+UseG1GC
"""


class ParseTests(unittest.TestCase):
    def test_keeps_comments_and_blanks(self):
        records = sj.parse_records(SAMPLE)
        kinds = [r['kind'] for r in records]
        self.assertEqual(kinds.count('comment'), 1)
        self.assertEqual(kinds.count('arg'), 3)

    def test_serialize_round_trip(self):
        records = sj.parse_records(SAMPLE)
        self.assertEqual(sj.serialize_records(records), SAMPLE)

    def test_all_args_splits_multiple_per_line(self):
        records = sj.parse_records('-Xmx4G -XX:+UseG1GC\n')
        self.assertEqual(sj.all_args(records),
                         ['-Xmx4G', '-XX:+UseG1GC'])

    def test_empty_text(self):
        self.assertEqual(sj.parse_records(''), [])
        self.assertEqual(sj.serialize_records([]), '')


class ReadMemoryTests(unittest.TestCase):
    def test_reads_max_and_min(self):
        memory = sj.read_memory(sj.parse_records(SAMPLE))
        self.assertEqual(memory['max'], '4G')
        self.assertEqual(memory['min'], '2G')

    def test_missing_returns_none(self):
        memory = sj.read_memory(sj.parse_records('-XX:+UseZGC\n'))
        self.assertIsNone(memory['max'])
        self.assertIsNone(memory['min'])

    def test_lowercase_unit_normalised(self):
        memory = sj.read_memory(sj.parse_records('-Xmx4096m\n'))
        self.assertEqual(memory['max'], '4096M')


class ValidateTests(unittest.TestCase):
    def test_accepts_memory_and_gc(self):
        ok, problems = sj.validate(max_gb=4, min_gb=2,
                                   extras=['-XX:+UseG1GC'])
        self.assertTrue(ok, problems)

    def test_rejects_min_greater_than_max(self):
        ok, problems = sj.validate(max_gb=2, min_gb=4)
        self.assertFalse(ok)
        self.assertTrue(any('初始内存' in p for p in problems))

    def test_rejects_non_numeric(self):
        ok, problems = sj.validate(max_gb='lots')
        self.assertFalse(ok)

    def test_rejects_out_of_range(self):
        self.assertFalse(sj.validate(max_gb=0)[0])
        self.assertFalse(sj.validate(max_gb=9999)[0])

    def test_rejects_unsupported_extra(self):
        """与启动侧同口径:不支持的参数必须在写入前挡住。"""
        ok, problems = sj.validate(extras=['-Xmn1G', '-javaagent:evil.jar'])
        self.assertFalse(ok)
        self.assertTrue(any('不会接受' in p for p in problems))

    def test_stack_size_counts_as_supported_extra(self):
        """``-Xss`` 被启动规则放行(正则的 ss 分支),属于可保留的额外参数。"""
        self.assertTrue(sj.is_supported('-Xss1M'))
        self.assertIsNone(sj.read_memory(sj.parse_records('-Xss1M'))['min'],
                          '-Xss 是线程栈,不能当成初始堆内存')

    def test_supported_predicate(self):
        self.assertTrue(sj.is_supported('-Xmx4G'))
        self.assertTrue(sj.is_supported('-Xms512m'))
        self.assertTrue(sj.is_supported('-XX:+UseZGC'))
        self.assertTrue(sj.is_supported('-Xss1M'))
        self.assertFalse(sj.is_supported('-Xmn1G'))
        self.assertFalse(sj.is_supported('-Xlog:gc'))
        self.assertFalse(sj.is_supported('-agentlib:jdwp'))
        self.assertFalse(sj.is_supported('java'))

    def test_matches_server_launch_rule(self):
        """防漂移:同一组参数在两处判定必须一致。"""
        import re
        sample = ['-Xmx4G', '-Xms2G', '-Xss1M', '-Xmn1G', '-Xlog:gc',
                  '-XX:+UseG1GC', '-XX:+UseZGC', '-XX:-UseParallelGC',
                  '-XX:+UseSerialGC', '-XX:+UseConcMarkSweepGC',
                  '-agentlib:jdwp', '-javaagent:x.jar']
        launch_rule = re.compile(
            r'-X(?:ms|mx|ss)\d+[kKmMgG]|-XX:[+-](?:UseG1GC|UseZGC|UseParallelGC|UseSerialGC)')
        for arg in sample:
            self.assertEqual(
                sj.is_supported(arg), launch_rule.fullmatch(arg) is not None,
                f'判定不一致: {arg}')


class MergeTests(unittest.TestCase):
    def test_memory_replaced_not_duplicated(self):
        merged = sj.merge(sj.parse_records(SAMPLE), max_gb=6, min_gb=3)
        args = sj.all_args(merged)
        self.assertEqual([a for a in args if a.startswith('-Xmx')], ['-Xmx6G'])
        self.assertEqual([a for a in args if a.startswith('-Xms')], ['-Xms3G'])

    def test_comments_survive_merge(self):
        merged = sj.merge(sj.parse_records(SAMPLE), max_gb=6)
        text = sj.serialize_records(merged)
        self.assertIn('# 服务端 JVM 参数', text)

    def test_unknown_args_survive_merge(self):
        """用户手工加的额外参数不能被吞掉(否则等于每次保存都重置别人的调优)。"""
        text = '-Xmx4G\n-XX:+UseZGC\n'
        merged = sj.merge(sj.parse_records(text), max_gb=8)
        self.assertIn('-XX:+UseZGC', sj.all_args(merged))

    def test_default_gc_kept_when_no_extras(self):
        merged = sj.merge(sj.parse_records(SAMPLE), max_gb=6)
        self.assertIn('-XX:+UseG1GC', sj.all_args(merged))

    def test_setting_none_removes_memory_flag(self):
        merged = sj.merge(sj.parse_records(SAMPLE), max_gb=None, min_gb=None)
        args = sj.all_args(merged)
        self.assertFalse([a for a in args if a.startswith('-Xm')])

    def test_extras_appended_without_duplicate(self):
        merged = sj.merge(sj.parse_records('-XX:+UseG1GC\n'),
                          extras=['-XX:+UseG1GC', '-XX:+UseZGC'])
        args = sj.all_args(merged)
        self.assertEqual(args.count('-XX:+UseG1GC'), 1)
        self.assertEqual(args.count('-XX:+UseZGC'), 1)

    def test_replace_extras_drops_managed_lines_only(self):
        text = '-XX:+UseG1GC\n-javaagent:keep.jar\n'
        merged = sj.merge(sj.parse_records(text), max_gb=4,
                          extras=['-XX:+UseZGC'], replace_extras=True)
        args = sj.all_args(merged)
        self.assertIn('-XX:+UseZGC', args)
        # 不支持的行不是「可管理参数」,replace 也不该顺手删掉
        self.assertIn('-javaagent:keep.jar', args)


class IoTests(unittest.TestCase):
    def _server(self, temp, text=SAMPLE):
        root = os.path.join(temp, 'server')
        os.makedirs(root, exist_ok=True)
        if text is not None:
            with open(sj_io.jvm_args_path(root), 'w', encoding='utf-8') as f:
                f.write(text)
        return root

    def test_current_settings_reads_memory_and_extras(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp)
            info = sj_io.current_settings(root)
            self.assertEqual((info['max'], info['min']), ('4G', '2G'))
            self.assertIn('-XX:+UseG1GC', info['extras'])

    def test_current_settings_flags_unsupported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp, '-Xmx4G\n-Xmn1G\n')
            info = sj_io.current_settings(root)
            self.assertIn('-Xmn1G', info['unsupported'])

    def test_apply_writes_and_backs_up(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp)
            result = sj_io.apply_update(root, max_gb=8, min_gb=4)
            self.assertTrue(result['ok'], result)
            info = sj_io.current_settings(root)
            self.assertEqual((info['max'], info['min']), ('8G', '4G'))
            backup = sj_io.jvm_args_path(root) + sj_io.BACKUP_SUFFIX
            self.assertTrue(os.path.isfile(backup))
            with open(backup, encoding='utf-8') as f:
                self.assertIn('-Xmx4G', f.read())

    def test_backup_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp)
            sj_io.apply_update(root, max_gb=8)
            sj_io.apply_update(root, max_gb=12)
            with open(sj_io.jvm_args_path(root) + sj_io.BACKUP_SUFFIX,
                      encoding='utf-8') as f:
                self.assertIn('-Xmx4G', f.read())

    def test_running_server_refuses(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp)
            with mock.patch.object(sj_io, 'server_running', return_value=True):
                result = sj_io.apply_update(root, max_gb=8)
            self.assertFalse(result['ok'])
            self.assertIn('正在运行', result['message'])
            self.assertEqual(sj_io.current_settings(root)['max'], '4G')

    def test_running_override(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp)
            with mock.patch.object(sj_io, 'server_running', return_value=True):
                result = sj_io.apply_update(root, max_gb=8, allow_running=True)
            self.assertTrue(result['ok'], result)

    def test_invalid_value_is_not_written(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp)
            result = sj_io.apply_update(root, max_gb='abc')
            self.assertFalse(result['ok'])
            self.assertEqual(sj_io.current_settings(root)['max'], '4G')

    def test_unsupported_extra_is_not_written(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp)
            result = sj_io.apply_update(root, extras=['-javaagent:evil.jar'])
            self.assertFalse(result['ok'])
            self.assertNotIn('javaagent',
                             sj_io.read_text(sj_io.jvm_args_path(root)))

    def test_existing_unsupported_arg_blocks_save_with_explanation(self):
        """文件里本来就有启动器不接受的参数时,保存要明确告知而不是默默放过。"""
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp, '-Xmx4G\n-Xmn1G\n')
            result = sj_io.apply_update(root, max_gb=8)
            self.assertFalse(result['ok'])
            self.assertIn('-Xmn1G', result['message'])

    def test_missing_file_is_created(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._server(temp, text=None)
            self.assertEqual(sj_io.current_settings(root)['max'], None)
            result = sj_io.apply_update(root, max_gb=4)
            self.assertTrue(result['ok'], result)
            self.assertEqual(sj_io.current_settings(root)['max'], '4G')

    def test_parse_gb(self):
        self.assertEqual(sj_io.parse_gb('4G'), 4)
        self.assertEqual(sj_io.parse_gb('2048M'), 2048)
        self.assertIsNone(sj_io.parse_gb(''))
        self.assertIsNone(sj_io.parse_gb('x'))


if __name__ == '__main__':
    unittest.main()
