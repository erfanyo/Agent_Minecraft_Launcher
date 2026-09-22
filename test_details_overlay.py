# -*- coding: utf-8 -*-
"""详情「覆盖层 + 返回」单测(与「下载详情」同一套交互)。

历史:详情曾经是与「设置」平级的常驻标签页,两个详情页同时存在、只切可见性,
于是出现过「在服务端里看到客户端详情」的困惑。现在改成覆盖层:点开→看→返回,
同一时刻只有一个详情页,也不占常驻标签位。

**为什么这样写**:构造一次 MainWindow 要十几秒,每个用例都造会拖成一分多钟。
覆盖层逻辑只依赖「一个主标签容器 + 一个覆盖层 + 两个详情控件」,所以这里用轻量
宿主 ``_Host`` 承载**真实的** ``MainWindow`` 方法(``types.MethodType``),跑的是
生产代码但不付主窗口的构造代价;另留一条真实 MainWindow 用例覆盖集成行为。
"""
import types
import unittest

from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

_app = QApplication.instance() or QApplication([])

from i18n import t
from main import MainWindow


class _StubContent(QWidget):
    """替代真实详情控件:只记录被要求展示谁。"""

    def __init__(self):
        super().__init__()
        self.shown = None
        self.shell = object()

    def set_instance(self, inst, game_dir):
        self.shown = inst

    def set_server(self, server):
        self.shown = server


class _StubOverlay(QWidget):
    """记录 set_title / set_content / show / hide 的最小覆盖层。"""

    def __init__(self):
        super().__init__()
        self.title = None
        self.content = None
        self.shown = 0
        self.hidden = 0

    def set_title(self, text):
        self.title = text

    def set_content(self, widget):
        self.content = widget

    def show_overlay(self):
        self.shown += 1
        self.show()

    def hide_overlay(self):
        self.hidden += 1
        self.hide()


class _Host:
    """承载 MainWindow 详情方法的轻量宿主。"""

    _ensure_details_overlay = MainWindow._ensure_details_overlay
    _on_details_back = MainWindow._on_details_back
    _open_details_overlay = MainWindow._open_details_overlay
    _show_instance_details = MainWindow._show_instance_details
    _hide_instance_details = MainWindow._hide_instance_details
    _show_server_details = MainWindow._show_server_details
    _hide_server_details = MainWindow._hide_server_details
    _on_instance_selected = MainWindow._on_instance_selected
    _on_server_selected = MainWindow._on_server_selected
    _details_open = MainWindow._details_open

    def __init__(self):
        self.main_tabs = QTabWidget()
        for label in (t("MY_INSTANCES"), t("RESOURCES"), t("MULTIPLAYER")):
            self.main_tabs.addTab(QWidget(), label)
        self.instance_details = _StubContent()
        self.server_details = _StubContent()
        # 预置覆盖层(真实实现里是惰性创建,这里直接给,便于断言)
        self._details_overlay = _StubOverlay()

    def close(self):
        self.main_tabs.deleteLater()
        self._details_overlay.deleteLater()
        QApplication.processEvents()


def _instance():
    return {'id': 'x', 'name': 'X'}


def _server():
    return {'id': 's', 'name': 'S', 'path': '.', 'packagePath': '.',
            'report': {}}


