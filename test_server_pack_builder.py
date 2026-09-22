import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from archive_inspection import inspect_archive
from server_pack_builder import build_candidate_server_pack, supported_conversion
from server_pack_rules import inspect_client_instance, sha256_file
from server_packs import import_server_pack, list_servers, read_candidate_report
from agent_tools import (list_server_instances, list_server_mods,
                         read_server_candidate_report, set_server_mod_enabled)


def _jar(path, metadata_name=None, metadata=None):
    with zipfile.ZipFile(path, 'w') as archive:
        if metadata_name:
            archive.writestr(metadata_name, metadata)
        archive.writestr('example/Marker.class', b'not-a-real-class')


def _fake_forge_runtime(root, loader, mc, version, java, status=lambda _: None):
    assert loader == 'forge'
    entry = Path(root, 'libraries', 'net', 'minecraftforge', 'forge', f'{mc}-{version}')
    entry.mkdir(parents=True)
    entry.joinpath('win_args.txt').write_text(
        'cpw.mods.bootstraplauncher.BootstrapLauncher '
        f'--launchTarget forgeserver --fml.forgeVersion {version} '
        f'--fml.mcVersion {mc} --fml.forgeGroup net.minecraftforge '
        '--fml.mcpVersion 20230612.114412', encoding='utf-8')
    entry.joinpath('unix_args.txt').write_text(
        'cpw.mods.bootstraplauncher.BootstrapLauncher '
        f'--launchTarget forgeserver --fml.forgeVersion {version} '
        f'--fml.mcVersion {mc} --fml.forgeGroup net.minecraftforge '
        '--fml.mcpVersion 20230612.114412', encoding='utf-8')
    return {'loader': loader, 'minecraftVersion': mc}


class ServerPackBuilderTests(unittest.TestCase):
    def test_rules_exclude_only_proven_client_mod_and_flag_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp, 'instance')
            root.joinpath('mods').mkdir(parents=True)
            root.joinpath('config').mkdir()
            _jar(root / 'mods' / 'client.jar', 'fabric.mod.json', json.dumps({
                'schemaVersion': 1, 'id': 'client_only', 'version': '1',
                'environment': 'client'}))
            _jar(root / 'mods' / 'unknown.jar')
            root.joinpath('config', 'bridge.toml').write_text(
                'rcon_password = "do-not-copy-this-value-into-report"', encoding='utf-8')
            report = inspect_client_instance(root)
            actions = {item['file']: item['action'] for item in report['mods']}
            self.assertEqual(actions['client.jar'], 'excluded')
            self.assertEqual(actions['unknown.jar'], 'included')
            self.assertEqual(report['secretPaths'], ['config/bridge.toml'])
            self.assertNotIn('do-not-copy-this-value-into-report', json.dumps(report))

    def test_build_is_read_only_and_emits_reviewable_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp, 'instance')
            root.joinpath('mods').mkdir(parents=True)
            root.joinpath('config').mkdir()
            _jar(root / 'mods' / 'client.jar', 'fabric.mod.json', json.dumps({
                'schemaVersion': 1, 'id': 'client_only', 'version': '1',
                'environment': 'client'}))
            _jar(root / 'mods' / 'keep.jar')
            root.joinpath('config', 'common.toml').write_text('enabled=true', encoding='utf-8')
            before = {path.relative_to(root).as_posix(): sha256_file(path)
                      for path in root.rglob('*') if path.is_file()}
            output = Path(temp, 'candidate.zip')
            result = build_candidate_server_pack(
                root, output, name='Test Candidate', minecraft='1.20.1',
                loader='forge', loader_version='47.2.0', java='unused-java',
                runtime_installer=_fake_forge_runtime)
            after = {path.relative_to(root).as_posix(): sha256_file(path)
                     for path in root.rglob('*') if path.is_file()}
            self.assertEqual(before, after)
            self.assertFalse(result['report']['verification']['minecraftStarted'])
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertIn('server/mods/keep.jar', names)
                self.assertNotIn('server/mods/client.jar', names)
                self.assertNotIn('server/eula.txt', names)
                self.assertIn('amcl-build-report.json', names)
                report_text = archive.read('amcl-build-report.json').decode('utf-8')
                self.assertNotIn(str(root), report_text)
            scan = inspect_archive(output)
            self.assertEqual(scan['kind'], 'server')
            self.assertEqual(scan['loader'], 'forge')
            self.assertEqual(scan['minecraftVersion'], '1.20.1')
            game_dir = Path(temp, 'game')
            imported = import_server_pack(output, game_dir, scan['sha256'],
                                          display_name='Readable candidate')
            servers = list_servers(game_dir)
            self.assertEqual(len(servers), 1)
            self.assertTrue(servers[0]['candidate'])
            self.assertEqual(servers[0]['name'], 'Readable candidate')
            self.assertEqual(read_candidate_report(servers[0])['verification']['level'],
                             'static-launch-plan')
            self.assertTrue(Path(imported).is_dir())
            self.assertIn('Readable candidate', list_server_instances(game_dir))
            self.assertIn('keep.jar', list_server_mods('Readable candidate', game_dir))
            self.assertIn('静态验证', read_server_candidate_report(
                'Readable candidate', game_dir))
            changed = set_server_mod_enabled('Readable candidate', 'keep.jar', False,
                                             'diagnostic_only', game_dir)
            self.assertIn('已停用', changed)
            self.assertTrue(Path(servers[0]['path'], 'mods', 'keep.jar.disabled').is_file())
            restored = set_server_mod_enabled('Readable candidate', 'keep.jar', True,
                                              'diagnostic_only', game_dir)
            self.assertIn('已启用', restored)

    def test_unsupported_loader_stops_before_build(self):
        ok, reason = supported_conversion('fabric', '1.20.1')
        self.assertFalse(ok)
        self.assertIn('Forge', reason)

    def test_server_repair_prompt_mounts_server_tools(self):
        from assistant import mount_tools_for
        names = {item['function']['name'] for item in
                 mount_tools_for('帮我修复候选服务端崩溃')}
        self.assertIn('read_server_candidate_report', names)
        self.assertIn('read_server_log', names)
        self.assertIn('set_server_mod_enabled', names)


if __name__ == '__main__':
    unittest.main()
