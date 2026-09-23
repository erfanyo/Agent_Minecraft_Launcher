import tempfile
import unittest
import zipfile
import json
from pathlib import Path
from unittest.mock import ANY, patch
from server_launch import build_launch_plan, eula_accepted
from server_service import select_server_java


class ServerLaunchTests(unittest.TestCase):
    def test_server_java_uses_managed_preference_without_dialog(self):
        with tempfile.TemporaryDirectory() as root:
            java = Path(root, 'java.exe')
            java.write_bytes(b'java')
            with patch('java_manager.java_version_probe', return_value=(17, '')), \
                    patch('java_manager.ensure_java') as ensure:
                selected, result = select_server_java(
                    {'minecraftVersion': '1.19.2', 'requiredJava': 17}, {},
                    {'java_paths': {'17': str(java)}}, root)
            self.assertEqual(selected, str(java))
            self.assertEqual(result, (17, ''))
            ensure.assert_not_called()

    def test_server_java_auto_selects_exact_legacy_range(self):
        with tempfile.TemporaryDirectory() as root, \
                patch('java_manager.ensure_java', return_value='managed-java') as ensure, \
                patch('java_manager.java_version_probe', return_value=(8, '')):
            selected, result = select_server_java(
                {'minecraftVersion': '1.16.5', 'requiredJava': 8}, {}, {}, root)
            self.assertEqual((selected, result), ('managed-java', (8, '')))
            ensure.assert_called_once_with(
                root, 8, progress_callback=None, status_callback=ANY,
                max_major=8, prefer_managed=True)

    def test_mod_environment(self):
        from mod_deps import read_mod_metadata
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, 'mod.jar')
            for side, expected in [('client', 'client'), ('server', 'server'), ('*', 'both')]:
                with zipfile.ZipFile(path, 'w') as archive:
                    archive.writestr('fabric.mod.json', json.dumps({'id': 'test', 'environment': side}))
                self.assertEqual(read_mod_metadata(str(path))['environment'], expected)
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('META-INF/mods.toml', '[[mods]]\nmodId="test"\n[[dependencies.test]]\nmodId="minecraft"\nside="CLIENT"')
            self.assertEqual(read_mod_metadata(str(path))['environment'], 'unknown')

    def test_neoforge(self):
        with tempfile.TemporaryDirectory() as root:
            args = Path(root, 'libraries/net/neoforged/neoforge/21.1.100/unix_args.txt')
            args.parent.mkdir(parents=True)
            args.write_text('net.neoforged.fml.startup.Server', encoding='utf-8')
            plan = build_launch_plan(root, 'linux')
            self.assertEqual(plan['loader'], 'neoforge')
            self.assertEqual(plan['requiredJava'], 21)

    def fixture(self, root, extra=''):
        root = Path(root)
        jar = root / 'libraries/test/lib.jar'
        jar.parent.mkdir(parents=True)
        jar.write_bytes(b'test')
        args = root / 'libraries/net/minecraftforge/forge/1.19.2-43.3.8/win_args.txt'
        args.parent.mkdir(parents=True)
        args.write_text('-p libraries/test/lib.jar\n' + extra + '\n'
            'cpw.mods.bootstraplauncher.BootstrapLauncher\n--launchTarget forgeserver\n'
            '--fml.mcVersion 1.19.2', encoding='utf-8')
        return args

    @staticmethod
    def executable_jar(path, main='com.example.ServerMain'):
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('META-INF/MANIFEST.MF',
                             f'Manifest-Version: 1.0\nMain-Class: {main}\n')

    def test_single_executable_root_jar_is_automatic(self):
        with tempfile.TemporaryDirectory() as root:
            self.executable_jar(Path(root, 'paper-1.20.1.jar'))
            plan = build_launch_plan(root, 'windows')
            self.assertEqual(plan['entry'], 'paper-1.20.1.jar')
            self.assertEqual(plan['arguments'], ['-jar', 'paper-1.20.1.jar', 'nogui'])

    def test_ambiguous_root_jars_require_one_manual_choice(self):
        with tempfile.TemporaryDirectory() as root:
            self.executable_jar(Path(root, 'paper.jar'))
            self.executable_jar(Path(root, 'purpur.jar'))
            with self.assertRaisesRegex(ValueError, '多个可启动 JAR'):
                build_launch_plan(root, 'windows')

    def test_forge_plan_and_missing_library(self):
        with tempfile.TemporaryDirectory() as root:
            self.fixture(root)
            plan = build_launch_plan(root, 'windows')
            self.assertEqual(plan['requiredJava'], 17)
            self.assertEqual(plan['arguments'][-1], 'nogui')
            self.assertFalse(any(x.startswith('@') for x in plan['arguments']))
            Path(root, 'libraries/test/lib.jar').unlink()
            with self.assertRaises(ValueError):
                build_launch_plan(root, 'windows')

    def test_standard_java_network_preferences(self):
        with tempfile.TemporaryDirectory() as root:
            self.fixture(root, '-Djava.net.preferIPv6Addresses=system\n-Djava.net.preferIPv4Stack=false')
            plan = build_launch_plan(root, 'windows')
            self.assertIn('-Djava.net.preferIPv6Addresses=system', plan['arguments'])
            self.assertIn('-Djava.net.preferIPv4Stack=false', plan['arguments'])

        for extra in ('-Djava.net.preferIPv6Addresses=maybe',
                      '-Djava.net.preferIPv4Stack=system'):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as root:
                self.fixture(root, extra)
                with self.assertRaises(ValueError):
                    build_launch_plan(root, 'windows')

    def test_reject_dangerous_arguments(self):
        for extra in ('@evil.txt', '-javaagent:evil.jar', '-XX:OnError=evil', '-Djava.library.path=../x'):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as root:
                self.fixture(root, extra)
                with self.assertRaises(ValueError):
                    build_launch_plan(root, 'windows')

    def test_wrong_platform_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            self.fixture(root)
            Path(root, 'server.jar').write_bytes(b'vanilla')
            with self.assertRaises(ValueError):
                build_launch_plan(root, 'linux')

    def test_explicit_server_jar_stays_inside_server(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'custom-server.jar').write_bytes(b'jar')
            plan = build_launch_plan(root, 'windows', 'custom-server.jar')
            self.assertEqual(plan['entry'], 'custom-server.jar')
            self.assertEqual(plan['arguments'], ['-jar', 'custom-server.jar', 'nogui'])
            outside = Path(root).parent / 'outside-server.jar'
            outside.write_bytes(b'jar')
            try:
                with self.assertRaises(ValueError):
                    build_launch_plan(root, 'windows', outside)
            finally:
                outside.unlink(missing_ok=True)

    def test_eula_last_value_and_whitespace(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, 'eula.txt')
            path.write_text('# eula=true\neula = true\n', encoding='utf-8')
            self.assertTrue(eula_accepted(root))
            path.write_text('eula=true\neula=false', encoding='utf-8')
            self.assertFalse(eula_accepted(root))
