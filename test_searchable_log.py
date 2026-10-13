"""Server console search stays usable while its document changes."""
import os
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import QApplication
from searchable_log import SearchableLogView


class SearchableLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = SearchableLogView()
        self.addCleanup(self.view.deleteLater)
        self.addCleanup(self.view.search_bar.deleteLater)

    def wait_for_search(self):
        deadline = time.monotonic() + 3
        while self.view._refresh_timer.isActive() or self.view._scanning:
            self.app.processEvents()
            if time.monotonic() > deadline:
                self.fail('Search did not complete')
            time.sleep(.002)

    def search(self, query):
        self.view._input.setText(query)
        self.wait_for_search()

    def test_case_insensitive_navigation_and_clear(self):
        self.view.setPlainText('ERROR first\nerror second')
        self.search('error')
        self.assertEqual(self.view._count.text(), '1 / 2')
        self.view._next.click()
        self.assertEqual(self.view._count.text(), '2 / 2')
        self.view._next.click()
        self.assertEqual(self.view._count.text(), '1 / 2')
        self.view._close.click()
        self.assertFalse(self.view.search_active)
        self.assertEqual(self.view.extraSelections(), [])
        self.assertFalse(self.view._previous.isEnabled())

    def test_new_matches_never_show_zero_of_total(self):
        self.search('error')
        self.assertEqual(self.view._count.text(), '无匹配')
        self.view.appendPlainText('error new')
        self.wait_for_search()
        self.assertEqual(self.view._count.text(), '1 / 1')

    def test_trimming_preserves_selected_match(self):
        self.view.setMaximumBlockCount(3)
        self.view.setPlainText('error first\nerror second\nerror third')
        self.search('error')
        self.view._next.click()
        self.view.appendPlainText('tail')
        self.wait_for_search()
        match = self.view._matches[self.view._current]
        self.assertEqual(match.block().text(), 'error second')
        self.assertEqual(self.view._count.text(), '1 / 2')

    def test_many_matches_bound_highlights_but_keep_all_results(self):
        self.view.setPlainText('\n'.join(['error'] * 2200))
        self.search('error')
        self.assertEqual(len(self.view._matches), 2200)
        self.assertLessEqual(len(self.view.extraSelections()), 1001)
        self.view._previous.click()
        self.assertEqual(self.view._count.text(), '2200 / 2200')

    def test_query_change_cancels_stale_batches(self):
        self.view.setPlainText('error ' * 2200 + 'warning')
        self.view._input.setText('error')
        self.view._refresh_timer.stop()
        self.view._scan()
        self.view._input.setText('warning')
        self.wait_for_search()
        self.assertEqual(self.view._count.text(), '1 / 1')
        self.assertEqual(self.view._matches[0].selectedText(), 'warning')

    def test_no_shortcuts_and_search_bar_stays_visible(self):
        self.view.search_bar.show()
        self.assertEqual(self.view.findChildren(QShortcut), [])
        self.assertFalse(self.view.search_bar.isHidden())
        self.view._close.click()
        self.assertFalse(self.view.search_bar.isHidden())
