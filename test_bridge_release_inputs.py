from pathlib import Path
import tempfile
import unittest
import zipfile
from tools import fetch_bridge_mod_jars as bridge


class BridgeReleaseInputsTests(unittest.TestCase):
    def test_all_eight_pinned_artifacts_are_valid(self):
        self.assertEqual(bridge.MANIFEST['version'],'0.2.0')
        self.assertEqual(len(bridge.ARTIFACTS),8)
        self.assertEqual(bridge.verify_bundle(bridge.PREBUILT),[])

    def test_corruption_is_detected_and_repaired(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination=Path(temporary)
            bridge.stage_bundle(destination)
            path=destination/bridge.ARTIFACTS[0]['file']
            path.write_bytes(b'corrupted')
            self.assertTrue(bridge.verify_bundle(destination))
            bridge.stage_bundle(destination)
            self.assertEqual(bridge.verify_bundle(destination),[])

    def test_extra_legacy_jar_prevents_packaging(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination=Path(temporary)
            bridge.stage_bundle(destination)
            (destination/'agentmc-bridge-fabric-1.21.1-0.1.0.jar').write_bytes(b'old')
            with self.assertRaisesRegex(ValueError,'清单外'):
                bridge.stage_bundle(destination)

    def test_legacy_mod_annotation_has_real_version(self):
        path=bridge.PREBUILT/'agentmc-bridge-forge-1.12.2-0.2.0.jar'
        with zipfile.ZipFile(path) as archive:
            data=archive.read('com/agentmc/bridge/forge1122/BridgeForge1122.class')
        self.assertNotIn(b'@VERSION@',data)
        self.assertIn(b'0.2.0',data)
