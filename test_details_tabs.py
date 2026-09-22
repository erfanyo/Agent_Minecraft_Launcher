# -*- coding: utf-8 -*-
"""详情页挂载单测:两个详情页互斥、按需挂载、不会同时存在。

这是「在服务端里看到客户端实例详情」那次困惑的回归测试。根因是旧实现把两个
详情页都做成**常驻标签页**、只切换可见性,于是它们同时存在;现在改成按需
insertTab / removeTab,任意时刻最多只有一个详情页。

**为什么这样写**:直接 `MainWindow()` 构造一次要十几秒,7 个用例就是 1 分多钟。
但被验证的逻辑其实只依赖「一个 QTabWidget + 两个下标 + 两个详情控件」,所以这里
用一个轻量宿主 ``_Host`` 承载**真实的** ``MainWindow`` 方法(通过
``types.MethodType`` 绑定),既跑的是生产代码,又不用付整个主窗口的构造代价。
只有「启动时不挂载详情页」这一条需要真的造一次 MainWindow(见
:class:`StartupBehaviourTests`)。
"""
import types
import unittest

from PySide6.QtWidgets import QApplication, QLabel, QTabWidget, QWidget

_app = QApplication.instance() or QApplication([])

from i18n import t
from main import MainWindow


class _StubDetails(QWidget):
    """替代真实详情控件:只记录被要求展示谁。"""

    def __init__(self):
        super().__init__()
        self.shown = None
        self.shell = object()      # 非 None 即可(widget 存活断言用)

    def set_instance(self, inst, game_dir):
        self.shown = inst

    def set_server(self, server):
        self.shown = server


class _Host:
    """承载 MainWindow 详情相关方法的轻量宿主(真实 QTabWidget)。"""

    #: 真实方法,直接绑定到本类实例上
    _attach_details_tab = MainWindow._attach_details_tab
    _detach_details_tabs = MainWindow._detach_details_tabs
    _show_instance_details = MainWindow._show_instance_details
    _hide_instance_details = MainWindow._hide_instance_details
    _show_server_details = MainWindow._show_server_details
    _hide_server_details = MainWindow._hide_server_details

    #: 与 MainWindow 保持一致的常量
    INSTANCE_DETAILS_SLOT = MainWindow.INSTANCE_DETAILS_SLOT

    def __init__(self):
        self.main_tabs = QTabWidget()
        # 常驻页,用于验证详情页插在「我的实例」右边
        self.main_tabs.addTab(QWidget(), t("MY_INSTANCES"))
        self.main_tabs.addTab(QWidget(), t("RESOURCES"))
        self.main_tabs.addTab(QWidget(), t("MULTIPLAYER"))
        self.instance_details = _StubDetails()
        self.server_details = _StubDetails()
        self._inst_details_tab_idx = -1
        self._server_details_tab_idx = -1
        self._ui_ready = True

    def titles(self):
        return [self.main_tabs.tabText(i) for i in range(self.main_tabs.count())]

    def close(self):
        self.main_tabs.deleteLater()
        QApplication.processEvents()


def _instance():
    return {'id': 'x', 'name': 'X'}


def _server():
    return {'id': 's', 'name': 'S', 'path': '.', 'packagePath': '.',
            'report': {}}


