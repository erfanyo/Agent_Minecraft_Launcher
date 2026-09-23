import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from archive_inspection import inspect_archive
from server_pack_builder import (apply_test_result_to_pack,
                                 build_candidate_server_pack, supported_conversion)
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

    def test_custom_top_level_folder_is_kept_not_filtered(self):
        """A hand-written integration folder must survive conversion.

        Regression for the real-world case where ``hotai/`` (patch data that
        makes a server-side API exist) was dropped by a fixed whitelist, so the
        candidate server booted but failed at runtime.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp, 'instance')
            root.joinpath('mods').mkdir(parents=True)
            root.joinpath('hotai', 'com', 'example').mkdir(parents=True)
            root.joinpath('hotai', 'com', 'example', 'Patch.badiff').write_bytes(b'patch')
            root.joinpath('tlm_custom_pack', 'models').mkdir(parents=True)
            root.joinpath('tlm_custom_pack', 'models', 'maid.json').write_text(
                '{}', encoding='utf-8')
            # Personal launcher data must still be dropped.
            root.joinpath('saves', 'world').mkdir(parents=True)
            root.joinpath('saves', 'world', 'level.dat').write_bytes(b'personal')
            root.joinpath('logs').mkdir()
            root.joinpath('logs', 'latest.log').write_text('noise', encoding='utf-8')
            report = inspect_client_instance(root)
            targets = {item['target'] for item in report['files']}
            self.assertIn('hotai/com/example/Patch.badiff', targets)
            self.assertIn('tlm_custom_pack/models/maid.json', targets)
            self.assertNotIn('saves/world/level.dat', targets)
            self.assertNotIn('logs/latest.log', targets)

    def test_mod_manifest_pins_original_names_without_renaming(self):
        """Mod filenames keep their Chinese prefixes; the manifest maps ids."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp, 'instance')
            root.joinpath('mods').mkdir(parents=True)
            display = '[机械动力] create-1.20.1-6.0.8.jar'
            _jar(root / 'mods' / display, 'META-INF/mods.toml',
                 'modLoader="javafml"\nloaderVersion="[47,)"\n'
                 '[[mods]]\nmodId="create"\ndisplayName="Create"\n')
            report = inspect_client_instance(root)
            entry = next(item for item in report['modManifest']
                         if item['file'] == display)
            self.assertEqual(entry['file'], display)
            self.assertFalse(entry['renamed'])
            self.assertEqual(entry['modId'], 'create')
            self.assertTrue(entry['fileAscii'].isascii())
            targets = {item['target'] for item in report['files']}
            self.assertIn(f'mods/{display}', targets)

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
                self.assertIn('amcl-mod-manifest.json', names)
                pinned = json.loads(archive.read('amcl-mod-manifest.json').decode('utf-8'))
                self.assertEqual(pinned['schemaVersion'], 1)
                self.assertEqual([item['file'] for item in pinned['mods']], ['keep.jar'])
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

    def test_test_exclusion_updates_zip_manifest_and_report(self):
        with tempfile.TemporaryDirectory() as temp:
            instance = Path(temp, 'instance')
            instance.joinpath('mods').mkdir(parents=True)
            _jar(instance / 'mods' / 'keep.jar')
            output = Path(temp, 'candidate.zip')
            build_candidate_server_pack(instance, output, name='Test',
                minecraft='1.20.1', loader='forge', loader_version='47.2.0',
                java='unused-java', runtime_installer=_fake_forge_runtime)
            apply_test_result_to_pack(output, ['keep.jar'], started=True)
            with zipfile.ZipFile(output) as archive:
                self.assertNotIn('server/mods/keep.jar', archive.namelist())
                report = json.loads(archive.read('amcl-build-report.json'))
                manifest = json.loads(archive.read('amcl-server-pack.json'))
                self.assertEqual(report['verification']['level'], 'startup-tested')
                self.assertEqual(report['mods'][0]['action'], 'excluded')
                self.assertFalse(any(row['path'] == 'server/mods/keep.jar'
                                     for row in manifest['files']))
            self.assertEqual(inspect_archive(output)['kind'], 'server')

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
