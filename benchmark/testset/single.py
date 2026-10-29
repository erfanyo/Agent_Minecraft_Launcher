# -*- coding: utf-8 -*-
"""单步工具调用测试集(扩充版,覆盖 AI 迭代后的全部工具)。

格式与 ai_testset.CASES 一致(id/user/expect_tool/expect_args/note),
匹配器复用 ai_testset 的 _contains/_any_of/_instance_from_list 等。
分类 tag 便于分维度统计(inst/mod/log/cfg/new/cmd/key/rcp/cmp/ask/snap/inspect/server/modpack)。

评测时 system 声明可用实例(DEFAULT_INSTANCES)+ 可用服务端(DEFAULT_SERVERS)。
"""
import os
import sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from launcher_app.ai.ai_testset import (
    _any_of, _contains, _instance_from_list, _slug_anywhere, _mc_version,
)

# 服务端匹配:声明的可用服务端之一(不能编)
def _server_from_list(v):
    s = str(v).strip().lower()
    return any(k in s for k in ("paper", "测试服", "test-server", "paper-1.21.1"))

# 快照 id 匹配:非空字符串(快照 id 由 list 生成,只要求不空/合理)
def _snapshot_id(v):
    return isinstance(v, str) and len(v.strip()) >= 4

DEFAULT_SERVERS = "paper-1.21.1(测试服), test-server"

