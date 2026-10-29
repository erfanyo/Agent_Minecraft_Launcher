from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from launcher_app.instances.launcher import build_launch_command


class LegacyLaunchArgumentTests(unittest.TestCase):
    def test_paths_and_names_with_spaces_remain_single_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'Minecraft Test'
            profile={'id':'1.12.2','mainClass':'net.minecraft.launchwrapper.Launch',
                'libraries':[], 'minecraftArguments':'--username ${auth_player_name} --gameDir ${game_directory} --assetsDir ${assets_root} --note "two words"'}
            with patch('launcher_app.instances.launcher._extract_natives'), patch('launcher_app.instances.launcher._resolve_logging',return_value=[]):
                command=build_launch_command(profile,str(root),'java.exe',username='Test Player',install_dir=str(root),assets_dir=str(root/'assets cache'))
            for key,value in [('--username','Test Player'),('--gameDir',str(root)),('--assetsDir',str(root/'assets cache')),('--note','two words')]:
                self.assertEqual(command[command.index(key)+1],value)
