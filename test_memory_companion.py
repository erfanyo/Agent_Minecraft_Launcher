"""Companion positioning and visibility must never resize the main window."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QRect, QEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QPushButton, QDockWidget

import memory_launch_card as memory
from ui_anim import set_animations_enabled


class MemoryCompanionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        set_animations_enabled(False)

    def setUp(self):
        self.owner = QMainWindow()
        self.owner.screen = lambda: SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1400, 1000))
        self.owner.setGeometry(100, 100, 700, 400)
        self.owner.show()
        self.app.processEvents()
        self.panel = memory.MemoryCompanion(self.owner)
        self.panel.setWidget(QLabel('内存摘要'))

    def tearDown(self):
        self.panel.hide()
        self.panel.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.owner.close()
        self.owner.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_attached_window_preserves_owner_and_follows_movement(self):
        before = self.owner.geometry()
        self.panel.sync_attachment()
        self.assertTrue(self.panel.isWindow())
        self.assertTrue(self.panel.isVisible())
        self.assertEqual(self.owner.geometry(), before)
        self.assertEqual(self.panel.y(), self.owner.frameGeometry().bottom() + 6)
        self.owner.move(200, 150)
        self.app.processEvents()
        self.assertEqual(self.panel.y(), self.owner.frameGeometry().bottom() + 6)
        self.assertEqual(self.panel.x(), self.owner.frameGeometry().left())

    def test_insufficient_space_requires_explicit_reopen(self):
        self.owner.move(100, 850)
        self.panel.sync_attachment()
        self.app.processEvents()
        self.assertFalse(self.panel.isVisible())
        self.assertTrue(self.panel.status_button.isVisible())
        self.panel.reopen()
        self.assertTrue(self.panel.isVisible())
        self.assertTrue(self.panel.detached)
        self.assertTrue(QRect(0, 0, 1400, 1000).contains(self.panel.geometry()))
        self.panel.move(20, 20)
        self.panel.sync_attachment()
        self.assertEqual(self.panel.pos().x(), 20)

    def test_user_collapse_and_minimize_keep_reopen_available(self):
        self.panel.sync_attachment()
        self.panel.collapse()
        self.panel.sync_attachment()
        self.assertFalse(self.panel.isVisible())
        self.panel.reopen()
        self.assertTrue(self.panel.isVisible())
        self.owner.showMinimized()
        self.app.processEvents()
        self.assertFalse(self.panel.isVisible())
        self.owner.showNormal()
        self.app.processEvents()
        self.assertTrue(self.panel.isVisible())

    def test_wayland_requires_user_to_open_independent_window(self):
        with patch.object(QApplication, 'platformName', return_value='wayland'):
            self.panel.sync_attachment()
            self.assertFalse(self.panel.isVisible())
            self.panel.reopen()
            self.assertTrue(self.panel.isVisible())
            self.assertTrue(self.panel.detached)

    def test_advice_launches_without_dock_and_hides_inactive_ai(self):
        self.panel.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.owner.ai_dock = SimpleNamespace(_local_engine=None)
        plan = SimpleNamespace(command=['-Xmx8G'], instance_id='test', game_dir='.')
        calls = []
        with patch('settings.load_settings', return_value={}), \
                patch.object(memory, 'snapshot', return_value=(16 * memory.GIB, memory.GIB)), \
                patch.object(memory, 'automatic_budget', return_value={'gb': 4, 'desired_gb': 8}), \
                patch.object(memory, 'history_peak', return_value=0), \
                patch.object(memory, 'enabled_mod_count', return_value=0), \
                patch.object(memory, 'pressure', return_value=2):
            self.assertTrue(memory.offer_memory_actions(self.owner, plan, {}, lambda *args: calls.append(args)))
            self.panel = self.owner._memory_launch_card
            self.app.processEvents()
            self.assertEqual(len(calls), 1)
            self.assertFalse(self.owner.findChildren(QDockWidget))
            stop_ai = next(b for b in self.panel.findChildren(QPushButton) if b.text() == '关闭本地 AI')
            self.assertTrue(stop_ai.isHidden())
            self.assertTrue(any('游戏实际占用' in l.text() for l in self.panel.findChildren(QLabel)))
            refresh = next(b for b in self.panel.findChildren(QPushButton) if b.text() == '重新检测')
            self.owner.game_process = SimpleNamespace(pid=os.getpid(), poll=lambda: None)
            memory.pressure.return_value = 0
            with patch.object(memory.time, 'monotonic', return_value=10) as clock:
                refresh.click()
                clock.return_value = 41
                refresh.click()
            self.assertTrue(self.panel.collapsed)
            self.panel.reopen()
            refresh.click()
            self.assertTrue(self.panel.isVisible(), 'manual reopen must override stable auto-collapse')
            self.owner.game_process.poll = lambda: 0
            refresh.click()
            self.assertTrue(self.panel.collapsed)
            self.panel.reopen()
            refresh.click()
            self.assertTrue(self.panel.isVisible(), 'ended-game details must remain reviewable')


if __name__ == '__main__':
    unittest.main()
