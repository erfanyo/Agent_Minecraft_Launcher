# -*- coding: utf-8 -*-
"""KubeJS 工具插件的「目标选择」逻辑单测。

插件不能挂进实例/服务端详情的左菜单(插件 API 只给主标签页与联机中心页),
所以它自带一个目标列表:列出**存在 kubejs 目录**的客户端实例与服务端。
这里用假目录验证枚举、过滤、排序与稳定键,不依赖真实游戏目录。
"""
import os
import tempfile
import unittest
from unittest import mock

import kubejs_targets as kt


def _touch_kubejs(root):
    os.makedirs(os.path.join(root, 'kubejs', 'server_scripts'), exist_ok=True)
    with open(os.path.join(root, 'kubejs', 'server_scripts', 'a.js'), 'w',
              encoding='utf-8') as f:
        f.write('x')


class InstanceTargetTests(unittest.TestCase):
    def test_only_instances_with_kubejs_are_listed(self):
        with tempfile.TemporaryDirectory() as temp:
            good = os.path.join(temp, 'has_kubejs')
            plain = os.path.join(temp, 'no_kubejs')
            os.makedirs(good)
            os.makedirs(plain)
            _touch_kubejs(good)
            rows = [{'id': 'has_kubejs', 'name': '有脚本', 'path': good},
                    {'id': 'no_kubejs', 'name': '没脚本', 'path': plain}]
            with mock.patch('instances.scan_instances', return_value=rows):
                targets = kt.instance_targets(temp)
            self.assertEqual([t['id'] for t in targets], ['has_kubejs'])
            self.assertEqual(targets[0]['kind'], 'client')

    def test_scan_failure_returns_empty(self):
        with mock.patch('instances.scan_instances', side_effect=RuntimeError('x')):
            self.assertEqual(kt.instance_targets('whatever'), [])

    def test_falls_back_to_versions_layout(self):
        """记录里没有 path 时按 versions/<id> 推断。"""
        with tempfile.TemporaryDirectory() as temp:
            folder = os.path.join(temp, 'versions', 'inst1')
            os.makedirs(folder)
            _touch_kubejs(folder)
            with mock.patch('instances.scan_instances',
                            return_value=[{'id': 'inst1', 'name': 'A'}]):
                targets = kt.instance_targets(temp)
            self.assertEqual(len(targets), 1)
            self.assertTrue(targets[0]['kubejs'].endswith('kubejs'))


class ServerTargetTests(unittest.TestCase):
    def test_server_uses_record_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, 'server-labhf5v8')
            server_dir = os.path.join(root, 'server')
            os.makedirs(server_dir)
            _touch_kubejs(server_dir)
            rows = [{'id': 'server-labhf5v8', 'name': '地下酒吧-server',
                     'path': server_dir}]
            with mock.patch('server_packs.list_servers', return_value=rows):
                targets = kt.server_targets(temp)
            self.assertEqual(len(targets), 1)
            self.assertEqual(targets[0]['kind'], 'server')
            self.assertEqual(targets[0]['id'], 'server-labhf5v8')

    def test_server_without_kubejs_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            server_dir = os.path.join(temp, 'plain')
            os.makedirs(server_dir)
            with mock.patch('server_packs.list_servers',
                            return_value=[{'id': 'p', 'name': 'P',
                                           'path': server_dir}]):
                self.assertEqual(kt.server_targets(temp), [])

    def test_scan_failure_returns_empty(self):
        with mock.patch('server_packs.list_servers', side_effect=RuntimeError('x')):
            self.assertEqual(kt.server_targets('whatever'), [])


class CombinedTests(unittest.TestCase):
    def _fake(self, temp):
        client_dir = os.path.join(temp, 'client')
        server_dir = os.path.join(temp, 'server')
        os.makedirs(client_dir)
        os.makedirs(server_dir)
        _touch_kubejs(client_dir)
        _touch_kubejs(server_dir)
        return client_dir, server_dir

    def test_clients_come_before_servers(self):
        with tempfile.TemporaryDirectory() as temp:
            client_dir, server_dir = self._fake(temp)
            with mock.patch('instances.scan_instances',
                            return_value=[{'id': 'c', 'name': 'Zeta',
                                           'path': client_dir}]), \
                 mock.patch('server_packs.list_servers',
                            return_value=[{'id': 's', 'name': 'Alpha',
                                           'path': server_dir}]):
                targets = kt.all_targets(temp)
            self.assertEqual([t['kind'] for t in targets], ['client', 'server'])

    def test_targets_sorted_by_name(self):
        with tempfile.TemporaryDirectory() as temp:
            first = os.path.join(temp, 'b')
            second = os.path.join(temp, 'a')
            os.makedirs(first)
            os.makedirs(second)
            _touch_kubejs(first)
            _touch_kubejs(second)
            with mock.patch('instances.scan_instances',
                            return_value=[{'id': 'b', 'name': 'Bravo', 'path': first},
                                          {'id': 'a', 'name': 'Alpha', 'path': second}]), \
                 mock.patch('server_packs.list_servers', return_value=[]):
                targets = kt.all_targets(temp)
            self.assertEqual([t['name'] for t in targets], ['Alpha', 'Bravo'])

    def test_label_marks_side(self):
        self.assertIn('客户端', kt.label_for({'kind': 'client', 'name': 'X'}))
        self.assertIn('服务端', kt.label_for({'kind': 'server', 'name': 'X'}))

    def test_target_key_and_find_round_trip(self):
        target = {'kind': 'server', 'id': 'server-1', 'name': 'S'}
        key = kt.target_key(target)
        self.assertEqual(key, 'server:server-1')
        self.assertIs(kt.find_target([target], key), target)

    def test_find_target_missing(self):
        self.assertIsNone(kt.find_target([], 'client:x'))
        self.assertIsNone(kt.find_target([{'kind': 'client', 'id': 'a'}],
                                         'server:a'))

    def test_script_count_only_counts_js_in_script_dirs(self):
        with tempfile.TemporaryDirectory() as temp:
            _touch_kubejs(temp)
            os.makedirs(os.path.join(temp, 'kubejs', 'assets'), exist_ok=True)
            with open(os.path.join(temp, 'kubejs', 'assets', 'not_script.js'), 'w',
                      encoding='utf-8') as f:
                f.write('x')
            with open(os.path.join(temp, 'kubejs', 'server_scripts', 'b.txt'), 'w',
                      encoding='utf-8') as f:
                f.write('x')
            # server_scripts 下 1 个 .js;assets 里的不算
            self.assertEqual(kt.script_count(os.path.join(temp, 'kubejs')), 1)


if __name__ == '__main__':
    unittest.main()
