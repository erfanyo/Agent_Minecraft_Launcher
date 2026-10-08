# -*- coding: utf-8 -*-
"""首次引导:新手/老手左右选择卡 + 游戏目录页文件夹图标。"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QTextBrowser)

from onboarding import OnboardingDialog, _ChoiceCard

_app = QApplication.instance() or QApplication([])


class ChoiceCardTests(unittest.TestCase):
    def setUp(self):
        self.d = OnboardingDialog()

    def test_two_cards_side_by_side(self):
        """新手 / 老手 是左右两张卡,不是上下两个单选。"""
        page0 = self.d.stack.widget(0)
        self.assertIsInstance(self.d.rb_new, _ChoiceCard)
        self.assertIsInstance(self.d.rb_old, _ChoiceCard)
        self.assertIs(self.d.rb_new.parentWidget(), page0)
        self.assertIs(self.d.rb_old.parentWidget(), page0)

        side_by_side = False
        for lay in page0.findChildren(QHBoxLayout):
            widgets = [lay.itemAt(i).widget() for i in range(lay.count())]
            if self.d.rb_new in widgets and self.d.rb_old in widgets:
                side_by_side = True
                break
        self.assertTrue(side_by_side, "两张卡应在同一个横向布局里")

    def test_card_has_image_placeholder_and_caption(self):
        card = self.d.rb_new
        self.assertEqual(card.title.text(), "新手")
        self.assertTrue(card.subtitle.text(), "应有小字标注")
        self.assertEqual(self.d.rb_old.title.text(), "老手")

    def test_cards_use_real_illustrations(self):
        """两张卡应加载 onboarding-images/ 里的透明底插图(而不是占位符)。"""
        for card in (self.d.rb_new, self.d.rb_old):
            self.assertIsNotNone(card._source, "应加载真实插图")
            self.assertFalse(card.image.pixmap().isNull(), "应显示缩放后的图")
            self.assertEqual(card.image.text(), "", "有图时不该再显示占位文字")

    def test_image_keeps_aspect_ratio(self):
        card = self.d.rb_new
        shown = card.image.pixmap()
        src = card._source
        self.assertLessEqual(shown.width() / max(shown.height(), 1),
                             src.width() / max(src.height(), 1) + 0.02)

    def test_missing_image_falls_back_to_placeholder(self):
        card = _ChoiceCard(
            "新手", "说明",
            {"accent": "#1", "border": "#2", "sel": "#3", "base": "#4",
             "btn_bg": "#5", "text": "#6", "muted": "#7"},
            image_path="Z:/definitely/not/here.png")
        self.assertIsNone(card._source)
        self.assertEqual(card.image.text(), "🖼")

    def test_exclusive_selection(self):
        self.assertTrue(self.d.rb_new.isChecked())
        self.assertFalse(self.d.rb_old.isChecked())
        self.d.rb_old.clicked.emit()               # 点「老手」
        self.assertFalse(self.d.rb_new.isChecked())
        self.assertTrue(self.d.rb_old.isChecked())
        self.d.rb_new.clicked.emit()               # 点回「新手」
        self.assertTrue(self.d.rb_new.isChecked())
        self.assertFalse(self.d.rb_old.isChecked())

    def test_folder_icon_on_path_page(self):
        page1 = self.d.stack.widget(1)
        icons = [l for l in page1.findChildren(QLabel)
                 if l.pixmap() is not None and not l.pixmap().isNull()]
        self.assertTrue(icons, "游戏目录页文字前应有文件夹图标")
        self.assertFalse(icons[0].pixmap().isNull())

    def test_tutorial_page_still_ok(self):
        b = self.d.stack.widget(2).findChildren(QTextBrowser)[0]
        self.assertIn("硅基流动", b.toPlainText())


if __name__ == "__main__":
    unittest.main()
