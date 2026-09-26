# -*- coding: utf-8 -*-
"""首页入口/按钮布局单测(布局重构后新增)。

锁住这次重构的核心承诺:
- 「实例详情」是紧贴启动按钮上方的独立入口,两种模式都在;
- 按钮总数不变(不靠新增按钮堆功能);
- 客户端/服务端两模式下每个按钮的文字与职责正确,且**不出现重复动作**
  (重构过程中确实一度把两个按钮都设成了「导入服务端」);
- 右列不再有「更新日志 / MC 动态」标签页,更新日志改由设置页进入。
"""
import os
import unittest
from i18n import t

from PySide6.QtWidgets import QApplication, QPushButton

_app = QApplication.instance() or QApplication([])

from version_home import VersionHome


class EntryLayoutTests(unittest.TestCase):
    def _home(self):
        home = VersionHome()
        self.addCleanup(self._destroy, home)
        return home

    @staticmethod
    def _destroy(widget):
        try:
            widget.close()
            widget.setParent(None)
            widget.deleteLater()
            QApplication.processEvents()
        except RuntimeError:
            pass

    def test_details_button_exists_and_is_above_launch(self):
        home = self._home()
        self.assertEqual(home.details_btn.text(), '实例详情')
        # 布局顺序:详情按钮必须排在启动按钮之前(即视觉上在它上方)
        order = []
        for i in range(home._left_panel.layout().count()):
            item = home._left_panel.layout().itemAt(i)
            w = item.widget()
            if w in (home.details_btn, home.launch_btn):
                order.append(w)
        self.assertEqual(order, [home.details_btn, home.launch_btn])

    def test_details_button_emits_signal(self):
        home = self._home()
        seen = []
        home.instance_details_requested.connect(lambda: seen.append(1))
        home.details_btn.click()
        self.assertEqual(seen, [1])

    def test_action_buttons_in_both_modes(self):
        """行2 已移除:左列只剩 实例详情 + 导入/一键配置 + 启动。"""
        home = self._home()
        for setter in (home._set_client_mode, lambda: home._set_server_mode(None)):
            setter()
            buttons = [home.details_btn, home.import_btn, home.config_btn,
                       home.launch_btn]
            for button in buttons:
                self.assertTrue(button.text().strip(), '按钮文字不能为空')
            # 行2 那两个高频按钮已按需求删除
            self.assertFalse(hasattr(home, 'new_game_btn'))
            self.assertFalse(hasattr(home, 'find_mod_btn'))

    def test_client_mode_labels(self):
        home = self._home()
        home._set_client_mode()
        self.assertEqual(t('VERSION_HOME_IMPORT_MODPACK'), home.import_btn.text())
        self.assertEqual(t('VERSION_HOME_ONE_CLICK'), home.config_btn.text())
        self.assertEqual(home.launch_btn.text(), t('启动游戏', 'Launch Game'))

    def test_server_mode_labels(self):
        home = self._home()
        home._set_server_mode(None)
        self.assertEqual(home.import_btn.text(), '服务端管理')
        self.assertEqual(home.config_btn.text(), '导入服务端')
        self.assertEqual(home.launch_btn.text(), '启动服务端')

    def test_no_duplicate_action_labels_in_either_mode(self):
        """两模式下按钮文字不得重复——曾把 打开目录 与 导入服务端 设成同一个动作。"""
        home = self._home()
        for setter in (home._set_client_mode, lambda: home._set_server_mode(None)):
            setter()
            labels = [home.import_btn.text(), home.config_btn.text(),
                      home.details_btn.text()]
            self.assertEqual(len(labels), len(set(labels)),
                             f'按钮文字重复: {labels}')

    def test_server_import_reachable_in_server_mode(self):
        """「导入服务端」在服务端模式下要有入口(下拉菜单)。"""
        home = self._home()
        home._set_server_mode(None)
        menu = home.config_btn.menu()
        self.assertIsNotNone(menu)
        texts = [a.text() for a in menu.actions()]
        self.assertTrue(any('导入服务端' in t for t in texts), texts)

    def test_server_manage_reachable_in_server_mode(self):
        home = self._home()
        home._set_server_mode(None)
        menu = home.import_btn.menu()
        self.assertIsNotNone(menu)
        self.assertTrue(menu.actions())

    def test_client_mode_restores_one_click_menu(self):
        """从服务端模式切回客户端,「一键配置」的下拉要回来。"""
        home = self._home()
        home._set_server_mode(None)
        home._set_client_mode()
        menu = home.config_btn.menu()
        self.assertIsNotNone(menu)
        texts = [a.text() for a in menu.actions()]
        self.assertTrue(any('一键配置' in t for t in texts), texts)

    def test_instance_card_is_clickable_entry(self):
        """详情主入口改为「当前实例卡片」:点卡片要能发信号。"""
        home = self._home()
        seen = []
        home.instance_details_requested.connect(lambda: seen.append(1))
        home.inst_card.clicked.emit()
        self.assertEqual(seen, [1])

    def test_smart_import_toggle_does_not_relabel_wrong_button(self):
        """智能导入开关只影响导入整合包按钮,不能污染其它按钮。"""
        home = self._home()
        home.set_smart_import_enabled(True)
        self.assertIn('智能导入', home.import_btn.text())
        home.set_smart_import_enabled(False)
        self.assertNotIn('智能导入', home.import_btn.text())


class RightColumnTests(unittest.TestCase):
    def _home(self):
        home = VersionHome()
        self.addCleanup(self._destroy, home)
        return home

    @staticmethod
    def _destroy(widget):
        try:
            widget.close()
            widget.setParent(None)
            widget.deleteLater()
            QApplication.processEvents()
        except RuntimeError:
            pass

    def test_changelog_and_community_tabs_removed(self):
        from i18n import t
        home = self._home()
        titles = [home.tabs.tabText(i) for i in range(home.tabs.count())]
        self.assertNotIn(t("VERSION_HOME_CHANGELOG"), titles)
        self.assertNotIn(t("VERSION_HOME_COMMUNITY"), titles)

    def test_no_eager_changelog_fetch_on_construction(self):
        """更新日志改为按需打开,构造首页时不应再拉取(不该有网络线程)。"""
        home = self._home()
        self.assertFalse(hasattr(home, 'changelog_view'))
        self.assertFalse(hasattr(home, '_changelog_loaded'))

    def test_deprecated_changelog_tab_still_callable(self):
        """兼容:旧代码若仍调用它,应返回一个可用控件而不是抛异常。"""
        home = self._home()
        widget = home._build_changelog_tab()
        self.assertIsNotNone(widget)


class SettingsChangelogEntryTests(unittest.TestCase):
    def test_settings_system_page_has_changelog_button(self):
        from settings import load_settings
        from settings.center import SettingsCenter
        center = SettingsCenter(load_settings())
        self.addCleanup(self._destroy, center)
        found = []
        for i in range(center.shell.stack.count()):
            for button in center.shell.stack.widget(i).findChildren(QPushButton):
                if button.text() == '更新日志':
                    found.append(i)
        self.assertTrue(found, '设置里应有「更新日志」入口')

    @staticmethod
    def _destroy(widget):
        try:
            widget.close()
            widget.setParent(None)
            widget.deleteLater()
            QApplication.processEvents()
        except RuntimeError:
            pass


if __name__ == '__main__':
    unittest.main()
