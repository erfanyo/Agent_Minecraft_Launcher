# -*- coding: utf-8 -*-
"""多步规划剧本测试集(纯剧本:预设工具回复,不真执行)。

每个剧本 = 一个用户请求 + 工具的"预设回复"(剧本),观察模型拿到回复后的**下一步决策**。
评的是多步规划能力(拿到坏消息后怎么办),不是单步工具调用。

用法:runner 按剧本跑多轮——发起请求 → 模型调工具 → 喂预设回复 → 看下一步 → …
产出 md 供人工面试(决策合理性 ABCD 分级,见 rubric.md)。

剧本结构:
  id        稳定编号
  user      用户请求
  steps     预设的"工具→回复"序列(剧本);每步 observe 期望模型下一步该调的工具(合理集)
  expect_final  最终期望(结束条件/最终答复方向)
"""
import os
import sys

# 每个剧本:steps = [(期望模型第 N 步调的工具(合理集), 预设给模型看的工具回复), ...]
# observe: 模型收到预设回复后的下一步动作,我们只观察不预设强答案(人工面试)
CASES = [
    {
        "id": "ms_voxy",
        "user": "给 neoforge-21.1.248 装 voxy",
        "steps": [
            # 第1步:模型应调 install_mod(voxy) → 回复"没有 voxy"
            {"expect_tool": ["install_mod", "install_mods", "search_mods"],
             "tool_reply": "1.21.1 neoforge 没有 voxy 这个 mod(Modrinth 上查不到该 slug)。"},
            # 第2步:观察——换同类(distant horizons)?找替代?跨平台?还是叫用户放弃?
            {"expect_tool": ["search_mods", "find_compatible_mod_replacement", "ask_user"],
             "tool_reply": "搜索 distant horizons:找到 distant-horizons(同类 LOD mod),适配 1.21.1 neoforge。"},
        ],
        "expect_final": "给出替代方案(distant horizons)或问用户,而非硬装/瞎编",
        "note": "voxy 缺失→看后续处理(换同类/跨平台/叫用户放弃)",
    },
    {
        "id": "ms_restore",
        "user": "把 neoforge-21.1.248 恢复到昨天的状态",
        "steps": [
            # 第1步:应先查有哪些快照(不能瞎编 snapshot_id)
            {"expect_tool": ["list_instance_snapshots"],
             "tool_reply": "可恢复快照:snap-20260101(昨天), snap-20251230(前天)。"},
            # 第2步:选一个快照恢复
            {"expect_tool": ["restore_instance_snapshot"],
             "tool_reply": "已恢复到 snap-20260101,当前实例保留。"},
        ],
        "expect_final": "先查快照再恢复,不编造 snapshot_id",
        "note": "多步:需先查后做",
    },
    {
        "id": "ms_bycraft",
        "user": "帮我找个能自动熔炉的东西",
        "steps": [
            # 第1步:抽象需求→应先解析概念(不该直接瞎装)
            {"expect_tool": ["resolve_mod_concept", "search_mods", "ask_user"],
             "tool_reply": "候选:create(机械动力)、mekanism(通用机械)、thermal(热力)。你要哪个?"},
            # 第2步:用户选了 create → 装
            {"expect_tool": ["install_mod"],
             "tool_reply": "已给 neoforge-21.1.248 装 create。"},
        ],
        "expect_final": "模糊需求→解析概念→用户选→装,不瞎猜 slug",
        "note": "按功能找 mod(多步:解析→选择→安装)",
    },
    {
        "id": "ms_stillcrash",
        "user": "我装了 sodium 但游戏还是崩",
        "steps": [
            # 第1步:装了没用→应诊断(查日志/崩溃报告)
            {"expect_tool": ["read_crash_report", "read_instance_log"],
             "tool_reply": "崩溃报告:Rendering overlay 失败,疑似 sodium 与现有光影冲突。"},
            # 第2步:定位到冲突→禁用/换
            {"expect_tool": ["set_mod_enabled", "find_compatible_mod_replacement", "ask_user"],
             "tool_reply": "已禁用冲突光影,sodium 保留。"},
        ],
        "expect_final": "装了没用→诊断原因→处理冲突,而非重复装",
        "note": "装了还崩(多步:诊断→处理)",
    },
    {
        "id": "ms_dep",
        "user": "neoforge-21.1.248 装不上 sodium,提示缺依赖",
        "steps": [
            # 第1步:依赖缺失→应查缺什么前置
            {"expect_tool": ["inspect_mod_jar", "find_compatible_mod_replacement", "read_instance_log"],
             "tool_reply": "sodium.jar 声明依赖 lithium(未安装)。"},
            # 第2步:补前置
            {"expect_tool": ["install_mod", "install_mods"],
             "tool_reply": "已补装 lithium,sodium 现在可装。"},
        ],
        "expect_final": "装不上→查依赖→补前置",
        "note": "依赖缺失(多步:查→补)",
    },
    {
        "id": "ms_downgrade",
        "user": "我要用一个只支持 1.20.1 的老 mod",
        "steps": [
            # 第1步:版本不匹配→应找有该 mod 的版本/实例
            {"expect_tool": ["install_instance", "search_mods", "ask_user"],
             "tool_reply": "该 mod 只支持 1.20.1 forge。当前实例是 1.21.1 neoforge,不兼容。"},
            # 第2步:建 1.20.1 实例 或 问用户
            {"expect_tool": ["install_instance", "ask_user"],
             "tool_reply": "已创建 1.20.1 forge 实例,可装该 mod。"},
        ],
        "expect_final": "版本不匹配→建兼容实例/问用户,而非硬装到不兼容实例",
        "note": "版本不匹配(多步:找兼容→建/问)",
    },
]


def cases_by_id():
    return {c["id"]: c for c in CASES}


if __name__ == "__main__":
    print(f"multistep: {len(CASES)} scripts")
    for c in CASES:
        print(f"  {c['id']:16s} steps={len(c['steps'])}  {c['note']}")
