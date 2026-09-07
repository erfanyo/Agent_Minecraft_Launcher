"""Run with QT_QPA_PLATFORM=offscreen; never calls an AI service."""
import unittest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QWidget
from ai_context_pins import ContextPins, context_message


class PinsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dock = QWidget()
        self.dock.settings = {"api_key": "example-secret-value"}
        self.pins = ContextPins(self.dock)
        self.target = QWidget()
        self.data = {"id": "instance/mod.jar", "name": "mod.jar", "content": "example-secret-value"}
        self.pins._target = lambda pos: (self.target, lambda p: dict(self.data))

    def tearDown(self):
        self.pins.cancel()
        self.pins.band.close()
        self.dock.deleteLater()
        self.target.deleteLater()
        self.app.processEvents()

    def test_snapshot_redaction_and_remove(self):
        self.pins.capture(QPoint())
        snapshot = self.pins.message()
        self.assertNotIn("example-secret-value", snapshot)
        self.assertIn("REDACTED", snapshot)
        self.data["name"] = "changed.jar"
        self.assertEqual(snapshot, self.pins.message())
        self.pins.remove(self.pins.records[0][0])
        self.assertEqual("", self.pins.message())

    def test_duplicates_and_limit(self):
        self.pins.capture(QPoint())
        self.pins.capture(QPoint())
        self.assertEqual(1, len(self.pins.records))
        for i in range(12):
            self.data["id"] = str(i)
            self.pins.capture(QPoint())
        self.assertEqual(8, len(self.pins.records))
        self.assertIn("最多", self.pins.hint.text())

    def test_cancel_and_empty(self):
        self.pins.active = True
        self.pins.cancel()
        self.assertFalse(self.pins.active)
        self.assertEqual("", context_message([]))
        self.pins._target = lambda pos: (None, None)
        self.pins.capture(QPoint())
        self.assertEqual([], self.pins.records)

    def test_list_highlight_is_one_card(self):
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        from PySide6.QtCore import Qt, QSize
        from ai_context_pins import target_rect
        widget = QListWidget()
        widget.resize(400, 300)
        item = QListWidgetItem('Mod')
        item.setData(Qt.ItemDataRole.UserRole, 'mod.jar')
        item.setSizeHint(QSize(200, 80))
        widget.addItem(item)
        widget.show()
        self.app.processEvents()
        pos = widget.viewport().mapToGlobal(widget.visualItemRect(item).center())
        rect = target_rect(widget, pos)
        self.assertEqual(80, rect.height())
        self.assertTrue(target_rect(widget, widget.viewport().mapToGlobal(QPoint(10, 200))).isEmpty())
        widget.close()

    def test_text_capture_and_private_subtree(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QLabel, QLineEdit
        from ai_context_pins import ContextPins
        label = QLabel('这段说明', self.target)
        self.target.show()
        label.show()
        self.app.processEvents()
        with patch('ai_context_pins.QApplication.widgetAt', return_value=label):
            widget, provider = ContextPins._target(self.pins, QPoint())
            self.assertEqual(provider(QPoint())['content'], '这段说明')
            self.target.setProperty('ai_pin_sensitive', True)
            self.assertEqual((None, None), ContextPins._target(self.pins, QPoint()))
        self.target.setProperty('ai_pin_sensitive', False)
        edit = QLineEdit('private', self.target)
        with patch('ai_context_pins.QApplication.widgetAt', return_value=edit):
            self.assertEqual((None, None), ContextPins._target(self.pins, QPoint()))

    def test_plugin_context_contract(self):
        from plugin_manager import PluginAPI
        api = PluginAPI('example')
        api.bind_ai_context(self.target, 'status', '插件状态', '只读描述', lambda: '已连接')
        data = self.target.ai_pin_provider(QPoint())
        self.assertEqual('plugin:example:status', data['id'])
        self.assertEqual('已连接', data['content'])
        self.assertEqual('plugin', data['kind'])
        api.exclude_ai_context(self.target)
        self.assertTrue(self.target.property('ai_pin_sensitive'))
        with self.assertRaises(ValueError):
            api.bind_ai_context(self.target, '', '名称', '说明')

    def test_drag_pin_snap_and_cancel(self):
        from PySide6.QtCore import QRect
        from ai_context_pins import DragPin
        from ui_anim import set_animations_enabled
        ghost = self.pins.drag_pin
        set_animations_enabled(False)
        try:
            ghost.follow(QPoint(30, 40))
            self.assertTrue(ghost.isVisible())
            self.assertEqual(QPoint(42, 8), ghost.pos())
            rect = QRect(100, 100, 300, 80)
            ghost.follow(QPoint(120, 120), rect)
            self.assertEqual(DragPin.anchor_point(rect), ghost.pos())
            self.pins.cancel()
            self.assertFalse(ghost.isVisible())
            self.assertIsNone(ghost.anchor)
        finally:
            set_animations_enabled(True)

    def test_snap_waits_and_releases_on_speed(self):
        from PySide6.QtCore import QRect
        from unittest.mock import patch
        ghost = self.pins.drag_pin
        rect = QRect(100, 100, 300, 80)
        with patch('ai_context_pins.time.monotonic', return_value=1.0):
            ghost.track(QPoint(120, 120), rect)
        self.assertIsNone(ghost.anchor)
        self.assertTrue(ghost.snap_timer.isActive())
        ghost._snap()
        self.assertIsNotNone(ghost.anchor)
        with patch('ai_context_pins.time.monotonic', return_value=1.05):
            ghost.track(QPoint(124, 120), rect)
        self.assertIsNotNone(ghost.anchor)
        # Large total displacement is fine when the pointer moves slowly.
        for i in range(1, 11):
            with patch('ai_context_pins.time.monotonic', return_value=1.05 + i * 0.05):
                ghost.track(QPoint(124 + i * 4, 120), rect)
        self.assertIsNotNone(ghost.anchor)
        with patch('ai_context_pins.time.monotonic', return_value=1.57):
                ghost.track(QPoint(240, 120), rect)
        self.assertIsNone(ghost.anchor)
        self.assertGreaterEqual(ghost.snap_timer.interval(), 240)

    def test_dock_button_and_tab_can_pin(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QPushButton, QTabBar
        from ai_context_pins import ContextPins, target_rect
        button = QPushButton('权限设置', self.dock)
        self.dock.show()
        button.show()
        self.app.processEvents()
        with patch('ai_context_pins.QApplication.widgetAt', return_value=button):
            _, provider = ContextPins._target(self.pins, QPoint())
            self.assertEqual('权限设置', provider(QPoint())['content'])
        tabs = QTabBar(self.target)
        tabs.addTab('实例（共 3 个）')
        self.target.show()
        tabs.show()
        self.app.processEvents()
        pos = tabs.mapToGlobal(tabs.tabRect(0).center())
        with patch('ai_context_pins.QApplication.widgetAt', return_value=tabs):
            _, provider = ContextPins._target(self.pins, pos)
            self.assertEqual('实例（共 3 个）', provider(pos)['content'])
            self.assertEqual(tabs.tabRect(0).size(), target_rect(tabs, pos).size())

    def test_click_marker_removes_record(self):
        self.pins.capture(QPoint())
        data = self.pins.records[0][0]
        marker = self.pins.markers[data['id']]()
        self.assertIsNotNone(marker)
        marker.click()
        self.assertEqual([], self.pins.records)
        self.assertEqual({}, self.pins.markers)

    def test_tab_highlight_does_not_cover_hit_testing(self):
        from PySide6.QtWidgets import QTabBar, QApplication
        from ai_context_pins import target_rect
        tabs = QTabBar(self.target)
        tabs.addTab('实例（共 3 个）')
        self.target.resize(350, 100)
        self.target.show()
        tabs.show()
        self.app.processEvents()
        pos = tabs.mapToGlobal(tabs.tabRect(0).center())
        for _ in range(5):
            self.pins.highlight_target(tabs, pos)
            self.app.processEvents()
            self.assertFalse(self.pins.band.isWindow())
            self.assertIs(QApplication.widgetAt(pos), tabs)
            self.assertEqual(target_rect(tabs, pos).size(), self.pins.band.size())

    def test_instance_pin_uses_hovered_row(self):
        from types import SimpleNamespace
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        from PySide6.QtCore import Qt
        from version_home import VersionHome
        widget = QListWidget(self.target)
        widget.resize(300, 200)
        for name in ('first', 'second'):
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, {'id': name, 'base': '1.20.1', 'loader': 'forge'})
            widget.addItem(item)
        widget.setCurrentRow(0)
        self.target.show()
        widget.show()
        self.app.processEvents()
        pos = widget.viewport().mapToGlobal(widget.visualItemRect(widget.item(1)).center())
        data = VersionHome._pin_instance(SimpleNamespace(instance_list=widget), pos)
        self.assertEqual('second', data['instance'])
        self.assertEqual('forge', data['loader'])
        self.assertEqual('1.20.1', data['minecraft'])
        self.assertEqual(0, widget.currentRow())
        self.assertIsNone(VersionHome._pin_instance(SimpleNamespace(instance_list=widget),
                         widget.viewport().mapToGlobal(QPoint(10, 180))))

    def test_download_instance_snapshot(self):
        from resource_center import ResourceBrowser
        inst = {'id': 'pack', 'name': '测试整合包', 'base': '1.21.1', 'loader': 'neoforge'}
        data = ResourceBrowser._instance_pin_snapshot(inst)
        inst['id'] = 'other'
        self.assertEqual('pack', data['instance'])
        self.assertEqual('测试整合包', data['name'])
        self.assertEqual('neoforge', data['loader'])
        self.assertEqual('1.21.1', data['minecraft'])
        self.assertEqual('instance', data['kind'])
        self.assertEqual(data['id'], data['directory'])

    def test_download_version_and_sections(self):
        from types import SimpleNamespace
        from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QListWidget
        from PySide6.QtCore import Qt
        from download_tab import DownloadTab
        from ai_context_pins import target_rect
        tree = QTreeWidget(self.target)
        tree.resize(300, 180)
        item = QTreeWidgetItem(['1.20.1'])
        item.setData(0, Qt.ItemDataRole.UserRole, {'id': '1.20.1', 'type': 'release'})
        tree.addTopLevelItem(item)
        self.target.show()
        tree.show()
        self.app.processEvents()
        pos = tree.viewport().mapToGlobal(tree.visualItemRect(item).center())
        data = DownloadTab._pin_version(SimpleNamespace(version_tree=tree), pos)
        self.assertEqual('MC 1.20.1 版', data['content'])
        self.assertFalse(target_rect(tree, pos).isEmpty())
        item.setData(0, Qt.ItemDataRole.UserRole, {'__major__': '1.20', 'recommended': '1.20.1'})
        self.assertIn('未指定具体版本', DownloadTab._pin_version(SimpleNamespace(version_tree=tree), pos)['content'])
        menu = QListWidget(self.target)
        menu.addItems(['游戏版本', '加载器', '光影 Mod', '优化 Mod'])
        menu.resize(300, 180)
        menu.show()
        self.app.processEvents()
        for i in range(4):
            point = menu.viewport().mapToGlobal(menu.visualItemRect(menu.item(i)).center())
            result = DownloadTab._pin_section(SimpleNamespace(menu=menu, mc='1.20.1'), point)
            self.assertEqual('下载实例 · ' + menu.item(i).text(), result['name'])


if __name__ == "__main__":
    unittest.main()
