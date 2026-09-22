# -*- coding: utf-8 -*-
"""chat_view 渲染层单测:纯函数部分不依赖 Qt 部件,可直接断言 HTML。

覆盖:
- ChatEntry 数据模型与旧元组/字典的兼容(老归档必须能读回来)
- render_table:结构化表格 → 富文本(QTextBrowser 只认 HTML4 表格属性)
- table_to_text:同一份数据的纯文本形态(给模型/日志)
- render_entry:四类条目 + 工具三级折叠 + 长回答折叠
- HTML 转义:正文里的尖括号不能变成标签
"""
import unittest

from chat_view import (ChatEntry, ai_summary, coerce_entries, esc, is_long_ai,
                       render_entries, render_entry, render_table,
                       table_to_text)


TOKENS = {
    "text": "#111111", "muted": "#777777", "accent": "#2222cc",
    "success": "#229922", "warning": "#cc8800", "danger": "#cc2222",
    "user_bg": "#eeeeff", "ai_bg": "#f5f5f5", "border": "#cccccc",
    "row_alt": "#fafafa",
}


class ChatEntryTests(unittest.TestCase):
    def test_round_trip_dict(self):
        entry = ChatEntry(kind="table", title="清单",
                          columns=["mod", "描述"],
                          rows=[["create", "机械动力"]])
        again = ChatEntry.from_any(entry.to_dict())
        self.assertEqual(again.kind, "table")
        self.assertEqual(again.columns, ["mod", "描述"])
        self.assertEqual(again.rows, [["create", "机械动力"]])

    def test_legacy_tuple_is_still_readable(self):
        """老归档里 entries 是裸元组,必须能无损读回。"""
        legacy = [("user", "你好"), ("ai", "在的"),
                  ("tool", 3, "list_mods", {"instance": "x"}, "ok")]
        entries = coerce_entries(legacy)
        self.assertEqual([e.kind for e in entries], ["user", "ai", "tool"])
        self.assertEqual(entries[2].tool_id, 3)
        self.assertEqual(entries[2].args, {"instance": "x"})

    def test_dict_entries_are_readable(self):
        entries = coerce_entries([{"kind": "system", "text": "启动"},
                                  {"kind": "tool", "id": 1, "name": "t",
                                   "args": {}, "result": "r"}])
        self.assertEqual([e.kind for e in entries], ["system", "tool"])

    def test_unknown_entries_are_dropped_not_crashing(self):
        self.assertEqual(coerce_entries([None, (), ("bogus",), 7]), [])

    def test_plain_text_for_tool_and_table(self):
        tool = ChatEntry(kind="tool", name="list_mods", result="a.jar")
        self.assertIn("a.jar", tool.plain_text)
        table = ChatEntry(kind="table", columns=["a"], rows=[["1"]])
        self.assertIn("a", table.plain_text)


class RenderTableTests(unittest.TestCase):
    def test_table_uses_html4_attributes_not_css(self):
        """QTextBrowser 不支持 CSS 边框,必须用 border/bgcolor 属性。"""
        html = render_table("建议", ["mod", "描述"],
                            [["client.jar", "仅客户端"]], TOKENS)
        self.assertIn('<table border="1"', html)
        self.assertIn('cellpadding="4"', html)
        self.assertIn('bgcolor=', html)
        self.assertNotIn("border-collapse", html)

    def test_header_and_rows_present(self):
        html = render_table("", ["A", "B"], [["1", "2"], ["3", "4"]], TOKENS)
        self.assertEqual(html.count("<tr"), 3)      # 1 表头 + 2 数据行
        self.assertEqual(html.count("<th"), 2)
        self.assertEqual(html.count("<td"), 4)

    def test_empty_table_renders_nothing(self):
        self.assertEqual(render_table("", [], [], TOKENS), "")

    def test_cells_are_escaped(self):
        html = render_table("", ["<b>"], [["<script>"]], TOKENS)
        self.assertIn("&lt;b&gt;", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)

    def test_table_to_text(self):
        text = table_to_text("标题", ["mod", "描述"], [["a", "甲"]])
        self.assertIn("标题", text)
        self.assertIn("mod | 描述", text)
        self.assertIn("a | 甲", text)


class RenderEntryTests(unittest.TestCase):
    def test_user_and_system_bubbles(self):
        user = render_entry(ChatEntry(kind="user", text="你好"), 0, TOKENS)
        self.assertIn("你", user)
        self.assertIn(TOKENS["user_bg"], user)
        system = render_entry(ChatEntry(kind="system", text="就绪"), 0, TOKENS)
        self.assertIn("就绪", system)
        self.assertIn(TOKENS["muted"], system)

    def test_tool_three_level_folding(self):
        entry = ChatEntry(kind="tool", tool_id=7, name="list_mods",
                          args={"instance": "x"}, result="R" * 200)
        level0 = render_entry(entry, 0, TOKENS, tool_level=lambda _i: 0)
        self.assertIn("[查看]", level0)
        self.assertNotIn("R" * 10, level0)
        level1 = render_entry(entry, 0, TOKENS, tool_level=lambda _i: 1)
        self.assertIn("[完整结果]", level1)
        self.assertIn("…", level1)
        level2 = render_entry(entry, 0, TOKENS, tool_level=lambda _i: 2)
        self.assertIn("[收起]", level2)
        self.assertIn("R" * 10, level2)

    def test_long_ai_collapses_only_when_flagged(self):
        long_text = "\n".join(f"行{i}" for i in range(5))
        entry = ChatEntry(kind="ai", text=long_text)
        expanded = render_entry(entry, 2, TOKENS, ai_expanded=True)
        self.assertIn("[展开]", expanded)
        self.assertIn("ai:2", expanded)
        self.assertNotIn("行4", expanded)
        collapsed = render_entry(entry, 2, TOKENS, ai_expanded=False)
        self.assertIn("[收起]", collapsed)
        self.assertIn("行4", collapsed)

    def test_short_ai_has_no_toggle(self):
        out = render_entry(ChatEntry(kind="ai", text="好的"), 0, TOKENS)
        self.assertNotIn("[收起]", out)
        self.assertNotIn("[展开]", out)

    def test_html_in_message_is_escaped(self):
        out = render_entry(ChatEntry(kind="user", text="<img src=x onerror=y>"),
                           0, TOKENS)
        self.assertNotIn("<img", out)
        self.assertIn("&lt;img", out)

    def test_table_entry_renders_table(self):
        out = render_entry(ChatEntry(kind="table", title="清单",
                                     columns=["mod", "描述"],
                                     rows=[["a", "A"]]), 0, TOKENS)
        self.assertIn("<table", out)
        self.assertIn("清单", out)


class HelperTests(unittest.TestCase):
    def test_esc_newlines_become_br(self):
        self.assertEqual(esc("a\nb"), "a<br>b")

    def test_is_long_ai(self):
        self.assertTrue(is_long_ai("a\nb"))
        self.assertTrue(is_long_ai("x" * 200))
        self.assertFalse(is_long_ai("短"))
        self.assertFalse(is_long_ai(""))

    def test_ai_summary_truncates_first_line(self):
        self.assertEqual(ai_summary("第一行\n第二行"), "第一行")
        self.assertTrue(ai_summary("字" * 200).endswith("…"))

    def test_render_entries_concatenates_in_order(self):
        entries = [ChatEntry(kind="user", text="问"),
                   ChatEntry(kind="ai", text="答")]
        html = render_entries(entries, TOKENS)
        self.assertLess(html.index("问"), html.index("答"))


if __name__ == '__main__':
    unittest.main()