CASES = [
    # ===== 实例查询 (inst) =====
    {"id": "inst_01", "tag": "inst", "user": "看看我有哪些实例", "expect_tool": ["list_instances"], "expect_args": {}, "note": "无参查询"},
    {"id": "inst_02", "tag": "inst", "user": "列出所有实例", "expect_tool": ["list_instances"], "expect_args": {}, "note": "同义表达"},
    {"id": "inst_03", "tag": "inst", "user": "我装了什么游戏版本", "expect_tool": ["list_instances"], "expect_args": {}, "note": "口语化"},

    # ===== Mod 查询/安装 (mod) =====
    {"id": "mod_01", "tag": "mod", "user": "帮我搜一下钠这个mod", "expect_tool": ["search_mods"], "expect_args": {"query": _contains("钠", "sodium")}, "note": "中文名搜索"},
    {"id": "mod_02", "tag": "mod", "user": "搜索 sodium 光影", "expect_tool": ["search_mods"], "expect_args": {"query": _contains("sodium")}, "note": "英文名搜索"},
    {"id": "mod_03", "tag": "mod", "user": "neoforge-21.1.248 装了哪些mod", "expect_tool": ["list_mods"], "expect_args": {"instance": _instance_from_list}, "note": "列 mod"},
    {"id": "mod_04", "tag": "mod", "user": "看看 fabric 实例里有什么mod", "expect_tool": ["list_mods"], "expect_args": {"instance": _instance_from_list}, "note": "实例别名"},
    {"id": "mod_05", "tag": "inspect", "user": "检查一下 neoforge-21.1.248 里 sodium.jar 这个文件", "expect_tool": ["inspect_mod_jar"], "expect_args": {"instance": _instance_from_list, "filename": _contains("sodium")}, "note": "检视 mod jar(新工具)"},
    {"id": "mod_06", "tag": "mod", "user": "把 neoforge-21.1.248 里的 sodium 停用", "expect_tool": ["set_mod_enabled"], "expect_args": {"instance": _instance_from_list, "filename": _contains("sodium"), "enabled": _any_of(False, "false")}, "note": "禁用 mod(新工具)"},

    # ===== 日志/诊断 (log) =====
    {"id": "log_01", "tag": "log", "user": "看看 neoforge-21.1.248 最近的日志", "expect_tool": ["read_instance_log"], "expect_args": {"instance": _instance_from_list}, "note": "读日志"},
    {"id": "log_02", "tag": "log", "user": "游戏崩了,帮我看看崩溃报告", "expect_tool": ["read_crash_report"], "expect_args": {"instance": _instance_from_list}, "note": "崩溃报告"},
    {"id": "log_03", "tag": "log", "user": "我启动一直闪退,查一下原因", "expect_tool": ["read_crash_report", "read_instance_log"], "expect_args": {"instance": _instance_from_list}, "note": "诊断"},
    {"id": "log_04", "tag": "log", "user": "那把剑的英文 id 是什么", "expect_tool": ["resolve_mc_name"], "expect_args": {"query": _contains("剑")}, "note": "名词解析(新工具)"},
    {"id": "log_05", "tag": "log", "user": "观察一下 neoforge-21.1.248 这轮游戏跑得怎么样", "expect_tool": ["observe_game"], "expect_args": {"instance": _instance_from_list}, "note": "观察游戏进程(新工具)"},

    # ===== 设置 (cfg) =====
    {"id": "cfg_01", "tag": "cfg", "user": "当前启动器设置是什么", "expect_tool": ["get_settings"], "expect_args": {}, "note": "无参查询"},
    {"id": "cfg_02", "tag": "cfg", "user": "我的用户名是什么", "expect_tool": ["get_settings"], "expect_args": {}, "note": "查用户名"},
    {"id": "cfg_03", "tag": "cfg", "user": "把内存改成 6G", "expect_tool": ["set_setting"], "expect_args": {"key": _any_of("memory_gb", "memory"), "value": _any_of("6", "6g", "6144")}, "note": "改内存"},
    {"id": "cfg_04", "tag": "cfg", "user": "帮我把用户名改成 Steve", "expect_tool": ["set_setting"], "expect_args": {"key": _any_of("username", "name"), "value": _contains("steve")}, "note": "改用户名"},

    # ===== 实例创建/启动/备份 (new/inst) =====
    {"id": "new_01", "tag": "new", "user": "帮我建一个 1.21.1 的 fabric 实例", "expect_tool": ["install_instance"], "expect_args": {"version": _contains("1.21.1"), "loader": _any_of("fabric", "")}, "note": "建实例"},
    {"id": "new_02", "tag": "new", "user": "下载原版 1.20.1", "expect_tool": ["install_instance"], "expect_args": {"version": _mc_version("1.20.1")}, "note": "原版实例"},
    {"id": "new_03", "tag": "inst", "user": "启动 neoforge-21.1.248", "expect_tool": ["launch_game"], "expect_args": {"instance": _instance_from_list}, "note": "启动实例"},
    {"id": "inst_mod_03", "tag": "inst", "user": "备份 neoforge-21.1.248", "expect_tool": ["backup_instance"], "expect_args": {"instance": _instance_from_list}, "note": "备份实例"},

    # ===== Mod 安装 (mod install) =====
    {"id": "inst_mod_01", "tag": "mod", "user": "给 neoforge-21.1.248 装钠", "expect_tool": ["install_mod", "install_mods"], "expect_args": {"instance": _instance_from_list, "slug_or_slugs": _slug_anywhere("sodium")}, "note": "装单个 mod"},
    {"id": "inst_mod_02", "tag": "mod", "user": "给 neoforge-21.1.248 装 钠 和 锂", "expect_tool": ["install_mods", "install_mod"], "expect_args": {"instance": _instance_from_list, "slug_or_slugs": _slug_anywhere("sodium", "lithium")}, "note": "批量装 mod"},

    # ===== 指令 (cmd) =====
    {"id": "cmd_01", "tag": "cmd", "user": "给 neoforge-21.1.248 发指令 summon zombie", "expect_tool": ["send_game_command"], "expect_args": {"instance": _instance_from_list, "command": _contains("summon")}, "note": "发指令"},
    {"id": "cmd_02", "tag": "cmd", "user": "让游戏天气变成雨天", "expect_tool": ["send_game_command"], "expect_args": {"command": _contains("weather")}, "note": "天气指令"},
    {"id": "cmd_03", "tag": "cmd", "user": "1.21.1 的 summon 指令怎么写", "expect_tool": ["get_command_guide"], "expect_args": {"mc_version": _mc_version("1.21.1")}, "note": "指令指南"},

    # ===== 按键 (key) =====
    {"id": "key_01", "tag": "key", "user": "neoforge-21.1.248 里空格键绑了什么", "expect_tool": ["get_key_bindings"], "expect_args": {"instance": _instance_from_list, "query": _contains("空格", "space", "32")}, "note": "查按键"},

    # ===== 配方 (rcp) =====
    {"id": "rcp_01", "tag": "rcp", "user": "终极感应供应器怎么合成", "expect_tool": ["get_recipe_path"], "expect_args": {"item": _contains("终极感应供应器")}, "note": "查配方"},
    {"id": "rcp_02", "tag": "rcp", "user": "终极感应供应器要多少材料", "expect_tool": ["get_recipe_path"], "expect_args": {"item": _contains("终极感应供应器"), "brief": _any_of(False, "false")}, "note": "展开材料"},
    {"id": "rcp_03", "tag": "rcp", "user": "查一下 铁锭 的合成配方", "expect_tool": ["get_recipe_path"], "expect_args": {"item": _contains("铁锭")}, "note": "常见物品"},

    # ===== 物品比较 (cmp) =====
    {"id": "cmp_01", "tag": "cmp", "user": "哪个剑伤害最高", "expect_tool": ["compare_items"], "expect_args": {"attribute": _contains("伤害")}, "note": "武器比较"},
    {"id": "cmp_02", "tag": "cmp", "user": "比较一下护甲", "expect_tool": ["compare_items"], "expect_args": {"attribute": _contains("护甲")}, "note": "护甲比较"},

    # ===== 快照 (snap) —— 新工具 =====
    {"id": "snap_01", "tag": "snap", "user": "给 neoforge-21.1.248 拍个完整快照", "expect_tool": ["snapshot_instance"], "expect_args": {"instance": _instance_from_list}, "note": "创建快照(新)"},
    {"id": "snap_02", "tag": "snap", "user": "neoforge-21.1.248 有哪些可以恢复的快照", "expect_tool": ["list_instance_snapshots"], "expect_args": {"instance": _instance_from_list}, "note": "列快照(新)"},
    {"id": "snap_03", "tag": "snap", "user": "把 neoforge-21.1.248 恢复到快照 snap-20260101", "expect_tool": ["restore_instance_snapshot"], "expect_args": {"instance": _instance_from_list, "snapshot_id": _snapshot_id}, "note": "恢复快照(新)"},
    {"id": "snap_04", "tag": "snap", "user": "对比一下 neoforge-21.1.248 现在和快照 snap-20260101 改了哪些文件", "expect_tool": ["compare_instance_snapshot"], "expect_args": {"instance": _instance_from_list, "snapshot_id": _snapshot_id}, "note": "对比快照(新)"},

    # ===== 兼容/替换 (compat) —— 新工具 =====
    {"id": "compat_01", "tag": "compat", "user": "查一下 neoforge-21.1.248 里 sodium 有没有兼容版本", "expect_tool": ["find_compatible_mod_versions"], "expect_args": {"instance": _instance_from_list, "project": _contains("sodium")}, "note": "查兼容版本(新)"},
    {"id": "compat_02", "tag": "compat", "user": "neoforge-21.1.248 里那个不兼容的 sodium.jar 帮我找个替代", "expect_tool": ["find_compatible_mod_replacement"], "expect_args": {"instance": _instance_from_list, "filename": _contains("sodium")}, "note": "找替代(新)"},
    {"id": "compat_03", "tag": "compat", "user": "把 neoforge-21.1.248 的 sodium.jar 换成版本 ver-12345", "expect_tool": ["replace_mod_version"], "expect_args": {"instance": _instance_from_list, "filename": _contains("sodium"), "version_id": _contains("12345")}, "note": "替换版本(新)"},
    {"id": "core_01", "tag": "core", "user": "检查一下 neoforge-21.1.248 的核心文件完不完整", "expect_tool": ["inspect_instance_core"], "expect_args": {"instance": _instance_from_list}, "note": "检查核心(新)"},

    # ===== 整合包 (modpack) —— 新工具 =====
    {"id": "pack_01", "tag": "pack", "user": "搜一下机械动力整合包", "expect_tool": ["search_modpacks"], "expect_args": {"query": _contains("机械动力", "create")}, "note": "搜整合包(新)"},
    {"id": "pack_02", "tag": "pack", "user": "下载 create-into-the-nether 整合包", "expect_tool": ["install_modpack"], "expect_args": {"slug_or_url": _contains("create")}, "note": "装整合包(新)"},

    # ===== 服务端 (server) —— 新工具 =====
    {"id": "srv_01", "tag": "server", "user": "看看有哪些服务端", "expect_tool": ["list_server_instances"], "expect_args": {}, "note": "列服务端(新)"},
    {"id": "srv_02", "tag": "server", "user": "paper-1.21.1 服务端装了哪些 mod", "expect_tool": ["list_server_mods"], "expect_args": {"server": _server_from_list}, "note": "服务端 mod(新)"},
    {"id": "srv_03", "tag": "server", "user": "看看 paper-1.21.1 服务端的日志", "expect_tool": ["read_server_log"], "expect_args": {"server": _server_from_list}, "note": "服务端日志(新)"},
    {"id": "srv_04", "tag": "server", "user": "paper-1.21.1 服务端建议停用哪些 mod", "expect_tool": ["suggest_server_removals", "diagnose_server_mods"], "expect_args": {"server": _server_from_list}, "note": "服务端清理建议(新)"},
    {"id": "srv_05", "tag": "server", "user": "读一下 paper-1.21.1 转服务端的候选报告", "expect_tool": ["read_server_candidate_report"], "expect_args": {"server": _server_from_list}, "note": "候选报告(新)"},
    {"id": "srv_06", "tag": "server", "user": "把 paper-1.21.1 服务端的 sodium 停用", "expect_tool": ["set_server_mod_enabled"], "expect_args": {"server": _server_from_list}, "note": "停用服务端 mod(新)"},

    # ===== 歧义/问用户 (ask) =====
    {"id": "ask_01", "tag": "ask", "user": "我想装几个mod,你帮我推荐下", "expect_tool": ["ask_user"], "expect_args": {"question": lambda v: isinstance(v, str) and len(v) > 3}, "note": "歧义问用户"},
    {"id": "ask_02", "tag": "ask", "user": "你能帮我看看吗,我该装哪些优化mod", "expect_tool": ["ask_user"], "expect_args": {"question": lambda v: isinstance(v, str) and len(v) > 3}, "note": "需要选择"},
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
        args = {}
        for k, m in c.get("expect_args", {}).items():
            if callable(m):
                continue
            args[k] = m[0] if isinstance(m, list) else m
        r = ai_testset.evaluate_output(c, tool, args)
        if r["args_score"] < 1.0 and c.get("expect_args"):
            print(f"[?] {c['id']}: {r['detail']}")
            bad += 1
    print(f"single self-check: {len(CASES)} cases, {bad} need review")
    print("by tag:", {k: len(v) for k, v in cases_by_tag().items()})
