import json
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import mod_deps as md


class ModDependencyClassificationTests(unittest.TestCase):
    def test_optional_and_absent_conflicts_are_not_missing_dependencies(self):
        with tempfile.TemporaryDirectory() as root:
            metadata = {
                'id': 'iris', 'name': 'Iris', 'version': 'test',
                'depends': {'minecraft': '1.21.1', 'sodium': '>=0.6'},
                'recommends': {'rei': '*'},
                'suggests': {'modmenu': '*'},
                'breaks': {'embeddium': '*', 'optifabric': '*'},
            }
            with zipfile.ZipFile(Path(root, 'iris.jar'), 'w') as archive:
                archive.writestr('fabric.mod.json', json.dumps(metadata))
            graph = md.build_graph(root)

        self.assertEqual([edge.target for edge in graph.missing_deps()], ['sodium'])
        self.assertTrue(graph.nodes['sodium'].missing)
        self.assertTrue(graph.nodes['modmenu'].placeholder)
        self.assertFalse(graph.nodes['modmenu'].missing)
        self.assertTrue(graph.nodes['rei'].placeholder)
        self.assertFalse(graph.nodes['rei'].missing)
        self.assertNotIn('embeddium', graph.nodes)
        self.assertNotIn('optifabric', graph.nodes)
        self.assertEqual(graph.stats(), {'mods': 1, 'embedded': 0, 'missing': 1, 'edges': 5})

    def test_legacy_forge_mandatory_false_is_optional(self):
        metadata = '''modLoader="javafml"
[[mods]]
modId="example"
displayName="Example"
[[dependencies.example]]
modId="requiredlib"
mandatory=true
[[dependencies.example]]
modId="optionaladdon"
mandatory=false
'''
        with tempfile.TemporaryDirectory() as root:
            with zipfile.ZipFile(Path(root, 'example.jar'), 'w') as archive:
                archive.writestr('META-INF/mods.toml', metadata)
            graph = md.build_graph(root)

        types = {edge.target: edge.type for edge in graph.edges}
        self.assertEqual(types['requiredlib'], md.REQUIRED)
        self.assertEqual(types['optionaladdon'], md.OPTIONAL)
        self.assertTrue(graph.nodes['requiredlib'].missing)
        self.assertFalse(graph.nodes['optionaladdon'].missing)

    def test_installed_conflict_gets_a_conflict_edge_without_being_missing(self):
        with tempfile.TemporaryDirectory() as root:
            for name, metadata in [
                    ('iris.jar', {'id': 'iris', 'breaks': {'embeddium': '*'}}),
                    ('embeddium.jar', {'id': 'embeddium'})]:
                with zipfile.ZipFile(Path(root, name), 'w') as archive:
                    archive.writestr('fabric.mod.json', json.dumps(metadata))
            graph = md.build_graph(root)

        self.assertIn('embeddium', graph.nodes)
        self.assertFalse(graph.nodes['embeddium'].missing)
        self.assertEqual(graph.edges[0].type, md.INCOMPATIBLE)
        self.assertEqual(graph.missing_deps(), [])

    def test_disabled_mod_does_not_create_active_missing_dependencies(self):
        with tempfile.TemporaryDirectory() as root:
            metadata = {'id': 'disabledmod', 'depends': {'absentlib': '*'}}
            with zipfile.ZipFile(Path(root, 'disabled.jar.disabled'), 'w') as archive:
                archive.writestr('fabric.mod.json', json.dumps(metadata))
            graph = md.build_graph(root)

        self.assertIn('disabledmod', graph.nodes)
        self.assertFalse(graph.nodes['disabledmod'].enabled)
        self.assertNotIn('absentlib', graph.nodes)
        self.assertEqual(graph.edges, [])
        self.assertEqual(graph.missing_deps(), [])

    def test_nested_jar_satisfies_required_dependency(self):
        inner_bytes = io.BytesIO()
        with zipfile.ZipFile(inner_bytes, 'w') as inner:
            inner.writestr('META-INF/neoforge.mods.toml', '''modLoader="javafml"
[[mods]]
modId="flywheel"
displayName="Flywheel"
version="1.0.6"
''')
        outer_meta = '''modLoader="javafml"
[[mods]]
modId="create"
displayName="Create"
[[dependencies.create]]
modId="flywheel"
type="required"
versionRange="[1.0.0,2.0)"
'''
        with tempfile.TemporaryDirectory() as root:
            with zipfile.ZipFile(Path(root, 'create.jar'), 'w') as outer:
                outer.writestr('META-INF/neoforge.mods.toml', outer_meta)
                outer.writestr('META-INF/jarjar/flywheel.jar', inner_bytes.getvalue())
            graph = md.build_graph(root)

        self.assertIn('flywheel', graph.nodes)
        self.assertFalse(graph.nodes['flywheel'].placeholder)
        self.assertIn('create.jar!META-INF/jarjar/flywheel.jar', graph.nodes['flywheel'].file)
        self.assertEqual(graph.missing_deps(), [])
        self.assertEqual(graph.stats()['mods'], 1)
        self.assertEqual(graph.stats()['embedded'], 1)


if __name__ == '__main__':
    unittest.main()
