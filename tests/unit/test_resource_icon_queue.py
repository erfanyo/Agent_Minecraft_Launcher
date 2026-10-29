import collections
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem
from launcher_app.ui.resource_center import ResourceBrowser


class BrowserHarness:
    _enqueue_visible_icons = ResourceBrowser._enqueue_visible_icons
    _pump_icon_queue = ResourceBrowser._pump_icon_queue
    _end_icon = ResourceBrowser._end_icon

    def __init__(self, source='curseforge'):
        self.result_list = QListWidget()
        self._icon_queue = collections.deque()
        self._icon_loaded = {}
        self._icon_active = 0
        self._icon_concurrency = 4
        self._icon_generation = 0
        self.visible = list(range(8))
        self.jobs = []
        for i in range(12):
            item = QListWidgetItem(str(i), self.result_list)
            item.setData(Qt.ItemDataRole.UserRole, {
                'slug': str(i), 'icon_url': f'https://example.com/{i}', 'source': source})

    def _visible_rows(self):
        return self.visible

    def _async(self, key, worker, callback, cache):
        self.jobs.append((worker, callback))


class IconQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_both_sources_limit_concurrency_and_bind_each_request(self):
        for source in ('curseforge', 'modrinth'):
            with self.subTest(source=source):
                browser = BrowserHarness(source)
                browser._enqueue_visible_icons()
                browser._enqueue_visible_icons()
                self.assertEqual(browser._icon_active, 4)
                self.assertEqual(len(browser.jobs), 4)
                if source == 'curseforge':
                    with patch('requests.get') as get:
                        get.return_value.status_code = 200
                        get.return_value.content = b'image'
                        for worker, _ in browser.jobs:
                            self.assertEqual(worker(), b'image')
                        self.assertEqual([c.args[0] for c in get.call_args_list],
                                         [f'https://example.com/{i}' for i in range(4)])
                else:
                    with patch('launcher_app.ui.image_cache.load_icon') as load:
                        for worker, _ in browser.jobs:
                            worker()
                        self.assertEqual([c.args[0] for c in load.call_args_list],
                                         ['0', '1', '2', '3'])
                browser.jobs[0][1](None)
                self.assertEqual(browser._icon_active, 4)
                self.assertEqual(len(browser.jobs), 5)

    def test_scroll_discards_waiting_rows_and_allows_return(self):
        browser = BrowserHarness()
        browser._enqueue_visible_icons()
        browser.visible = [8, 9, 10, 11]
        browser._enqueue_visible_icons()
        browser.jobs[0][1](None)
        self.assertIn(8, browser._icon_loaded)
        self.assertNotIn(4, browser._icon_loaded)
        browser.visible = [4, 5, 6, 7]
        browser._enqueue_visible_icons()
        browser.jobs[1][1](None)
        self.assertIn(4, browser._icon_loaded)

    def test_old_search_completion_releases_slot_without_using_deleted_item(self):
        browser = BrowserHarness()
        browser._enqueue_visible_icons()
        old_callback = browser.jobs[0][1]
        browser._icon_generation += 1
        browser.result_list.clear()
        browser._icon_loaded.clear()
        browser._icon_queue.clear()
        browser.visible = []
        old_callback(b'not-an-image')
        self.assertEqual(browser._icon_active, 3)


if __name__ == '__main__':
    unittest.main()
