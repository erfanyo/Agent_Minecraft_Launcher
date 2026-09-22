# -*- coding: utf-8 -*-
"""KubeJS 报错定位单测。

用**真实日志形态**做样例(取自本项目服务端的 logs/kubejs/server.log):
    [18:18:15] [ERROR] ! business/counter.js#501: Error in 'BlockEvents.rightClicked':
    TypeError: Cannot find function getIngredients in object ...
"""
import os
import tempfile
import unittest

import kubejs_errors as ke


REAL_LOG = """[18:17:38] [INIT] KubeJS 2001.6.5-build.26; MC 2001 forge
[18:17:39] [INFO] Added 868 recipes, removed 82 recipes
[18:18:15] [ERROR] ! business/counter.js#501: Error in 'BlockEvents.rightClicked':
TypeError: Cannot find function getIngredients in object com.github.ysbbbbbb.kaleidoscopetavern.blockentity.mixology.SignatureCocktailBlockEntity@42b69a24.
[18:18:16] [ERROR] ! business/counter.js#501: Error in 'BlockEvents.rightClicked':
TypeError: Cannot find function getIngredients in object com.github.ysbbbbbb.kaleidoscopetavern.blockentity.mixology.SignatureCocktailBlockEntity@42b69a24.
[18:18:27] [ERROR] ! startup_scripts/wine.js#12: Error in 'ServerEvents.loaded':
ReferenceError: someThing is not defined
"""


#: 更常见的形态:Forge 服务端日志(latest.log / .amcl-runtime 日志)。
#: 注意与上面精简日志的三处差别:多一个 [Server thread/ERROR] 段、有
#: "[KubeJS Server/]: " 前缀、异常类型**在同一行**后半段。
FORGE_LOG = """[18:17:38] [Server thread/INFO] [KubeJS Server/]: Loaded script server_scripts:business/counter.js in 0.002 s
[18:18:15] [Server thread/ERROR] [KubeJS Server/]: business/counter.js#501: Error in 'BlockEvents.rightClicked': TypeError: Cannot find function getIngredients in object com.github.ysbbbbbb.kaleidoscopetavern.blockentity.mixology.SignatureCocktailBlockEntity@42b69a24.
[18:18:16] [Server thread/ERROR] [KubeJS Server/]: business/counter.js#501: Error in 'BlockEvents.rightClicked': TypeError: Cannot find function getIngredients in object com.github.ysbbbbbb.
[18:19:00] [Server thread/WARN] [KubeJS Server/]: startup_scripts/wine.js#12: Error in 'ServerEvents.loaded': ReferenceError: someThing is not defined
"""


class ForgeFormatTests(unittest.TestCase):
    """Forge 形态日志(实测日志里最常见的一种)。"""

    def test_parses_forge_lines(self):
        errors = ke.parse_errors(FORGE_LOG)
        self.assertEqual(len(errors), 2)          # counter.js#501 去重 + wine.js
        first = errors[0]
        self.assertEqual(first['relpath'], 'business/counter.js')
        self.assertEqual(first['line'], 501)

    def test_inline_exception_is_extracted(self):
        """异常类型在同一行后半段,必须能拆出来(否则提示会给错)。"""
        errors = ke.parse_errors(FORGE_LOG)
        self.assertEqual(errors[0]['kind'], 'TypeError')
        self.assertIn('getIngredients', errors[0]['message'])

    def test_info_lines_ignored(self):
        errors = ke.parse_errors(FORGE_LOG)
        self.assertFalse([e for e in errors if 'Loaded script' in e['message']])

    def test_hint_still_fires_for_forge_format(self):
        """两种格式下提示都要命中(本项目真实教训:缺补丁而非脚本写错)。"""
        errors = ke.parse_errors(FORGE_LOG)
        self.assertTrue(any('补丁' in h for h in ke.hints_for(errors[0])))

    def test_warn_level_counts_too(self):
        errors = ke.parse_errors(FORGE_LOG)
        self.assertIn('wine.js', errors[1]['relpath'])


class ParseTests(unittest.TestCase):
    def test_extracts_path_line_and_exception(self):
        errors = ke.parse_errors(REAL_LOG)
        self.assertGreaterEqual(len(errors), 2)
        first = errors[0]
        self.assertEqual(first['relpath'], 'business/counter.js')
        self.assertEqual(first['line'], 501)
        self.assertEqual(first['kind'], 'TypeError')
        self.assertIn('getIngredients', first['message'])

    def test_deduplicates_repeated_flood(self):
        """同一文件同一行刷屏时只留一条。"""
        errors = ke.parse_errors(REAL_LOG)
        counter = [e for e in errors if e['relpath'] == 'business/counter.js']
        self.assertEqual(len(counter), 1)

    def test_ignores_info_lines(self):
        errors = ke.parse_errors(REAL_LOG)
        self.assertFalse([e for e in errors if 'INIT' in e['relpath']])

    def test_second_file_is_found(self):
        errors = ke.parse_errors(REAL_LOG)
        paths = {e['relpath'] for e in errors}
        self.assertIn('startup_scripts/wine.js', paths)

    def test_path_with_subdirectory(self):
        text = ("[10:00:00] [ERROR] ! business/mail_station.js#7: Error in 'x':\n"
                "TypeError: boom\n")
        errors = ke.parse_errors(text)
        self.assertEqual(errors[0]['relpath'], 'business/mail_station.js')

    def test_no_errors(self):
        self.assertEqual(ke.parse_errors('[18:00:00] [INFO] all good'), [])
        self.assertEqual(ke.parse_errors(''), [])

    def test_message_falls_back_to_title(self):
        text = "[10:00:00] [ERROR] ! a.js#3: Error in 'X':\n(no exception line)\n"
        errors = ke.parse_errors(text)
        self.assertTrue(errors[0]['message'])


