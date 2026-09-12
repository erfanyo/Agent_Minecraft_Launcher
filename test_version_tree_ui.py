import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QStyleOptionViewItem, QTreeWidget

from download_tab import DownloadTab
from version_tree import VersionTreeDelegate, fill_version_tree


class VersionTreeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_major_versions_are_large_spanning_cards(self):
        tree = QTreeWidget()
        manifest = {
            "versions": [
                {"id": "1.21.4", "type": "release",
                 "releaseTime": "2024-12-03T00:00:00+00:00"},
                {"id": "1.21.1", "type": "release",
                 "releaseTime": "2024-08-08T00:00:00+00:00"},
            ]
        }

        fill_version_tree(tree, manifest)
        root = tree.topLevelItem(0)

        self.assertEqual(root.text(0), "1.21.xx")
        self.assertFalse(root.isExpanded())
        self.assertTrue(root.isFirstColumnSpanned())
        self.assertIsInstance(tree.itemDelegate(), VersionTreeDelegate)
        index = tree.indexFromItem(root)
        root_height = tree.itemDelegate().sizeHint(QStyleOptionViewItem(), index).height()
        leaf_height = tree.itemDelegate().sizeHint(
            QStyleOptionViewItem(), tree.indexFromItem(root.child(0))).height()
        self.assertGreaterEqual(root_height, 42)
        self.assertGreaterEqual(leaf_height, 34)

    def test_download_version_list_hides_repeated_header(self):
        tab = DownloadTab(auto_load_versions=False)
        self.assertTrue(tab.version_tree.isHeaderHidden())


if __name__ == "__main__":
    unittest.main()
