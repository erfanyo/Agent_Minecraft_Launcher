import importlib.util
from pathlib import Path
import tempfile
import unittest


@unittest.skipUnless(importlib.util.find_spec('nbtlib'), 'Optional requirements-bridge-test.txt needed')
class BridgeWorldTests(unittest.TestCase):
    def test_copy_resets_weather_and_permissions_without_changing_source(self):
        import nbtlib as n
        from tools.bridge_weather_game import prepare_world
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            source=root/'source'
            source.mkdir()
            n.File({'Data':n.Compound({'allowCommands':n.Byte(1), 'raining':n.Byte(1),
                'thundering':n.Byte(1), 'GameRules':n.Compound({})})},gzipped=True).save(source/'level.dat')
            (source/'session.lock').write_bytes(b'locked')
            original=(source/'level.dat').read_bytes()
            prepare_world(source,root/'copy',False)
            data=n.load(root/'copy/level.dat')['Data']
            self.assertFalse(data['allowCommands'])
            self.assertFalse(data['raining'])
            self.assertFalse(data['thundering'])
            self.assertEqual(str(data['GameRules']['doWeatherCycle']),'false')
            self.assertFalse((root/'copy/session.lock').exists())
            self.assertEqual(original,(source/'level.dat').read_bytes())

    def test_protected_instance_is_rejected_before_launch(self):
        from tools.bridge_weather_game import test_game
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'地下酒吧'
            source.mkdir()
            with self.assertRaisesRegex(ValueError,'excluded'):
                test_game(source,'world',Path('missing.jar'))

    def test_protected_template_is_rejected_before_launch(self):
        from tools.bridge_weather_game import test_game
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'safe'
            protected=Path(temporary)/'地下酒吧'/'world'
            source.mkdir()
            protected.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError,'excluded'):
                test_game(source,'world',Path('missing.jar'),world_source=protected)
