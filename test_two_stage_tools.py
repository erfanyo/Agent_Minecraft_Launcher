# -*- coding: utf-8 -*-
"""两阶段工具调用(模拟悟 L1/L2/L3)防退化测试(P0#1 + P1#6/7 基础)。

背景:0.8B 单阶段「41 选 1」易被抢注意力误调工具。两阶段把一次跳跃拆成
L1 选组(6~11 选 1)→ L2 组内选工具+填参 → L3 自检。effort 控制深度。
本测试用 mock engine 固化 effort→阶段映射、各阶段链路、失败回退,防止脱节。
"""
import unittest
import local_ai


class FakeEng:
    """记录调用序列的假引擎。list_mods 为固定返回。"""
    def __init__(self):
        self.calls = []

    def tool_call(self, text, timeout=120, context="", mounted=None):
        self.calls.append(("tool_call", sorted((mounted or {}).keys())))
        return {"name": "list_mods", "arguments": {"instance": "x"}}

    def _raw_tool_call(self, text, timeout=120, context="", system=None, gbnf=None):
        self.calls.append(("raw", "pick_group" in (gbnf or "")))
        return {"name": "pick_group", "arguments": {"group": "mod"}}


class TwoStageTests(unittest.TestCase):
    def test_effort_to_stage_mapping(self):
        self.assertEqual(local_ai.stage_for_effort("none"), 1)
        self.assertEqual(local_ai.stage_for_effort("minimal"), 1)
        self.assertEqual(local_ai.stage_for_effort("low"), 2)
        self.assertEqual(local_ai.stage_for_effort("medium"), 2)
        self.assertEqual(local_ai.stage_for_effort("high"), 3)
        self.assertEqual(local_ai.stage_for_effort("xhigh"), 3)
        self.assertEqual(local_ai.stage_for_effort("unknown"), 2)  # 兜底 medium
        self.assertEqual(local_ai.stage_for_effort(None), 2)

    def test_group_schemas_filters_cloud_only(self):
        schemas = local_ai.schemas_from_assistant_tools()
        sub = local_ai._group_schemas(
            ["search_mods", "list_mods", "create_plugin", "resolve_mod_concept"], schemas)
        self.assertIn("list_mods", sub)
        self.assertNotIn("create_plugin", sub)
        self.assertNotIn("resolve_mod_concept", sub)

    def test_stage1_is_single_call(self):
        eng = FakeEng()
        result = local_ai.two_stage_tool_call("x", engine=eng, effort="none")
        self.assertEqual(result["name"], "list_mods")
        self.assertTrue(all(c[0] == "tool_call" for c in eng.calls), eng.calls)

    def test_stage2_picks_group_then_tool(self):
        eng = FakeEng()
        result = local_ai.two_stage_tool_call("neoforge 装了哪些mod", engine=eng, effort="medium")
        self.assertEqual(result["name"], "list_mods")
        kinds = [c[0] for c in eng.calls]
        self.assertIn("raw", kinds, "stage2 应先 L1 选组")
        l2 = [c for c in eng.calls if c[0] == "tool_call"]
        self.assertTrue(l2 and "list_mods" in l2[0][1], l2)

    def test_stage3_self_check_retries_on_missing_required(self):
        class NoArgEng(FakeEng):
            def __init__(self):
                super().__init__()
                self.n = 0

            def tool_call(self, text, timeout=120, context="", mounted=None):
                self.n += 1
                self.calls.append(("tool_call", sorted((mounted or {}).keys())))
                if self.n == 1:
                    return {"name": "list_mods", "arguments": {}}   # 缺必填 instance
                return {"name": "list_mods", "arguments": {"instance": "x"}}

        eng = NoArgEng()
        result = local_ai.two_stage_tool_call("x", engine=eng, effort="high")
        self.assertEqual(result["arguments"].get("instance"), "x")
        self.assertEqual(eng.n, 2, "缺必填应重试一次 L2")

    def test_group_pick_failure_falls_back_to_single(self):
        class FailGroup(FakeEng):
            def _raw_tool_call(self, *a, **kw):
                raise ValueError("grammar fail")

        eng = FailGroup()
        result = local_ai.two_stage_tool_call("x", engine=eng, effort="medium")
        self.assertEqual(result["name"], "list_mods")   # 不断链,回退单阶段
        self.assertEqual(eng.calls[-1][0], "tool_call")


if __name__ == "__main__":
    unittest.main()
