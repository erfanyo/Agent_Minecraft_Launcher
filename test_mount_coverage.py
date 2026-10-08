# -*- coding: utf-8 -*-
"""按需挂载不漏挂的防退化测试(P0 bug 回归)。

背景:曾出现「list_mods 被 CLOUD_MAX_TOOLS 截断挤掉 + server 组误命中『哪些mod』」
→ 模型看不见 list_mods,转头误调 create_plugin。修复见 assistant.mount_tools_for 的
core 集合 + TOOL_GROUP_KEYWORDS['server'] 组合词。本测试把「期望工具必须挂上」固化,
防止加工具/改关键词时又脱节。
"""
import unittest
import assistant
from assistant import mount_tools_for
import ai_testset


class MountCoverageTests(unittest.TestCase):
    def test_all_expected_tools_are_mounted(self):
        """每条测试用例的期望工具都必须出现在按需挂载结果里(漏挂=模型选错率100%)。"""
        for case in ai_testset.CASES:
            names = {t["function"]["name"] for t in mount_tools_for(case["user"])}
            for expect in case["expect_tool"]:
                self.assertIn(
                    expect, names,
                    f"{case['id']} ({case['user']!r}) 期望工具 {expect} 被漏挂;"
                    f"挂载={sorted(names)}")

    def test_list_mods_mounted_for_mod_queries(self):
        """回归:list_mods 之前被截断挤掉。查询类必须稳定挂上。"""
        for q in ("neoforge-21.1.248 装了哪些mod", "看看 fabric 实例里有什么mod",
                  "列出 neoforge-21.1.248 的 mod"):
            names = {t["function"]["name"] for t in mount_tools_for(q)}
            self.assertIn("list_mods", names, f"{q!r} 应挂 list_mods,实际 {sorted(names)}")

    def test_server_group_not_hijacked_by_client_mod_query(self):
        """回归:「XX 装了哪些mod」是客户端查询,不应把整套服务端工具拉进候选。"""
        names = {t["function"]["name"] for t in mount_tools_for("neoforge-21.1.248 装了哪些mod")}
        server_tools = {"list_server_instances", "read_server_log", "list_server_mods"}
        self.assertFalse(server_tools & names,
                         f"客户端 mod 查询不应命中服务端工具,实际挂了 {sorted(server_tools & names)}")

    def test_query_tools_survive_truncation(self):
        """只读查询工具即使候选超限也必须在截断窗口内。"""
        from assistant import CLOUD_MAX_TOOLS
        for q in ("neoforge-21.1.248 装了哪些mod", "给 neoforge-21.1.248 发指令 summon zombie"):
            mounted = mount_tools_for(q)
            names = {t["function"]["name"] for t in mounted}
            # 插件/MCP 追加在截断后,这里只看内置截断窗口
            self.assertLessEqual(len([n for n in names if not n.startswith("mcp__")]),
                                 CLOUD_MAX_TOOLS + 5, "候选规模应受控")
            self.assertTrue({"list_instances", "get_settings"} & names, "通用工具恒在")


if __name__ == "__main__":
    unittest.main()
