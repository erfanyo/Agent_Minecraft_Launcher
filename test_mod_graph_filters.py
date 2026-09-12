import unittest

from PySide6.QtWidgets import QApplication

import mod_deps as md
from mod_graph import ModDependencyGraphDialog


class ModGraphFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_optional_dependencies_are_hidden_by_default(self):
        graph = md.ModGraph()
        graph.add_node(md.ModNode('main', name='Main'))
        graph.ensure_missing('required-lib')
        graph.ensure_optional('optional-addon')
        graph.add_node(md.ModNode('conflict-mod', name='Installed Conflict'))
        graph.add_edge('main', 'required-lib', md.REQUIRED)
        graph.add_edge('main', 'optional-addon', md.OPTIONAL)
        graph.add_edge('main', 'conflict-mod', md.INCOMPATIBLE)

        dialog = ModDependencyGraphDialog('demo', graph)
        self.addCleanup(dialog.close)
        edges = {edge_type: item for _source, _target, edge_type, item in dialog._edge_items}

        self.assertFalse(dialog.show_optional.isChecked())
        self.assertTrue(edges[md.REQUIRED].isVisible())
        self.assertTrue(edges[md.INCOMPATIBLE].isVisible())
        self.assertFalse(edges[md.OPTIONAL].isVisible())
        self.assertFalse(dialog._items['optional-addon'].isVisible())
        self.assertTrue(dialog._items['required-lib'].isVisible())
        self.assertIn('2 条依赖关系', dialog.overview.text())

        dialog.show_optional.setChecked(True)
        self.assertTrue(edges[md.OPTIONAL].isVisible())
        self.assertTrue(dialog._items['optional-addon'].isVisible())
        self.assertIn('3 条依赖关系', dialog.overview.text())

    def test_installed_optional_target_remains_visible(self):
        graph = md.ModGraph()
        graph.add_node(md.ModNode('main', name='Main'))
        graph.add_node(md.ModNode('installed-addon', name='Installed Addon'))
        graph.add_edge('main', 'installed-addon', md.OPTIONAL)

        dialog = ModDependencyGraphDialog('demo', graph)
        self.addCleanup(dialog.close)
        self.assertTrue(dialog._items['installed-addon'].isVisible())
        self.assertFalse(dialog._edge_items[0][3].isVisible())


if __name__ == '__main__':
    unittest.main()
