"""First-game walkthrough targets match the current version picker."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from download_tab import DownloadTab
from guide_overlay import GuideDriver, GuideOverlay
from tutorial_steps import first_game_steps


def _release(version, month):
    return {'id': version, 'type': 'release',
            'releaseTime': f'{month}-01T00:00:00+00:00'}


class TutorialStepsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tab = DownloadTab(auto_load_versions=False)
        self.tab._refresh_loader_cards = lambda: None
        self.tab._fill_tree({'versions': [
            _release('1.22.2', '2026-03'),
            _release('1.22.1', '2026-02'),
            _release('1.21.9', '2025-08'),
            _release('1.21.1', '2024-08'),
        ]})
        self.tab.resize(900, 600)
        self.tab.show()
        self.app.processEvents()

    def tearDown(self):
        self.tab.close()

    def test_major_row_chooses_gold_or_latest_release(self):
        tree = self.tab.version_tree
        self.assertEqual(tree.topLevelItem(1).data(0, 0x0100)['recommended'], '1.21.1')
        tree.setCurrentItem(tree.topLevelItem(1))
        self.assertEqual(self.tab.mc, '1.21.1')
        self.tab.menu.setCurrentRow(0)
        tree.setCurrentItem(tree.topLevelItem(0))
        self.assertEqual(self.tab.mc, '1.22.2')

    def test_spotlight_can_focus_golden_leaf_without_selecting_it(self):
        host = QWidget()
        driver = GuideDriver(host, [])
        tree = self.tab.version_tree
        self.assertEqual(self.tab.mc, '')
        group = driver._focus_rect({'focus_tree_item': '1.21.xx'}, tree)
        leaf = driver._focus_rect({'focus_tree_item': '1.21.1'}, tree)
        self.assertGreater(group.height(), 0)
        self.assertGreater(leaf.height(), 0)
        self.assertNotEqual(group.top(), leaf.top())
        self.assertEqual(self.tab.mc, '')
        host.close()

    def test_walkthrough_uses_current_entry_and_no_automatic_install(self):
        steps = first_game_steps()
        self.assertEqual(len(steps), 9)
        self.assertEqual(steps[0]['focus_main_tab'], '下载新资源')
        self.assertEqual(steps[2]['focus_tree_item'], '1.21.xx')
        self.assertEqual(steps[3]['focus_tree_item'], '1.21.1')
        self.assertIn('最新正式版', steps[2]['text'])
        self.assertIn('不会替你下载', steps[5]['text'])
        self.assertIn('启动游戏', steps[-1]['text'])

    def test_overlay_and_spotlight_share_host_local_coordinates(self):
        host = QWidget()
        host.setGeometry(210, 130, 700, 480)
        target = QLabel('目标', host)
        target.setGeometry(37, 59, 110, 32)
        host.show()
        self.app.processEvents()
        overlay = GuideOverlay(host)
        self.assertIs(overlay.parentWidget(), host)
        self.assertEqual(overlay.geometry(), host.rect())
        rect = GuideDriver(host, [])._focus_rect({}, target)
        self.assertEqual((rect.x(), rect.y()), (37, 59))
        overlay.show_step(rect, 'below', '测试', True, True)
        self.assertEqual(overlay._target_rect, rect)
        host.close()


if __name__ == '__main__':
    unittest.main()
