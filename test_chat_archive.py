# -*- coding: utf-8 -*-
"""chat_archive 与 chat_view.ChatEntry 的兼容性单测。

重点:老归档(entries 为裸元组)必须仍能读回,新归档(字典)必须能还原成
ChatEntry,渲染层无需分支判断。
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from chat_view import ChatEntry


class ChatArchiveTests(unittest.TestCase):
    def _with_archive(self, fn):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.dict(os.environ, {}, clear=False):
                import chat_archive as ca
                original = ca.ARCHIVE_DIR
                ca.ARCHIVE_DIR = temp
                try:
                    return fn(ca)
                finally:
                    ca.ARCHIVE_DIR = original

    def test_round_trip_keeps_all_entry_kinds(self):
        def run(ca):
            entries = [
                ChatEntry(kind="user", text="问一句"),
                ChatEntry(kind="ai", text="答一句"),
                ChatEntry(kind="system", text="系统消息"),
                ChatEntry(kind="tool", tool_id=5, name="list_mods",
                          args={"instance": "x"}, result="结果"),
                ChatEntry(kind="table", title="清单", columns=["mod", "描述"],
                          rows=[["a.jar", "仅客户端"]]),
            ]
            saved = ca.save_session([{"role": "user", "content": "问一句"}], entries)
            self.assertTrue(saved["ok"], saved)
            loaded = ca.load_session(saved["path"])
            self.assertTrue(loaded["ok"])
            kinds = [e.kind for e in loaded["entries"]]
            self.assertEqual(kinds, ["user", "ai", "system", "tool", "table"])
            table = loaded["entries"][-1]
            self.assertEqual(table.columns, ["mod", "描述"])
            self.assertEqual(table.rows, [["a.jar", "仅客户端"]])
            tool = loaded["entries"][3]
            self.assertEqual(tool.tool_id, 5)
            self.assertEqual(tool.args, {"instance": "x"})

        self._with_archive(run)

    def test_legacy_tuple_archive_is_still_loadable(self):
        """历史归档文件里 entries 是元组列表,升级后必须还能读。"""
        def run(ca):
            legacy = {"title": "旧会话", "created_at": "2026-01-01 00:00:00",
                      "chat_messages": [],
                      "entries": [{"kind": "user", "text": "老的"},
                                  {"kind": "ai", "text": "回复"},
                                  {"kind": "tool", "id": 1, "name": "t",
                                   "args": {}, "result": "r"}]}
            path = os.path.join(ca.ARCHIVE_DIR, "legacy.json")
            os.makedirs(ca.ARCHIVE_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(legacy, f, ensure_ascii=False)
            loaded = ca.load_session(path)
            self.assertTrue(loaded["ok"])
            kinds = [e.kind for e in loaded["entries"]]
            self.assertEqual(kinds, ["user", "ai", "tool"])
            # 载入结果必须是 ChatEntry,渲染层不需要再判类型。
            self.assertTrue(all(isinstance(e, ChatEntry) for e in loaded["entries"]))

        self._with_archive(run)

    def test_default_title_picks_first_user_message(self):
        def run(ca):
            entries = [ChatEntry(kind="system", text="启动"),
                       ChatEntry(kind="user", text="帮我看看日志")]
            saved = ca.save_session([], entries)
            self.assertEqual(saved["title"], "帮我看看日志")
            # 旧元组形态也要能取到标题。
            legacy = [("system", "启动"), ("user", "元组标题")]
            saved2 = ca.save_session([], legacy)
            self.assertEqual(saved2["title"], "元组标题")

        self._with_archive(run)


if __name__ == '__main__':
    unittest.main()
