# -*- coding: utf-8 -*-
"""基准评分(judge):复用 ai_testset.evaluate_output,补充"瞎编检测"和汇总。

对每条用例的模型输出 {name, arguments} 打分:
  name_ok    1.0/0.0  工具名命中期望
  args_score 0~1      期望参数匹配比例
  halluc     bool     是否瞎编(instance/server/snapshot_id 不在声明列表里)
  detail     str      逐参数说明
"""
import os
import sys
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from launcher_app.ai.ai_testset import evaluate_output, norm, _INSTANCE_ALIASES

# 声明的合法值(与 testset/single.py 对齐)——瞎编检测用
KNOWN_INSTANCES = {"neoforge-21.1.248", "fabric-1.21.1", "vanilla-1.20.1"}
KNOWN_SERVER_KEYWORDS = ("paper", "测试服", "test-server", "paper-1.21.1")

# 这些参数若填了"不存在的值"就算瞎编
_HALLUC_KEYS = ("instance", "server", "snapshot_id", "filename", "project")


def _hallucinated(tool_name: str, args: dict) -> list:
    """返回瞎编的字段列表(instance/server/snapshot_id 等填了不存在的值)。"""
    bad = []
    a = args or {}
    inst = a.get("instance")
    if isinstance(inst, str) and inst.strip():
        canon = _INSTANCE_ALIASES.get(norm(inst), norm(inst))
        if canon not in {norm(x) for x in KNOWN_INSTANCES}:
            bad.append(f"instance={inst!r}(不在声明实例内)")
    srv = a.get("server")
    if isinstance(srv, str) and srv.strip():
        if not any(k in norm(srv) for k in KNOWN_SERVER_KEYWORDS):
            bad.append(f"server={srv!r}(不在声明服务端内)")
    return bad


def score_case(case: dict, tool_name: str, args: dict) -> dict:
    """评分一条用例。返回 {name_ok, args_score, halluc, detail}。"""
    base = evaluate_output(case, tool_name or "", args or {})
    halluc = _hallucinated(tool_name, args or {})
    return {
        "id": case["id"],
        "tag": case.get("tag", "other"),
        "name_ok": base["name_ok"],
        "args_score": base["args_score"],
        "halluc": bool(halluc),
        "halluc_detail": "; ".join(halluc),
        "detail": base["detail"],
        "tool": tool_name,
    }


def summarize(results: list) -> dict:
    """汇总:整体 + 按 tag 的工具名命中率/参数分/瞎编率。"""
    if not results:
        return {}
    n = len(results)
    name_hits = sum(r["name_ok"] for r in results)
    args_sum = sum(r["args_score"] for r in results)
    halluc_n = sum(1 for r in results if r["halluc"])
    by_tag = {}
    for r in results:
        t = by_tag.setdefault(r["tag"], {"n": 0, "name": 0.0, "args": 0.0, "halluc": 0})
        t["n"] += 1
        t["name"] += r["name_ok"]
        t["args"] += r["args_score"]
        t["halluc"] += 1 if r["halluc"] else 0
    return {
        "n": n,
        "name_acc": name_hits / n,
        "args_avg": args_sum / n,
        "halluc_rate": halluc_n / n,
        "by_tag": {k: {
            "n": v["n"],
            "name_acc": v["name"] / v["n"],
            "args_avg": v["args"] / v["n"],
            "halluc_rate": v["halluc"] / v["n"],
        } for k, v in by_tag.items()},
    }
