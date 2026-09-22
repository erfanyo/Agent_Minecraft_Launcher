# -*- coding: utf-8 -*-
"""内容包目录管理(纯逻辑)单测。

重点锁住两条**不能出错**的:
- 同名冲突**不覆盖**(宁可多留一个,也不能把别人的包盖掉);
- 压缩包解压**不能逃出目标目录**(zip slip:``../`` 或绝对路径)。
"""
import os
import tempfile
import unittest
import zipfile

import pack_folder as pf


def _write(path, text='x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as stream:
        stream.write(text)
    return path


def _zip(path, members):
    with zipfile.ZipFile(path, 'w') as bundle:
        for name, text in members.items():
            bundle.writestr(name, text)
    return path


class HumanSizeTests(unittest.TestCase):
    def test_units(self):
        self.assertEqual(pf.human_size(0), '0 B')
        self.assertEqual(pf.human_size(512), '512 B')
        self.assertEqual(pf.human_size(2048), '2.0 KB')
        self.assertEqual(pf.human_size(5 * 1024 * 1024), '5.0 MB')

    def test_bad_input(self):
        self.assertEqual(pf.human_size('abc'), '未知')
        self.assertEqual(pf.human_size(None), '未知')


class DirSizeTests(unittest.TestCase):
    def test_counts_files_and_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            _write(os.path.join(temp, 'a.txt'), '12345')
            _write(os.path.join(temp, 'sub', 'b.txt'), '123')
            size, count = pf.dir_size(temp)
            self.assertEqual(count, 2)
            self.assertEqual(size, 8)

    def test_missing_dir(self):
        self.assertEqual(pf.dir_size(os.path.join(tempfile.gettempdir(), 'nope-xyz')), (0, 0))


class MatchesTests(unittest.TestCase):
    def test_empty_exts_allows_everything(self):
        self.assertTrue(pf.matches('anything.bin', ()))

    def test_case_insensitive(self):
        self.assertTrue(pf.matches('Skin.PNG', ('.png',)))
        self.assertFalse(pf.matches('skin.png', ('.nbt',)))


class ScanTests(unittest.TestCase):
    def test_files_filtered_by_ext_but_dirs_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            _write(os.path.join(temp, 'a.nbt'))
            _write(os.path.join(temp, 'notes.txt'))
            _write(os.path.join(temp, 'pack', 'inner.txt'))
            entries = pf.scan(temp, exts=('.nbt',))
            names = [e['name'] for e in entries]
            self.assertEqual(names, ['a.nbt', 'pack'])
            pack = next(e for e in entries if e['name'] == 'pack')
            self.assertTrue(pack['is_dir'])
            self.assertEqual(pack['file_count'], 1)

    def test_archive_junk_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            os.makedirs(os.path.join(temp, '__MACOSX'))
            entries = pf.scan(temp)
            self.assertEqual(entries, [])

    def test_missing_root(self):
        self.assertEqual(pf.scan(''), [])
        self.assertEqual(pf.scan(os.path.join(tempfile.gettempdir(), 'nope-xyz')), [])


class ScanTreeTests(unittest.TestCase):
    def test_relative_paths_use_forward_slashes(self):
        with tempfile.TemporaryDirectory() as temp:
            _write(os.path.join(temp, 'com', 'demo', 'Thing.badiff'))
            _write(os.path.join(temp, 'com', 'demo', 'other.txt'))
            entries = pf.scan_tree(temp, exts=('.badiff',))
            self.assertEqual([e['name'] for e in entries], ['com/demo/Thing.badiff'])

    def test_missing_root(self):
        self.assertEqual(pf.scan_tree(''), [])


class SummarizeTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(pf.summarize([], '个'), '空')

    def test_counts(self):
        entries = [{'file_count': 2, 'size': 1024}, {'file_count': 1, 'size': 1024}]
        self.assertEqual(pf.summarize(entries, '套'), '2 套 · 共 3 个文件 · 2.0 KB')


class UniqueDestTests(unittest.TestCase):
    def test_free_name_used_as_is(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(pf.unique_dest(temp, 'a.txt'), os.path.join(temp, 'a.txt'))

    def test_conflicts_get_suffix(self):
        with tempfile.TemporaryDirectory() as temp:
            _write(os.path.join(temp, 'a.txt'))
            self.assertEqual(pf.unique_dest(temp, 'a.txt'), os.path.join(temp, 'a (2).txt'))
            _write(os.path.join(temp, 'a (2).txt'))
            self.assertEqual(pf.unique_dest(temp, 'a.txt'), os.path.join(temp, 'a (3).txt'))


class ExtractArchiveTests(unittest.TestCase):
    def test_extracts_nested_files(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _zip(os.path.join(temp, 'p.zip'), {'pack/a.txt': '1', 'pack/b.txt': '2'})
            target = os.path.join(temp, 'out')
            out = pf.extract_archive(target, archive)
            self.assertEqual(sorted(out['added']), ['pack/a.txt', 'pack/b.txt'])
            self.assertTrue(os.path.isfile(os.path.join(target, 'pack', 'a.txt')))

    def test_existing_files_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _zip(os.path.join(temp, 'p.zip'), {'a.txt': 'new'})
            target = os.path.join(temp, 'out')
            _write(os.path.join(target, 'a.txt'), 'old')
            out = pf.extract_archive(target, archive)
            self.assertEqual(out['added'], [])
            self.assertEqual(out['skipped'], ['a.txt'])
            with open(os.path.join(target, 'a.txt'), encoding='utf-8') as stream:
                self.assertEqual(stream.read(), 'old')

    def test_zip_slip_is_blocked(self):
        """../../ 逃逸必须被挡掉——否则一个恶意压缩包能往任意位置写文件。"""
        with tempfile.TemporaryDirectory() as temp:
            archive = _zip(os.path.join(temp, 'evil.zip'),
                           {'../escaped.txt': 'bad', 'ok.txt': 'fine'})
            target = os.path.join(temp, 'out')
            out = pf.extract_archive(target, archive)
            self.assertIn('../escaped.txt', out['skipped'])
            self.assertFalse(os.path.exists(os.path.join(temp, 'escaped.txt')))
            self.assertEqual(out['added'], ['ok.txt'])

    def test_absolute_member_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _zip(os.path.join(temp, 'evil.zip'), {'/etc/passwd': 'bad'})
            target = os.path.join(temp, 'out')
            out = pf.extract_archive(target, archive)
            self.assertEqual(out['added'], [])
            self.assertEqual(out['skipped'], ['/etc/passwd'])

    def test_macosx_members_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _zip(os.path.join(temp, 'p.zip'),
                           {'__MACOSX/._a': 'junk', 'a.txt': 'ok'})
            out = pf.extract_archive(os.path.join(temp, 'out'), archive)
            self.assertEqual(out['added'], ['a.txt'])
            self.assertIn('__MACOSX/._a', out['skipped'])

    def test_backslash_member_is_also_a_separator(self):
        """Windows 上压缩包成员常用反斜杠;解到底还是得落到子目录、垃圾仍要被跳过。"""
        with tempfile.TemporaryDirectory() as temp:
            archive = _zip(os.path.join(temp, 'p.zip'),
                           {'__MACOSX\\junk.txt': 'j', 'sub\\ok.txt': 'ok'})
            target = os.path.join(temp, 'out')
            out = pf.extract_archive(target, archive)
            self.assertTrue(os.path.isfile(os.path.join(target, 'sub', 'ok.txt')))
            self.assertFalse(os.path.exists(os.path.join(target, '__MACOSX')))
            self.assertEqual(len(out['added']), 1)

    def test_safe_member_handles_raw_backslashes(self):
        """直接喂反斜杠给底层函数(不能只在 zipfile 归一化之后才安全)。"""
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(pf._safe_member(temp, '__MACOSX\\junk.txt'))
            self.assertIsNone(pf._safe_member(temp, '..\\escaped.txt'))
            self.assertIsNone(pf._safe_member(temp, 'a\\..\\..\\escaped.txt'))
            self.assertEqual(pf._safe_member(temp, 'sub\\ok.txt'),
                             os.path.join(temp, 'sub', 'ok.txt'))

    def test_drive_letter_member_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _zip(os.path.join(temp, 'evil.zip'), {'C:/evil.txt': 'bad'})
            out = pf.extract_archive(os.path.join(temp, 'out'), archive)
            self.assertEqual(out['added'], [])

    def test_bad_zip_reports_error(self):
        with tempfile.TemporaryDirectory() as temp:
            broken = _write(os.path.join(temp, 'broken.zip'), 'not a zip')
            out = pf.extract_archive(os.path.join(temp, 'out'), broken)
            self.assertEqual(out['added'], [])
            self.assertEqual(len(out['errors']), 1)


class ImportSourcesTests(unittest.TestCase):
    def test_matching_file_copied(self):
        with tempfile.TemporaryDirectory() as temp:
            source = _write(os.path.join(temp, 'src', 'a.nbt'))
            target = os.path.join(temp, 'root')
            out = pf.import_sources(target, [source], exts=('.nbt',))
            self.assertEqual(out['added'], ['a.nbt'])
            self.assertTrue(os.path.isfile(os.path.join(target, 'a.nbt')))

    def test_mismatched_file_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            source = _write(os.path.join(temp, 'src', 'a.txt'))
            out = pf.import_sources(os.path.join(temp, 'root'), [source], exts=('.nbt',))
            self.assertEqual(out['added'], [])
            self.assertEqual(out['skipped'], ['a.txt'])

    def test_folder_copied_as_one_pack(self):
        with tempfile.TemporaryDirectory() as temp:
            pack = os.path.join(temp, 'src', 'MyPack')
            _write(os.path.join(pack, 'pack.mcmeta'), '{}')
            target = os.path.join(temp, 'root')
            out = pf.import_sources(target, [pack])
            self.assertEqual(out['added'], ['MyPack'])
            self.assertTrue(os.path.isfile(os.path.join(target, 'MyPack', 'pack.mcmeta')))

    def test_zip_is_extracted_not_copied(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _zip(os.path.join(temp, 'gun.zip'), {'guns/a.json': '{}'})
            target = os.path.join(temp, 'root')
            out = pf.import_sources(target, [archive])
            self.assertEqual(out['added'], ['guns/a.json'])
            self.assertFalse(os.path.exists(os.path.join(target, 'gun.zip')))

    def test_source_folder_is_left_alone(self):
        with tempfile.TemporaryDirectory() as temp:
            source = _write(os.path.join(temp, 'src', 'a.nbt'))
            pf.import_sources(os.path.join(temp, 'root'), [source], exts=('.nbt',))
            self.assertTrue(os.path.isfile(source))

    def test_second_import_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            source = _write(os.path.join(temp, 'src', 'a.nbt'), 'first')
            target = os.path.join(temp, 'root')
            pf.import_sources(target, [source], exts=('.nbt',))
            _write(source, 'second')
            out = pf.import_sources(target, [source], exts=('.nbt',))
            self.assertEqual(out['added'], ['a (2).nbt'])
            with open(os.path.join(target, 'a.nbt'), encoding='utf-8') as stream:
                self.assertEqual(stream.read(), 'first')

    def test_missing_source_reports_error(self):
        with tempfile.TemporaryDirectory() as temp:
            out = pf.import_sources(os.path.join(temp, 'root'),
                                    [os.path.join(temp, 'gone.nbt')])
            self.assertEqual(out['added'], [])
            self.assertEqual(out['errors'][0][1], '文件不存在')

    def test_empty_root_reports_error(self):
        out = pf.import_sources('', ['x'])
        self.assertEqual(out['errors'][0][1], '目标目录未知')

    def test_target_created_on_demand(self):
        with tempfile.TemporaryDirectory() as temp:
            target = os.path.join(temp, 'deep', 'root')
            pf.import_sources(target, [])
            self.assertTrue(os.path.isdir(target))


class RemovePathsTests(unittest.TestCase):
    def test_removes_file_and_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            _write(os.path.join(temp, 'a.txt'))
            _write(os.path.join(temp, 'pack', 'inner.txt'))
            out = pf.remove_paths([os.path.join(temp, 'a.txt'),
                                   os.path.join(temp, 'pack')])
            self.assertEqual(sorted(out['removed']), ['a.txt', 'pack'])
            self.assertFalse(os.path.exists(os.path.join(temp, 'a.txt')))
            self.assertFalse(os.path.exists(os.path.join(temp, 'pack')))

    def test_missing_path_reports_error(self):
        with tempfile.TemporaryDirectory() as temp:
            out = pf.remove_paths([os.path.join(temp, 'gone')])
            self.assertEqual(out['removed'], [])
            self.assertEqual(len(out['errors']), 1)


class ImportSummaryTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(pf.import_summary({'added': ['a'], 'skipped': [], 'errors': []}),
                         '已导入 1 项')

    def test_mentions_skips_and_errors(self):
        text = pf.import_summary({'added': ['a'], 'skipped': ['b'],
                                  'errors': [('c', 'boom')]})
        self.assertIn('跳过 1 项', text)
        self.assertIn('1 项失败', text)

    def test_tolerates_none(self):
        self.assertEqual(pf.import_summary(None), '已导入 0 项')


if __name__ == '__main__':
    unittest.main()
