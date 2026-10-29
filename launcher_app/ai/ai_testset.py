# -*- coding: utf-8 -*-
"""
AI 回归测试集(规划 §7.4):固定测试用例(几十条典型指令 + 期望输出)。

模型 / 规则更新后自动跑,防"修好一个弄坏三个"。每条用例:
  id          稳定编号
  user        用户原话(典型指令,中文为主,与启动器真实使用一致)
  expect_tool 期望调用的工具名(可给多个 = 任一命中即算对)
  expect_args 期望参数:{key: 匹配器}。匹配器可以是:
              - 字符串:规范化后精确相等
              - 列表:规范化后命中任一
              - callable(value)->bool:自定义
              expect_args 里每个 key 必须出现在模型输出中且匹配(按比例给分)
  note        说明这条测什么

工具集合与 assistant.py TOOLS / agent_tools.py 保持一致。
测试时默认给模型的系统提示里声明可用实例,便于填 instance 参数。
"""
# 系统提示模板:评测时填入 {instances}(可用实例清单)
SYSTEM_TEMPLATE = (
    "你是 Agent Minecraft 启动器的 AI 助手,负责帮玩家完成启动器操作。"
    "你可以调用工具完成任务。可用实例:{instances}。"
    "需要实例 id 时必须从可用实例中选择。回答要简洁,直接调用工具。"
)

# 评测默认的可用实例(与测试用例期望值对齐)
DEFAULT_INSTANCES = "neoforge-21.1.248, fabric-1.21.1, vanilla-1.20.1"

# 常见归一化别名(参数值匹配用)
_INSTANCE_ALIASES = {
    "neoforge": "neoforge-21.1.248",
    "neo": "neoforge-21.1.248",
    "neoforge-21.1.248": "neoforge-21.1.248",
    "fabric": "fabric-1.21.1",
    "fabric-1.21.1": "fabric-1.21.1",
    "vanilla": "vanilla-1.20.1",
    "原版": "vanilla-1.20.1",
}
_SLUG_ALIASES = {
    "钠": "sodium",
    "sodium": "sodium",
    "锂": "lithium",
    "lithium": "lithium",
    "玉": "jade",
    "jade": "jade",
    "jei": "jei",
    "create": "create",
    "机械动力": "create",
}
_MC_VERSION_ALIASES = {
    "1.21.1": "1.21.1",
    "1211": "1.21.1",
    "1.20.1": "1.20.1",
    "1.21": "1.21.1",
    "26.2": "26.2",
}


def norm(s) -> str:
    """参数值规范化:小写、去空白、去引号"""
    if not isinstance(s, str):
        return str(s)
    return s.strip().strip('"').strip("'").lower()


def _alias_map(value, table):
    v = norm(value)
    if v in table:
        return table[v]
    return v


def _instance(v):
    return _alias_map(v, _INSTANCE_ALIASES)


def _slug(v):
    return _alias_map(v, _SLUG_ALIASES)


def _mc_version(v):
    return _alias_map(v, _MC_VERSION_ALIASES)


def _any_of(*allowed):
    """参数值命中任一允许值(已规范化比较)"""
    allowed_n = [norm(a) for a in allowed]
    return lambda v: norm(v) in allowed_n


def _contains(*subs):
    """参数值包含任一子串(规范化)"""
    subs_n = [norm(s) for s in subs]
    return lambda v: any(s in norm(v) for s in subs_n)


def _instance_from_list(v):
    """instance 参数:必须是声明的可用实例之一(不能乱编)"""
    return _instance(v) in ("neoforge-21.1.248", "fabric-1.21.1", "vanilla-1.20.1")


def _slug_list(v):
    """slugs 列表参数:每个元素都规范化为已知 slug"""
    if not isinstance(v, list):
        return False
    return all(_slug(x) in ("sodium", "lithium", "jade", "jei", "create") for x in v)


def _slug_list_exact(*expected):
    """slugs 列表与期望集合一致(顺序无关)"""
    exp = {_slug(e) for e in expected}
    return lambda v: (isinstance(v, list) and {_slug(x) for x in v} == exp)


def _slug_anywhere(*expected):
    """slug(单装)或 slugs(批量)任一包含期望项 —— 兼容 install_mod / install_mods 两种调用。
    这是跨字段匹配器:接收完整 args 字典(带 _whole_args 标记,evaluate_output 据此区分)"""
    exp = {_slug(e) for e in expected}
    def check(args):
        if "slugs" in args and isinstance(args.get("slugs"), list):
            return {_slug(x) for x in args["slugs"]} == exp
        if "slug" in args:
            return _slug(args["slug"]) in exp
        return False
    check._whole_args = True
    return check


