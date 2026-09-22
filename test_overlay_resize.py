# -*- coding: utf-8 -*-
"""覆盖层跟随父控件尺寸单测。

回归:覆盖层原先只在 ``show_overlay()`` 里 ``setGeometry(parent.rect())``,显示
期间用户拉大窗口时它仍是旧尺寸,内容就缩在左上角一块。这里锁定「父一改尺寸,
覆盖层跟着改」,并确保没有漏掉父控件的 resize 事件监听。
"""
import unittest

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

_app = QApplication.instance() or QApplication([])

from ui_overlay import ContentOverlay


class OverlayResizeTests(unittest.TestCase):
    def setUp(self):
        self.host = QWidget()
        self.host.resize(800, 600)
        self.host.show()
        self.overlay = ContentOverlay(self.host)
        self.overlay.set_title('测试')
        self.overlay.set_content(QLabel('内容'))
        self.addCleanup(self._teardown)

    def _teardown(self):
        try:
            self.overlay.hide_overlay()
            self.host.close()
            self.host.deleteLater()
            QApplication.processEvents()
        except RuntimeError:
            pass

    def test_covers_parent_when_shown(self):
        self.overlay.show_overlay()
        QApplication.processEvents()
        self.assertEqual(self.overlay.size(), self.host.size())

    def test_follows_parent_grow_while_visible(self):
        """核心回归:显示期间拉大窗口,覆盖层必须跟着变大。"""
        self.overlay.show_overlay()
        QApplication.processEvents()
        self.host.resize(1200, 900)
        QApplication.processEvents()
        self.assertEqual(self.overlay.size(), self.host.size())
        self.assertEqual(self.overlay.width(), 1200)
        self.assertEqual(self.overlay.height(), 900)

    def test_follows_parent_shrink_while_visible(self):
        self.overlay.show_overlay()
        QApplication.processEvents()
        self.host.resize(500, 400)
        QApplication.processEvents()
        self.assertEqual(self.overlay.size(), self.host.size())

    def test_not_stuck_at_top_left_corner(self):
        """不能只覆盖左上角一小块(原 bug 的表现)。"""
        self.overlay.show_overlay()
        QApplication.processEvents()
        self.host.resize(1300, 1000)
        QApplication.processEvents()
        self.assertEqual(self.overlay.geometry(), self.host.rect())

    def test_event_filter_removed_after_hide(self):
        """隐藏后要摘掉事件过滤器,避免父控件继续回调已关闭的覆盖层。"""
        self.overlay.show_overlay()
        QApplication.processEvents()
        self.overlay.hide_overlay()
        QApplication.processEvents()
        self.assertIsNone(self.overlay._watched_parent)
        # 父控件再改尺寸不应报错
        self.host.resize(700, 500)
        QApplication.processEvents()

    def test_can_reopen_after_hide(self):
        self.overlay.show_overlay()
        self.overlay.hide_overlay()
        self.overlay.show_overlay()
        QApplication.processEvents()
        self.host.resize(1100, 800)
        QApplication.processEvents()
        self.assertEqual(self.overlay.size(), self.host.size())


if __name__ == '__main__':
    unittest.main()
