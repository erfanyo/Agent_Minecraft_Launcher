import json
import hashlib
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch, Mock
import diagnostic_tools as d


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'versions' / 'demo'
        (self.folder / 'mods').mkdir(parents=True)
        (self.folder / 'demo.json').write_text(json.dumps({'id': 'demo', 'mainClass': 'test.Main'}))
        (self.folder / 'amcl_instance.json').write_text(json.dumps({'minecraft_version': '1.21.1', 'loader': 'neoforge'}))
        for name, replacement in [('diagnostic_tools.paths.GAME_DIR', str(self.root)),
                                  ('diagnostic_tools.assert_stopped', Mock()),
                                  ('settings.load_settings', Mock(return_value={'version_isolation': True}))]:
            p = patch(name, replacement)
            p.start()
            self.addCleanup(p.stop)

    def test_snapshot_restore_exact_and_keep_previous(self):
        (self.folder / 'mods' / 'bad.jar').write_bytes(b'old')
        snap = json.loads(d.snapshot_instance('demo'))
        (self.folder / 'mods' / 'bad.jar').write_bytes(b'changed')
        (self.folder / 'extra').write_text('new')
        result = d.restore_instance_snapshot('demo', snap['snapshot_id'])
        self.assertEqual((self.folder / 'mods' / 'bad.jar').read_bytes(), b'old')
        self.assertFalse((self.folder / 'extra').exists())
        self.assertIn('保留', result)
        self.assertEqual(len(list((self.root / 'diagnostic_snapshots' / 'demo').glob('before-restore-*'))), 1)
        with self.assertRaises(ValueError):
            d.check_constraint('demo', '1.20.1', 'forge')

    def test_corrupt_snapshot_refused(self):
        snap = json.loads(d.snapshot_instance('demo'))
        Path(snap['directory'], 'files', 'demo.json').write_text('corrupt')
        with self.assertRaises(ValueError):
            d.restore_instance_snapshot('demo', snap['snapshot_id'])
        self.assertIn('test.Main', (self.folder / 'demo.json').read_text())

    def test_toggle_roundtrip_and_collision(self):
        jar = self.folder / 'mods' / 'x.jar'
        jar.write_bytes(b'x')
        d.set_mod_enabled('demo', 'x.jar', False)
        self.assertFalse(jar.exists())
        d.set_mod_enabled('demo', 'x.jar.disabled', True)
        self.assertEqual(jar.read_bytes(), b'x')
        (self.folder / 'mods' / 'x.jar.disabled').write_bytes(b'keep')
        with self.assertRaises(ValueError):
            d.set_mod_enabled('demo', 'x.jar', False)

    def test_renamed_jar_identity(self):
        with zipfile.ZipFile(self.folder / 'mods' / 'obs.jar', 'w') as archive:
            archive.writestr('fabric.mod.json', '{"id":"iris","version":"test"}')
        result = json.loads(d.inspect_mod_jar('demo', 'obs.jar'))
        self.assertIn('iris', result['metadata']['fabric.mod.json'])
        self.assertEqual(len(result['sha256']), 64)
        mismatch = json.loads(d.inspect_mod_jar('demo', 'obs.jar', '0' * 40))
        self.assertFalse(mismatch['matches_expected_sha1'])

    def test_snapshot_diff(self):
        snap = json.loads(d.snapshot_instance('demo'))
        (self.folder / 'mods' / 'new.jar').write_bytes(b'new')
        report = json.loads(d.compare_instance_snapshot('demo', snap['snapshot_id']))
        self.assertEqual(report['counts']['added'], 1)

    def test_summary_keeps_dependency_from_middle_of_long_metadata(self):
        metadata = ('modLoader="javafml"\nloaderVersion="[4,)"\n'
                    '[[mods]]\nmodId="sample"\nversion="1.0"\ndescription="' + 'x' * 10000 + '"\n'
                    '[[dependencies.sample]]\nmodId="essential"\ntype="required"\nversionRange="[2,3)"\n'
                    '[[dependencies.sample]]\nmodId="conflict"\ntype="incompatible"\nversionRange="*"\n'
                    '[[mixins]]\nconfig="sample.mixins.json"\n')
        with zipfile.ZipFile(self.folder / 'mods' / 'sample.jar', 'w') as archive:
            archive.writestr('META-INF/neoforge.mods.toml', metadata)
        result = json.loads(d.inspect_mod_jar('demo', 'sample.jar', view='summary'))
        declarations = result['metadata_summary']['META-INF/neoforge.mods.toml']['declarations']
        self.assertEqual(declarations['dependencies']['sample'][0]['modId'], 'essential')
        self.assertEqual(declarations['dependencies']['sample'][1]['type'], 'incompatible')
        self.assertEqual(declarations['mixins'], [{'config': 'sample.mixins.json'}])
        self.assertNotIn('metadata', result)
        self.assertLess(len(json.dumps(result)), 3000)

    def test_invalid_metadata_is_not_treated_as_no_dependencies(self):
        with zipfile.ZipFile(self.folder / 'mods' / 'broken.jar', 'w') as archive:
            archive.writestr('fabric.mod.json', '{bad-json')
        result = json.loads(d.inspect_mod_jar('demo', 'broken.jar', view='summary'))
        self.assertEqual(result['metadata_summary']['fabric.mod.json']['status'], 'parse_error')

    def test_toggle_returns_executable_undo(self):
        jar = self.folder / 'mods' / 'x.jar'
        jar.write_bytes(b'original')
        changed = json.loads(d.set_mod_enabled('demo', 'x.jar', False,
                                               reason='wrong_game_version'))
        self.assertEqual(changed['reason'], 'wrong_game_version')
        self.assertIn('原文件仍保留', changed['user_effect'])
        d.set_mod_enabled(**changed['undo']['arguments'])
        self.assertEqual(jar.read_bytes(), b'original')

    def test_paths_and_shared_data(self):
        with self.assertRaises(ValueError):
            d.inspect_mod_jar('demo', '../bad.jar')
        with patch('settings.load_settings', return_value={'version_isolation': False}):
            with self.assertRaises(ValueError):
                d.snapshot_instance('demo')

    def test_no_historical_success(self):
        self.assertIn('没有本次', d.observe_game('demo'))

    def test_instance_core_verification_distinguishes_verified_and_damaged(self):
        client = b'client-core'
        library = b'loader-library'
        (self.folder / 'demo.jar').write_bytes(client)
        relative = 'net/neoforged/neoforge/21.1.250/neoforge.jar'
        library_path = self.root / 'libraries' / Path(relative)
        library_path.parent.mkdir(parents=True)
        library_path.write_bytes(library)
        detail = {
            'id': 'demo', 'mainClass': 'cpw.mods.bootstraplauncher.BootstrapLauncher',
            'downloads': {'client': {'sha1': hashlib.sha1(client).hexdigest(),
                                     'size': len(client)}},
            'libraries': [{'name': 'net.neoforged:neoforge:21.1.250',
                           'downloads': {'artifact': {'path': relative,
                                                      'sha1': hashlib.sha1(library).hexdigest(),
                                                      'size': len(library)}}}],
        }
        (self.folder / 'demo.json').write_text(json.dumps(detail), encoding='utf-8')
        verified = json.loads(d.inspect_instance_core('demo'))
        self.assertEqual(verified['status'], 'verified')
        self.assertFalse(verified['repair_recommended'])
        library_path.write_bytes(b'corrupt')
        damaged = json.loads(d.inspect_instance_core('demo'))
        self.assertEqual(damaged['status'], 'issues_found')
        self.assertTrue(damaged['repair_recommended'])
        self.assertEqual(damaged['libraries']['issues'][0]['status'], 'size_mismatch')

    def test_observe_game_is_bounded_and_keeps_success_signal(self):
        logfile = self.folder / 'current.log'
        logfile.write_text(('ordinary startup line\n' * 5000) +
                           '[Server thread/INFO]: player joined the game\n', encoding='utf-8')
        process = Mock(pid=123)
        process.wait.side_effect = __import__('subprocess').TimeoutExpired('game', 0)
        process.poll.return_value = None
        d._runs[(os.path.realpath(self.root), 'demo')] = (process, str(logfile), time.monotonic())
        with patch('settings.load_settings', return_value={}):
            result = json.loads(d.observe_game('demo', 0))
        self.assertTrue(result['signals']['joined_world'])
        self.assertLess(len(json.dumps(result)), 12000)

    def test_compatible_version_results_omit_download_urls(self):
        response = Mock()
        response.json.return_value = [{
            'id': 'version-id', 'version_number': '1.0', 'version_type': 'release',
            'game_versions': ['1.21.1'], 'loaders': ['neoforge'],
            'files': [{'primary': True, 'filename': 'demo.jar', 'size': 10,
                       'url': 'https://cdn.modrinth.com/secretly-long',
                       'hashes': {'sha1': 'a' * 40}}],
            'dependencies': [{'project_id': 'dep', 'version_id': None,
                              'dependency_type': 'required'}],
        }]
        with patch('requests.get', return_value=response):
            result = d.find_compatible_mod_versions('demo', 'project')
        self.assertNotIn('https://', result)
        self.assertEqual(json.loads(result)[0]['file']['sha1'], 'a' * 40)

    def test_compatible_replacement_uses_hash_identity_and_cache(self):
        with zipfile.ZipFile(self.folder / 'mods' / 'renamed.jar', 'w') as archive:
            archive.writestr('fabric.mod.json', '{"id":"demo-mod","name":"Demo Mod","version":"9"}')
        hash_response = Mock(status_code=200)
        hash_response.json.return_value = {'project_id': 'project-id'}
        versions_response = Mock()
        versions_response.json.return_value = [{
            'id': 'compatible-version', 'version_number': '2.0', 'version_type': 'release',
            'game_versions': ['1.21.1'], 'loaders': ['neoforge'],
            'files': [{'primary': True, 'filename': 'demo-neoforge.jar', 'size': 12,
                       'hashes': {'sha1': 'b' * 40}}], 'dependencies': []}]
        with patch('requests.get', side_effect=[hash_response, versions_response]) as get:
            first = json.loads(d.find_compatible_mod_replacement('demo', 'renamed.jar'))
            second = json.loads(d.find_compatible_mod_replacement('demo', 'renamed.jar'))
        self.assertEqual(first['action'], 'replace')
        self.assertEqual(first['recommended']['version_id'], 'compatible-version')
        self.assertEqual(first['identity_source'], 'file_hash')
        self.assertTrue(second['cached'])
        self.assertEqual(get.call_count, 2)

    def test_compatible_replacement_searches_internal_id_then_falls_back(self):
        with zipfile.ZipFile(self.folder / 'mods' / 'random.jar', 'w') as archive:
            archive.writestr('META-INF/neoforge.mods.toml',
                             'modLoader="javafml"\n[[mods]]\nmodId="actualmod"\ndisplayName="Actual Mod"\nversion="1"')
        missing_hash = Mock(status_code=404)
        search_response = Mock()
        search_response.json.return_value = {'hits': [{'slug': 'actualmod', 'title': 'Actual Mod'}]}
        versions_response = Mock()
        versions_response.json.return_value = []
        with patch('requests.get', side_effect=[missing_hash, search_response, versions_response]):
            result = json.loads(d.find_compatible_mod_replacement('demo', 'random.jar'))
        self.assertEqual(result['project']['slug'], 'actualmod')
        self.assertEqual(result['action'], 'no_compatible_release')
        self.assertEqual(result['identity_source'], 'internal_mod_id')

    def test_wrong_loader_replacement_refused(self):
        response = Mock()
        response.json.return_value = {'game_versions': ['1.21.1'], 'loaders': ['fabric']}
        with patch('requests.get', return_value=response):
            with self.assertRaises(ValueError):
                d.replace_mod_version('demo', 'old.jar', 'version')

    def test_tools_are_mounted(self):
        from assistant import mount_tools_for, WRITE_TOOLS, CONFIRM_TOOLS
        names = {t['function']['name'] for t in mount_tools_for('地狱测试修复', None)}
        self.assertTrue({'snapshot_instance', 'restore_instance_snapshot', 'inspect_mod_jar',
                         'find_compatible_mod_replacement',
                         'inspect_instance_core', 'observe_game', 'replace_mod_version',
                         'compare_instance_snapshot', 'launch_game', 'repair_instance_core'} <= names)
        self.assertIn('restore_instance_snapshot', WRITE_TOOLS & CONFIRM_TOOLS)

    def test_launch_uses_shared_preparation(self):
        from types import SimpleNamespace
        plan = SimpleNamespace(command=['java', '-Xmx4G', 'Main'], game_dir=str(self.folder))
        process = Mock(pid=987654)
        process.poll.return_value = None
        with patch('game_launch_service.GameLaunchService') as service, \
             patch('diagnostic_tools.subprocess.Popen', return_value=process) as popen, \
             patch('diagnostic_tools.paths.data_dir', return_value=str(self.root)), \
             patch('memory_policy.track_process'):
            service.return_value.prepare.return_value = plan
            result = d.diagnostic_launch('demo')
            self.assertIn('尚未确认', result)
            service.return_value.prepare.assert_called_once()
            self.assertEqual(popen.call_args.args[0], plan.command)
        d._runs.pop((str(self.root.resolve()), 'demo'), None)


if __name__ == '__main__':
    unittest.main()