# ================= 测试用例 =================
CASES = [
    # ---- 实例类 ----
    {"id": "inst_01", "user": "看看我有哪些实例", "expect_tool": ["list_instances"], "expect_args": {}, "note": "无参查询"},
    {"id": "inst_02", "user": "列出所有实例", "expect_tool": ["list_instances"], "expect_args": {}, "note": "同义表达"},
    {"id": "inst_03", "user": "我装了什么游戏版本", "expect_tool": ["list_instances"], "expect_args": {}, "note": "口语化"},

    # ---- Mod 搜索/列表 ----
    {"id": "mod_01", "user": "帮我搜一下钠这个mod", "expect_tool": ["search_mods"], "expect_args": {"query": _contains("钠", "sodium")}, "note": "中文名搜索(中英文都接受)"},
    {"id": "mod_02", "user": "搜索 sodium 光影", "expect_tool": ["search_mods"], "expect_args": {"query": _contains("sodium")}, "note": "英文名搜索"},
    {"id": "mod_03", "user": "neoforge-21.1.248 装了哪些mod", "expect_tool": ["list_mods"], "expect_args": {"instance": _instance_from_list}, "note": "实例已给出"},
    {"id": "mod_04", "user": "看看 fabric 实例里有什么mod", "expect_tool": ["list_mods"], "expect_args": {"instance": _instance_from_list}, "note": "实例别名"},

    # ---- 日志/崩溃 ----
    {"id": "log_01", "user": "看看 neoforge-21.1.248 最近的日志", "expect_tool": ["read_instance_log"], "expect_args": {"instance": _instance_from_list}, "note": "读日志"},
    {"id": "log_02", "user": "游戏崩了,帮我看看崩溃报告", "expect_tool": ["read_crash_report"], "expect_args": {"instance": _instance_from_list}, "note": "崩溃报告"},
    {"id": "log_03", "user": "我启动一直闪退,查一下原因", "expect_tool": ["read_crash_report", "read_instance_log"], "expect_args": {"instance": _instance_from_list}, "note": "诊断(两个工具都算对)"},

    # ---- 设置 ----
    {"id": "cfg_01", "user": "当前启动器设置是什么", "expect_tool": ["get_settings"], "expect_args": {}, "note": "无参查询"},
    {"id": "cfg_02", "user": "我的用户名是什么", "expect_tool": ["get_settings"], "expect_args": {}, "note": "从设置里查用户名"},
    {"id": "cfg_03", "user": "把内存改成 6G", "expect_tool": ["set_setting"], "expect_args": {"key": _any_of("memory_gb", "memory"), "value": _any_of("6", "6g", "6144")}, "note": "改内存"},
    {"id": "cfg_04", "user": "帮我把用户名改成 Steve", "expect_tool": ["set_setting"], "expect_args": {"key": _any_of("username", "name"), "value": _contains("steve")}, "note": "改用户名"},

    # ---- 实例创建/启动 ----
    {"id": "new_01", "user": "帮我建一个 1.21.1 的 fabric 实例", "expect_tool": ["install_instance"], "expect_args": {"version": _contains("1.21.1"), "loader": _any_of("fabric", "")}, "note": "建带加载器实例(版本含 1.21.1 即可)"},
    {"id": "new_02", "user": "下载原版 1.20.1", "expect_tool": ["install_instance"], "expect_args": {"version": _mc_version("1.20.1")}, "note": "原版实例(loader 可空)"},
    {"id": "new_03", "user": "启动 neoforge-21.1.248", "expect_tool": ["launch_game"], "expect_args": {"instance": _instance_from_list}, "note": "启动实例"},

    # ---- Mod 安装/备份 ----
    {"id": "inst_mod_01", "user": "给 neoforge-21.1.248 装钠", "expect_tool": ["install_mod", "install_mods"], "expect_args": {"instance": _instance_from_list, "slug_or_slugs": _slug_anywhere("sodium")}, "note": "装单个mod(单装/批量都算对)"},
    {"id": "inst_mod_02", "user": "给 neoforge-21.1.248 装 钠 和 锂", "expect_tool": ["install_mods", "install_mod"], "expect_args": {"instance": _instance_from_list, "slug_or_slugs": _slug_anywhere("sodium", "lithium")}, "note": "批量装两个mod"},
    {"id": "inst_mod_03", "user": "备份 neoforge-21.1.248", "expect_tool": ["backup_instance"], "expect_args": {"instance": _instance_from_list}, "note": "备份实例"},

    # ---- 游戏指令 ----
    {"id": "cmd_01", "user": "给 neoforge-21.1.248 发指令 summon zombie", "expect_tool": ["send_game_command"], "expect_args": {"instance": _instance_from_list, "command": _contains("summon")}, "note": "发游戏指令"},
    {"id": "cmd_02", "user": "让游戏天气变成雨天", "expect_tool": ["send_game_command"], "expect_args": {"command": _contains("weather")}, "note": "天气指令(instance 可缺省)"},
    {"id": "cmd_03", "user": "1.21.1 的 summon 指令怎么写", "expect_tool": ["get_command_guide"], "expect_args": {"mc_version": _mc_version("1.21.1")}, "note": "查指令指南"},

    # ---- 按键绑定 ----
    {"id": "key_01", "user": "neoforge-21.1.248 里空格键绑了什么", "expect_tool": ["get_key_bindings"], "expect_args": {"instance": _instance_from_list, "query": _contains("空格", "space", "32")}, "note": "查按键绑定(空格键/space/32 都接受)"},

    # ---- 配方 ----
    {"id": "rcp_01", "user": "终极感应供应器怎么合成", "expect_tool": ["get_recipe_path"], "expect_args": {"item": _contains("终极感应供应器")}, "note": "中文名查配方"},
    {"id": "rcp_02", "user": "终极感应供应器要多少材料", "expect_tool": ["get_recipe_path"], "expect_args": {"item": _contains("终极感应供应器"), "brief": _any_of(False, "false")}, "note": "要完整材料(应展开)"},
    {"id": "rcp_03", "user": "查一下 铁锭 的合成配方", "expect_tool": ["get_recipe_path"], "expect_args": {"item": _contains("铁锭")}, "note": "常见物品"},

    # ---- 物品比较 ----
    {"id": "cmp_01", "user": "哪个剑伤害最高", "expect_tool": ["compare_items"], "expect_args": {"attribute": _contains("伤害")}, "note": "武器伤害比较"},
    {"id": "cmp_02", "user": "比较一下护甲", "expect_tool": ["compare_items"], "expect_args": {"attribute": _contains("护甲")}, "note": "护甲比较"},

    # ---- 交互/兜底 ----
    {"id": "ask_01", "user": "我想装几个mod,你帮我推荐下", "expect_tool": ["ask_user"], "expect_args": {"question": lambda v: isinstance(v, str) and len(v) > 3}, "note": "歧义→问用户"},
    {"id": "ask_02", "user": "你能帮我看看吗,我该装哪些优化mod", "expect_tool": ["ask_user"], "expect_args": {"question": lambda v: isinstance(v, str) and len(v) > 3}, "note": "需要用户选择"},
]