class ResolveTests(unittest.TestCase):
    def _tree(self, temp):
        root = os.path.join(temp, 'kubejs')
        os.makedirs(os.path.join(root, 'server_scripts', 'business'))
        os.makedirs(os.path.join(root, 'startup_scripts'))
        for relative in ('server_scripts/business/counter.js',
                         'startup_scripts/wine.js'):
            with open(os.path.join(root, *relative.split('/')), 'w',
                      encoding='utf-8') as f:
                f.write('// x\n')
        return root

    def test_resolves_bare_relative_path(self):
        """日志里的路径不带 server_scripts 前缀,要能猜出来。"""
        with tempfile.TemporaryDirectory() as temp:
            root = self._tree(temp)
            found = ke.resolve_path(root, 'business/counter.js')
            self.assertIsNotNone(found)
            self.assertTrue(found.endswith(os.path.join('server_scripts', 'business',
                                                        'counter.js')))

    def test_resolves_startup_script(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._tree(temp)
            found = ke.resolve_path(root, 'wine.js')
            self.assertTrue(found.endswith(os.path.join('startup_scripts', 'wine.js')))

    def test_resolves_path_that_already_has_subdir(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._tree(temp)
            self.assertTrue(ke.resolve_path(root, 'startup_scripts/wine.js'))

    def test_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._tree(temp)
            self.assertIsNone(ke.resolve_path(root, 'nope/missing.js'))
            self.assertIsNone(ke.resolve_path('', 'a.js'))


class ExcerptTests(unittest.TestCase):
    def _script(self, temp, lines=600):
        path = os.path.join(temp, 'counter.js')
        with open(path, 'w', encoding='utf-8') as f:
            for number in range(1, lines + 1):
                f.write(f'let v{number} = {number};\n')
        return path

    def test_returns_context_around_error(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self._script(temp)
            info = ke.read_excerpt(path, 501)
            numbers = [n for n, _ in info['lines']]
            self.assertIn(501, numbers)
            self.assertLess(min(numbers), 501)
            self.assertGreater(max(numbers), 501)
            self.assertEqual(info['error'], '')

    def test_error_index_points_at_error_line(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self._script(temp)
            info = ke.read_excerpt(path, 501)
            number, _content = info['lines'][info['error_index']]
            self.assertEqual(number, 501)

    def test_error_near_top_of_file(self):
        """错误在第 2 行时不能算出负数起始行。"""
        with tempfile.TemporaryDirectory() as temp:
            path = self._script(temp)
            info = ke.read_excerpt(path, 2)
            self.assertGreaterEqual(info['start'], 1)
            self.assertEqual(info['lines'][info['error_index']][0], 2)

    def test_error_near_end_of_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self._script(temp, lines=10)
            info = ke.read_excerpt(path, 9)
            self.assertEqual(info['lines'][info['error_index']][0], 9)

    def test_line_beyond_file_end_is_tolerated(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self._script(temp, lines=10)
            info = ke.read_excerpt(path, 999)
            self.assertEqual(info['error'], '')
            self.assertEqual(info['error_index'], -1)   # 越界时不强行高亮

    def test_missing_file_reports_error(self):
        info = ke.read_excerpt(os.path.join('no', 'such.js'), 1)
        self.assertTrue(info['error'])
        self.assertEqual(info['lines'], [])

    def test_text_has_line_numbers(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self._script(temp)
            info = ke.read_excerpt(path, 501)
            self.assertIn('501', info['text'])


class GroupAndHintTests(unittest.TestCase):
    def test_group_by_file(self):
        groups = ke.group_by_file(ke.parse_errors(REAL_LOG))
        paths = [g['relpath'] for g in groups]
        self.assertEqual(paths, ['business/counter.js', 'startup_scripts/wine.js'])
        self.assertEqual(groups[0]['count'], 1)

    def test_summarize(self):
        self.assertIn('2 处', ke.summarize(ke.parse_errors(REAL_LOG)))
        self.assertIn('没有发现', ke.summarize([]))

    def test_hint_for_missing_function_mentions_patch_data(self):
        """本项目真实教训:看起来像脚本写错,其实是缺补丁数据。"""
        errors = ke.parse_errors(REAL_LOG)
        hints = ke.hints_for(errors[0])
        self.assertTrue(hints)
        self.assertTrue(any('补丁' in h for h in hints))

    def test_hint_for_reference_error(self):
        errors = ke.parse_errors(REAL_LOG)
        wine = next(e for e in errors if e['relpath'].endswith('wine.js'))
        self.assertTrue(any('作用域' in h or '拼写' in h for h in ke.hints_for(wine)))

    def test_no_hint_for_unknown_error(self):
        record = {'title': 'Error in X', 'message': 'something else entirely'}
        self.assertEqual(ke.hints_for(record), [])


if __name__ == '__main__':
    unittest.main()