class OverlayBehaviourTests(unittest.TestCase):
    def setUp(self):
        self.host = _Host()
        # 真实实现会调 paths.GAME_DIR 等;宿主上只需记录 payload
        self.addCleanup(self.host.close)

    def test_opening_details_shows_overlay_and_hides_tabs(self):
        self.host._show_instance_details(_instance())
        overlay = self.host._details_overlay
        self.assertEqual(overlay.shown, 1)
        self.assertEqual(overlay.title, t("INSTANCE_DETAILS"))
        self.assertIs(overlay.content, self.host.instance_details)
        self.assertTrue(self.host.main_tabs.isHidden())

    def test_back_restores_tabs(self):
        self.host._show_instance_details(_instance())
        self.host._on_details_back()
        overlay = self.host._details_overlay
        self.assertEqual(overlay.hidden, 1)
        self.assertFalse(self.host.main_tabs.isHidden())
        self.assertIsNone(overlay.content, '返回后应摘掉内容,避免持有已切走的控件')

    def test_switching_between_details_replaces_content(self):
        """核心:同一时刻只能看一个详情页。"""
        self.host._show_instance_details(_instance())
        self.assertIs(self.host._details_overlay.content, self.host.instance_details)
        self.host._show_server_details(_server())
        self.assertIs(self.host._details_overlay.content, self.host.server_details)
        self.assertEqual(self.host._details_overlay.title, '服务端详情')
        # 一个覆盖层实例被复用,没有叠出第二个
        self.assertEqual(self.host._details_overlay.shown, 2)

    def test_payload_does_not_cross(self):
        """客户端详情拿到实例,服务端详情拿到服务端——不能串。"""
        inst, server = _instance(), _server()
        self.host._show_instance_details(inst)
        self.assertIs(self.host.instance_details.shown, inst)
        self.host._show_server_details(server)
        self.assertIs(self.host.server_details.shown, server)

    def test_details_open_flag(self):
        self.assertFalse(self.host._details_open)
        self.host._show_instance_details(_instance())
        self.assertTrue(self.host._details_open)
        self.host._on_details_back()
        self.assertFalse(self.host._details_open)

    def test_selecting_none_closes_open_details(self):
        """选中的实例/服务端消失时,不应把过时详情留在屏幕上。"""
        self.host._show_instance_details(_instance())
        self.host._on_instance_selected(None)
        self.assertFalse(self.host._details_open)

    def test_selecting_does_not_auto_open_details(self):
        """选中列表项不该自动糊住界面(覆盖层是用户主动点开的交互)。"""
        self.host._on_instance_selected(_instance())
        self.host._on_server_selected(_server())
        self.assertEqual(self.host._details_overlay.shown, 0)

    def test_selecting_none_when_closed_is_safe(self):
        self.host._on_instance_selected(None)
        self.host._on_server_selected(None)
        self.assertEqual(self.host._details_overlay.hidden, 0)


class RealWindowIntegrationTests(unittest.TestCase):
    """真实 MainWindow:覆盖层由真实 ContentOverlay 承载。"""

    def _window(self):
        import main as m
        window = m.MainWindow()
        self.addCleanup(self._destroy, window)
        return window

    @staticmethod
    def _destroy(window):
        try:
            window.close()
            window.deleteLater()
            QApplication.processEvents()
        except RuntimeError:
            pass

    def test_no_details_tab_and_no_overlay_at_startup(self):
        window = self._window()
        titles = [window.main_tabs.tabText(i)
                  for i in range(window.main_tabs.count())]
        self.assertNotIn(t("INSTANCE_DETAILS"), titles)
        self.assertNotIn('服务端详情', titles)
        self.assertFalse(window._details_open)
        self.assertFalse(window.main_tabs.isHidden())

    def test_open_and_back_via_real_overlay(self):
        window = self._window()
        window._show_instance_details(window.home_panel.current_instance())
        overlay = window._details_overlay
        self.assertIsNotNone(overlay)
        self.assertTrue(overlay.isVisibleTo(window._background) or not overlay.isHidden())
        self.assertTrue(window.main_tabs.isHidden())
        self.assertEqual(overlay.title_label.text(), t("INSTANCE_DETAILS"))
        # 点真实返回按钮
        overlay.back_btn.click()
        QApplication.processEvents()
        self.assertTrue(overlay.isHidden())
        self.assertFalse(window.main_tabs.isHidden())
        self.assertFalse(window._details_open)


if __name__ == '__main__':
    unittest.main()