def evaluate_output(case: dict, tool_name: str, args: dict) -> dict:
    """打分一个模型的工具调用输出。返回 {name_ok, args_score, detail}。

    name_ok:工具名命中期望(1.0/0.0)
    args_score:期望参数里有多少比例匹配(0~1);无期望参数时恒 1.0
    detail:逐参数的匹配说明(便于看差距)
    """
    expected_names = case["expect_tool"]
    name_ok = 1.0 if tool_name in expected_names else 0.0

    expect_args = case.get("expect_args", {})
    if not expect_args:
        return {"name_ok": name_ok, "args_score": 1.0, "detail": "无参数要求"}

    hit = 0
    detail = []
    for key, matcher in expect_args.items():
        if callable(matcher):
            if getattr(matcher, "_whole_args", False):
                # 跨字段匹配器:接收完整 args 字典(如 slug/slugs 二选一)
                try:
                    ok = bool(matcher(args))
                except Exception:
                    ok = False
                detail.append(f"{key}={'...'} {'✓' if ok else '✗'}")
            else:
                # 单值匹配器:接收该 key 的值
                val = args.get(key)
                if val is None:
                    ok = False
                    detail.append(f"{key}=缺失")
                else:
                    try:
                        ok = bool(matcher(val))
                    except Exception:
                        ok = False
                    detail.append(f"{key}={val!r} {'✓' if ok else '✗'}")
            hit += 1 if ok else 0
            continue
        val = args.get(key)
        if val is None:
            detail.append(f"{key}=缺失")
            continue
        try:
            ok = norm(val) == norm(matcher)
        except Exception:
            ok = False
        detail.append(f"{key}={val!r} {'✓' if ok else '✗'}")
        hit += 1 if ok else 0
    args_score = hit / len(expect_args)
    return {"name_ok": name_ok, "args_score": args_score, "detail": "; ".join(detail)}


def total_cases() -> int:
    return len(CASES)


if __name__ == "__main__":
    # 自检:每条用例都能被"理想输出"命中(防测试集写错)。
    # callable 匹配器无法自动猜值,跳过;字符串/列表匹配器用自身作样本值。
    import sys
    bad = 0
    for c in CASES:
        tool = c["expect_tool"][0]
        args = {}
        for k, m in c.get("expect_args", {}).items():
            if callable(m):
                continue  # 自定义逻辑,人工核对
            args[k] = m[0] if isinstance(m, list) else m
        r = evaluate_output(c, tool, args)
        if r["args_score"] < 1.0 and c.get("expect_args"):
            print(f"[?] {c['id']}: {r['detail']}", file=sys.stderr)
            bad += 1
    print(f"self-check: {total_cases()} cases, {bad} need manual review")
