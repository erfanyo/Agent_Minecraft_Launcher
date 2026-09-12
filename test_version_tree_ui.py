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

    def test_loader_network_failure_keeps_card_available_for_retry(self):
        tab = DownloadTab(auto_load_versions=False)
        tab.mc = "1.21.1"
        key, card, _arrow, _combo = next(
            row for row in tab.loader_rows if row[0] == "neoforge")
        tab._loader_checking.add((key, tab.mc))

        tab._on_loader_availability_error(key, card, tab.mc, "offline")

        self.assertTrue(card.isEnabled())
        self.assertFalse(card.isHidden())
        self.assertFalse((key, tab.mc) in tab._loader_checking)
        self.assertNotIn(key, tab.loader_available)

    def test_stale_loader_result_does_not_overwrite_new_minecraft_version(self):
        tab = DownloadTab(auto_load_versions=False)
        tab.mc = "1.21.4"
        key, card, _arrow, _combo = next(
            row for row in tab.loader_rows if row[0] == "neoforge")

        tab._on_loader_availability(key, ["21.1.250"], card, "1.21.1")

        self.assertNotIn(key, tab.loader_available)


if __name__ == "__main__":
    unittest.main()
