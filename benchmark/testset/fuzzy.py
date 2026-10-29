# -*- coding: utf-8 -*-
"""模糊指令测试集:小白的模糊/抽象说法,看模型能否走"合理工具路径"。

与 single.py 不同:模糊指令**没有唯一正确工具**,expect_tool 是"合理工具集"(任一命中即可),
expect_args 可空。评的是"理解模糊意图、没瞎调、走了合理路径"。

分类:install(想装但没说清)/ optimize(想优化)/ diagnose(有问题但没说清)/ vague(极度模糊)
"""
import os
import sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from launcher_app.ai.ai_testset import _contains, _instance_from_list

# 模糊指令:expect_tool = 合理工具集(任一命中即算走对了路);expect_args 多为空(只看方向)
CASES = [
    # ===== 想装东西但没说清 =====
    {"id": "fz_install_01", "tag": "install", "user": "帮我弄个 mod",
     "expect_tool": ["ask_user", "search_mods", "install_mod", "resolve_mod_concept"],
     "expect_args": {}, "note": "极度模糊的'装mod'→该问/搜索/解析概念"},
    {"id": "fz_install_02", "tag": "install", "user": "装个好玩的",
     "expect_tool": ["ask_user", "search_mods", "search_modpacks", "resolve_mod_concept"],
     "expect_args": {}, "note": "'好玩的'→该问用户要什么"},
    {"id": "fz_install_03", "tag": "install", "user": "我想要个能让游戏更有趣的",
     "expect_tool": ["ask_user", "search_mods", "resolve_mod_concept"],
     "expect_args": {}, "note": "抽象需求→该解析概念/问用户"},
    {"id": "fz_install_04", "tag": "install", "user": "给我整点 mod",
     "expect_tool": ["ask_user", "search_mods", "install_mods"],
     "expect_args": {}, "note": "口语模糊'整点'"},

    # ===== 想优化/改善 =====
    {"id": "fz_opt_01", "tag": "optimize", "user": "我想让游戏更顺",
     "expect_tool": ["search_mods", "ask_user", "resolve_mod_concept"],
     "expect_args": {}, "note": "'更顺'=想优化→搜优化mod/问用户"},
    {"id": "fz_opt_02", "tag": "optimize", "user": "游戏有点卡",
     "expect_tool": ["search_mods", "read_instance_log", "ask_user", "resolve_mod_concept"],
     "expect_args": {}, "note": "'卡'→优化mod/查日志/问"},
    {"id": "fz_opt_03", "tag": "optimize", "user": "帮我优化一下",
     "expect_tool": ["search_mods", "ask_user", "resolve_mod_concept"],
     "expect_args": {}, "note": "抽象'优化'"},
    {"id": "fz_opt_04", "tag": "optimize", "user": "把游戏搞快点",
     "expect_tool": ["search_mods", "ask_user", "resolve_mod_concept"],
     "expect_args": {}, "note": "'搞快点'→优化"},

    # ===== 有问题但没说清 =====
    {"id": "fz_diag_01", "tag": "diagnose", "user": "游戏不太对劲",
     "expect_tool": ["read_instance_log", "read_crash_report", "observe_game", "ask_user"],
     "expect_args": {}, "note": "'不对劲'→该诊断/问"},
    {"id": "fz_diag_02", "tag": "diagnose", "user": "好像出问题了",
     "expect_tool": ["read_instance_log", "read_crash_report", "inspect_instance_core", "ask_user"],
     "expect_args": {}, "note": "模糊故障→该查"},
    {"id": "fz_diag_03", "tag": "diagnose", "user": "帮我看看怎么回事",
     "expect_tool": ["read_instance_log", "read_crash_report", "observe_game", "ask_user"],
     "expect_args": {}, "note": "'怎么回事'→诊断/问"},
    {"id": "fz_diag_04", "tag": "diagnose", "user": "这游戏跑得不正常",
     "expect_tool": ["read_instance_log", "observe_game", "inspect_instance_core", "ask_user"],
     "expect_args": {}, "note": "'不正常'→诊断"},

    # ===== 极度模糊/闲聊边界 =====
    {"id": "fz_vague_01", "tag": "vague", "user": "随便搞搞",
     "expect_tool": ["ask_user", "list_instances", "search_mods"],
     "expect_args": {}, "note": "完全模糊→至少该问/查"},
    {"id": "fz_vague_02", "tag": "vague", "user": "弄一下",
     "expect_tool": ["ask_user", "list_instances"],
     "expect_args": {}, "note": "无意义→该问清楚"},
    {"id": "fz_vague_03", "tag": "vague", "user": "你看着办",
     "expect_tool": ["ask_user", "list_instances", "search_mods"],
     "expect_args": {}, "note": "推给AI→该问/给建议"},
]


def cases_by_tag() -> dict:
    out = {}
    for c in CASES:
        out.setdefault(c.get("tag", "other"), []).append(c)
    return out


if __name__ == "__main__":
    import launcher_app.ai.ai_testset as ai_testset
    bad = 0
    for c in CASES:
        tool = c["expect_tool"][0]
        r = ai_testset.evaluate_output(c, tool, {})
        if not r["name_ok"]:
            bad += 1
    print(f"fuzzy: {len(CASES)} cases, by tag: { {k: len(v) for k, v in cases_by_tag().items()} }")
