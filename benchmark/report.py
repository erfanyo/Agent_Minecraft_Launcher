# -*- coding: utf-8 -*-
"""把 benchmark/results/*.json 汇总成 Markdown 对照报告。

用法:
  python report.py                  # 汇总所有已有结果 → benchmark/report.md
  python report.py --out X.md       # 指定输出

报告含:模型×维度对照表(工具选择/参数/瞎编/速度/加载),按分类明细,逐条可选。
"""
import argparse
import glob
import json
import os
import sys

_BENCH = os.path.dirname(os.path.abspath(__file__))


def load_results(res_dir=None):
    res_dir = res_dir or os.path.join(_BENCH, "results")
    out = []
    for p in sorted(glob.glob(os.path.join(res_dir, "*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                out.append(json.load(f))
        except Exception:
            pass
    return out


def _pct(x):
    return f"{x*100:.0f}%" if isinstance(x, (int, float)) else "-"


def build_report(results):
    lines = []
    lines.append("# 本地模型基准测试报告")
    lines.append("")
    lines.append(f"共 {len(results)} 个模型。维度:工具选择准确率 / 参数填充 / 瞎编率 / 速度(tok/s) / 加载(s)。")
    lines.append("")

    # ---- 总表 ----
    lines.append("## 模型 × 维度对照")
    lines.append("")
    lines.append("| 模型 | 参数 | 单步工具 | 单步参数 | 模糊理解 | **多步规划** | 瞎编率 | tok/s |")
    lines.append("|---|---|---|---|---|---|---|---|")
    # 按多步规划排序(多步最能看出差距)
    def _ms(d):
        ms = d.get("multistep", {})
        return sum(m.get("direction_hit", 0) for m in ms.values()) / len(ms) if ms else 0
    for d in sorted(results, key=lambda x: -_ms(x)):
        m = d.get("model", {})
        s = d.get("summary", {})
        fz = d.get("fuzzy_summary", {})
        sp = d.get("speed", {})
        fz_acc = fz.get("name_acc") if fz else None
        lines.append(
            f"| {m.get('name','?')} | {m.get('params','?')} "
            f"| {_pct(s.get('name_acc'))} | {_pct(s.get('args_avg'))} "
            f"| {_pct(fz_acc) if fz_acc is not None else '-'} "
            f"| **{_pct(_ms(d))}** "
            f"| {_pct(s.get('halluc_rate'))} | {sp.get('avg_tok_per_s',0):.0f} |")
    lines.append("")

    # ---- 按分类明细 ----
    lines.append("## 按分类明细(工具选择准确率)")
    lines.append("")
    tags = []
    for d in results:
        for t in d.get("summary", {}).get("by_tag", {}):
            if t not in tags:
                tags.append(t)
    if tags and results:
        lines.append("| 分类 | " + " | ".join(
            (d.get("model", {}).get("name", "?")[:12] for d in results)) + " |")
        lines.append("|---" * (len(results) + 1) + "|")
        for t in tags:
            row = [f"**{t}**"]
            for d in results:
                bt = d.get("summary", {}).get("by_tag", {}).get(t)
                row.append(_pct(bt["name_acc"]) if bt else "-")
            lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # ---- 每模型逐条(仅列错的,便于看差距) ----
    lines.append("## 错误明细(仅列工具选错的)")
    lines.append("")
    for d in results:
        m = d.get("model", {}).get("name", "?")
        wrong = [r for r in d.get("results", []) if not r["name_ok"]]
        if not wrong:
            lines.append(f"**{m}**:全对 🎉")
            lines.append("")
            continue
        lines.append(f"**{m}**({len(wrong)} 条选错):")
        for r in wrong:
            lines.append(f"- `{r['id']}`:想用 `{r['detail'][:1]}`,实际 `{r['tool']}` "
                         f"(参数 {r['args_score']:.0%}{', 瞎编' if r['halluc'] else ''})")
        lines.append("")

    # ---- 多步决策链(供人工面试) ----
    ms_ids = []
    for d in results:
        for k in d.get("multistep", {}):
            if k not in ms_ids:
                ms_ids.append(k)
    if ms_ids:
        lines.append("## 多步决策链(供面试,按 rubric.md 打 A/B/C/D)")
        lines.append("")
        for sid in ms_ids:
            # 找这个剧本的 note/期望
            ref = None
            for d in results:
                if sid in d.get("multistep", {}):
                    ref = d["multistep"][sid]
                    break
            if ref:
                lines.append(f"### {sid} · {ref['user']}")
                lines.append(f"*{ref['note']}  期望:{ref['expect_final']}*")
                lines.append("")
                for d in results:
                    m = d.get("multistep", {}).get(sid)
                    if not m:
                        continue
                    name = d.get("model", {}).get("name", "?")
                    lines.append(f"**{name}** [{m.get('auto_hint','')}]")
                    for c in m.get("chain", []):
                        ok = "✓" if c["direction_ok"] else ("?" if c["direction_ok"] is None else "✗")
                        lines.append(f"- 步{c['step']}: {ok} `{c['tool']}` {json.dumps(c['args'], ensure_ascii=False)}")
                    lines.append(f"  - 面试评级:___  备注:___")
                lines.append("")

    lines.append("---")
    lines.append("*工具选择=期望工具命中率;参数填充=期望参数匹配比例;瞎编率=填了不存在的实例/服务端。*")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(_BENCH, "report.md"))
    args = ap.parse_args()
    results = load_results()
    if not results:
        print("没有结果(先跑 runner.py)"); return 1
    md = build_report(results)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"报告已写 {args.out}({len(results)} 个模型)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