class DetailsTabTests(unittest.TestCase):
    def setUp(self):
        self.host = _Host()
        # 宿主没有真实窗口,_show_instance_details 的淡入动画置空,避免副作用
        self.host._animate_instance_details_in = lambda: None
        self.addCleanup(self.host.close)

    def test_only_one_details_tab_at_a_time(self):
        """核心回归:客户端与服务端详情不得同时存在。"""
        self.host._show_instance_details(_instance(), switch=False)
        self.assertGreaterEqual(self.host._inst_details_tab_idx, 0)
        self.assertEqual(self.host._server_details_tab_idx, -1)

        self.host._show_server_details(_server())
        self.assertGreaterEqual(self.host._server_details_tab_idx, 0)
        self.assertEqual(self.host._inst_details_tab_idx, -1)

        self.host._show_instance_details(_instance(), switch=False)
        self.assertGreaterEqual(self.host._inst_details_tab_idx, 0)
        self.assertEqual(self.host._server_details_tab_idx, -1)

    def test_detach_removes_both_tabs(self):
        self.host._show_instance_details(_instance(), switch=False)
        self.host._detach_details_tabs()
        self.assertEqual(self.host._inst_details_tab_idx, -1)
        self.assertEqual(self.host._server_details_tab_idx, -1)
        self.assertNotIn(t("INSTANCE_DETAILS"), self.host.titles())

    def test_detach_removes_server_tab_too(self):
        self.host._show_server_details(_server())
        self.host._detach_details_tabs()
        self.assertEqual(self.host._server_details_tab_idx, -1)
        self.assertNotIn('服务端详情', self.host.titles())

    def test_detach_keeps_widget_alive(self):
        """移除标签页不能销毁控件——否则重开会丢状态。"""
        self.host._show_instance_details(_instance(), switch=False)
        widget = self.host.instance_details
        self.host._detach_details_tabs()
        self.assertIs(self.host.instance_details, widget)
        self.assertIsNotNone(widget.shell)

    def test_switching_back_reuses_same_widget(self):
        self.host._show_instance_details(_instance(), switch=False)
        first = self.host.main_tabs.widget(self.host._inst_details_tab_idx)
        self.host._detach_details_tabs()
        self.host._show_instance_details(_instance(), switch=False)
        again = self.host.main_tabs.widget(self.host._inst_details_tab_idx)
        self.assertIs(first, again)

    def test_details_tab_sits_right_after_instances(self):
        """详情页插在「我的实例」右边,且常驻页仍在。"""
        self.host._show_instance_details(_instance(), switch=False)
        titles = self.host.titles()
        for label in (t("MY_INSTANCES"), t("RESOURCES"), t("MULTIPLAYER")):
            self.assertIn(label, titles)
        self.assertEqual(titles.index(t("INSTANCE_DETAILS")), 1)

    def test_show_passes_the_right_payload(self):
        """客户端详情拿到实例,服务端详情拿到服务端——不能串。"""
        inst, server = _instance(), _server()
        self.host._show_instance_details(inst, switch=False)
        self.assertIs(self.host.instance_details.shown, inst)
        self.host._show_server_details(server)
        self.assertIs(self.host.server_details.shown, server)

    def test_switch_parameter_selects_tab(self):
        index = self.host._attach_details_tab('client', self.host.instance_details,
                                              t("INSTANCE_DETAILS"))
        self.host._show_instance_details(_instance(), switch=True)
        self.assertEqual(self.host.main_tabs.currentIndex(), index)

    def test_repeated_show_does_not_duplicate_tab(self):
        for _ in range(3):
            self.host._show_instance_details(_instance(), switch=False)
        self.assertEqual(self.host.titles().count(t("INSTANCE_DETAILS")), 1)


class StartupBehaviourTests(unittest.TestCase):
    """需要真实 MainWindow 的一条:启动阶段不自动挂载详情页。"""

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

    def test_no_details_tab_at_startup(self):
        """启动时不该有任何详情标签页。

        启动过程会触发一轮「选中第一个实例/服务端」(ServerCenter.refresh 会发
        selection_changed);若那时就挂详情页,一开窗口就多出标签页——用户并没有
        要求看它,而且会立刻扫描 mods/日志拖慢开窗。靠 _ui_ready 挡住。
        """
        window = self._window()
        titles = [window.main_tabs.tabText(i)
                  for i in range(window.main_tabs.count())]
        self.assertNotIn(t("INSTANCE_DETAILS"), titles)
        self.assertNotIn('服务端详情', titles)
        self.assertEqual(window._inst_details_tab_idx, -1)
        self.assertEqual(window._server_details_tab_idx, -1)
        # 启动结束后才允许自动挂载
        self.assertTrue(getattr(window, '_ui_ready', False))

    def test_selection_after_startup_mounts_details(self):
        window = self._window()
        window._on_instance_selected(_instance())
        self.assertGreaterEqual(window._inst_details_tab_idx, 0)
        window._on_server_selected(_server())
        self.assertGreaterEqual(window._server_details_tab_idx, 0)
        self.assertEqual(window._inst_details_tab_idx, -1)


if __name__ == '__main__':
    unittest.main()
