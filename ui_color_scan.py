# -*- coding: utf-8 -*-
"""硬编码色值扫描器(阶段 0 / 阶段 4 复用):扫描项目 .py 里的 hex / rgba 色值,
按"主题 token 候选" vs "数据调色板(白名单豁免)" vs "豁免项"分类。

阶段 0 用:产出迁移清单(哪些色值应迁到 ui_tokens.py,哪些是合法数据调色板)。
阶段 4 用:验收标准 4「无散落硬编码色值」——白名单外的色值 = 待迁。

用法:
    python ui_color_scan.py            # 全量报告(分组 + 摘要)
    python ui_color_scan.py --csv      # 每处一行 file,line,color(便于 grep/CI)
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

# 扫描时排除的目录(依赖/产物/数据/生成物)
EXCLUDE_DIRS = {
    ".venv", ".git", "build", "dist", ".minecraft", "__pycache__",
    ".mypy_cache", ".tmp", ".agent-teams", ".github", "bridge-mod",
    "node_modules", "AMCL", "test_modpack", "DPH_Chat",
}

# 数据调色板(非主题 token)——豁免白名单:这些色值是"数据/自绘内容",不应迁 token。
# 结构: color(小写) -> 说明
DATA_PALETTE_WHITELIST = {
    # 头像/封面/图标生成调色板
    "#5b8def": "头像/封面生成调色板(version_home.py _AVATAR_PALETTE / main.py 随机头像)",
    "#6bcb77": "头像生成调色板",
    "#ff6b6b": "头像生成调色板",
    "#ffd93d": "头像生成调色板",
    "#b980f0": "头像生成调色板",
    "#4ecdc4": "头像生成调色板",
    "#f78fb3": "头像生成调色板",
    "#82b74b": "头像生成调色板",
    "#e07b54": "头像生成调色板",
    "#3e7cb1": "头像生成调色板(也是下载环主色,见下)",
    # 教程草方块(自绘像素风)
    "#7cbf4a": "tutorial_intro 草方块自绘色",
    "#6fb043": "tutorial_intro 草方块自绘色",
    "#63a13c": "tutorial_intro 草方块自绘色",
    "#57a036": "tutorial_intro 草方块自绘色",
    "#5a9633": "tutorial_intro 草方块自绘色",
    "#4e822c": "tutorial_intro 草方块自绘色",
    "#8a5a35": "tutorial_intro 泥土自绘色",
    "#7d4e2e": "tutorial_intro 泥土自绘色",
    "#6f4526": "tutorial_intro 泥土自绘色",
    "#7a4e2e": "tutorial_intro 泥土自绘色",
    "#84552f": "tutorial_intro 泥土自绘色",
    "#5e3a20": "tutorial_intro 泥土自绘色",
    # Mod 依赖力导向图(数据语义:正常/禁用/缺失/关系类型)
    "#4a90d9": "mod_graph 节点色(normal)",
    "#9aa0a6": "mod_graph 节点色(disabled)",
    "#e05b5b": "mod_graph 节点色(missing)",
    "#6e8fbf": "mod_graph 关系线(required)",
    "#20262e": "mod_graph 图背景",
    "#1e2430": "mod_graph view 背景",
    # 下载环形指示器(自绘,主题无关的固定蓝)
    "#9fd0f0": "download_indicator 环形进度色",
    # SVG 图标模板占位色(theme_icon._tint 会替换为当前主题色)
    "#000": "theme_icon SVG 着色占位符(被 _tint 替换,非主题色)",
    # 教程 HTML 内联样式(内容数据)
    "#2a3240": "tutorial_gui 内联 HTML(分隔线/卡片底)",
    "#e8ecf2": "tutorial_gui 内联 HTML 文字(也是通用浅色文字,见候选区)",
    # 白色/主题无关 + 半透明灰浮层 + 深色画布/浮层 + 防御性 fallback
    "#ffffff": "绝对白(强调底白字 / 深色画布 / 浅色输入底)——主题无关",
    "rgba(128,128,128,90)": "assistant_ui 语音/截图按钮半透明灰悬停底",
    "rgba(128,128,128,160)": "assistant_ui 语音/截图按钮半透明灰按下底",
    "#2e5a85": "assistant_ui 发送按钮按下蓝(独立蓝系)",
    "#555": "changelog HTML 3 位灰(次要文字)",
    "#3a4556": "guide_overlay 深色遮罩控制条边框(spotlight 浮层)",
    "#232e3a": "tutorial_intro 深色卡片底",
    "#d6dde6": "tutorial_intro 深色卡片文字",
    "#aab3c0": "深色画布次级文字(mod_graph 搜索态 / 教程 HTML)",
    "#2b2f3a": "resource_center 占位图标深色底(自绘占位)",
    "#c6cdd8": "教程 HTML 次级文字",
    "#e7ecf5": "changelog fallback 正文(= text 深色默认,防御性回退)",
    "#8b96a8": "changelog fallback 次要(= muted 深色默认,防御性回退)",
    "#23272f": "changelog fallback 窗口底(= bg1 深色默认,防御性回退)",
    "#f5f6f9": "changelog fallback 浅色窗口底(= bg1 浅色默认,防御性回退)",
    "#1a1d23": "changelog fallback 输入底(= bg0 深色默认,防御性回退)",
    "rgba(255,255,255,0.90)": "main.py 拖入文件覆盖层:整窗发白(白色浮层底,主题无关)",
    "#222": "main.py 拖入覆盖层深色文字(白色浮层上的文字,3 位灰)",
}

# 豁免项:文档明确"不动"或属于样式/token 定义层(登记但不算违规)
EXEMPT_FILES = {
    "frameless_titlebar.py": "文档明确「标题栏样式不动」,硬编码 #e7ecf5/#c6cdd8 等保留",
    "ui_tokens.py": "设计 token 单一数据源(色值定义本身)",
    "ui_style.py": "样式层:色弱预设/全局调色板/可读性基准/旧兼容 card_style 的字面值(定义层,非散落)",
}

# (?<!&)# 排除 HTML 实体 &#128218;(📚 emoji)等被误报为色值
HEX_RE = re.compile(r"(?<!&)#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
RGBA_RE = re.compile(r"rgba?\(\s*[0-9]{1,3}\s*,\s*[0-9]{1,3}\s*,\s*[0-9]{1,3}(?:\s*,\s*[0-9.]+)?\s*\)")


def iter_py_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn.endswith(".py") and fn not in ("ui_color_scan.py", "ui_bench.py"):
                yield os.path.join(dirpath, fn)


def scan() -> dict:
    """返回 {color_lower: [(file, line, raw_color), ...]}"""
    found = {}
    for path in iter_py_files():
        rel = os.path.relpath(path, ROOT)
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            continue
        for lineno, line in enumerate(lines, 1):
            for m in HEX_RE.finditer(line):
                c = m.group(0).lower()
                found.setdefault(c, []).append((rel, lineno, m.group(0)))
            for m in RGBA_RE.finditer(line):
                # 归一化 rgba 内的空格
                raw = m.group(0)
                norm = re.sub(r"\s+", "", raw).lower()
                found.setdefault(norm, []).append((rel, lineno, raw))
    return found


def classify(found: dict) -> dict:
    cats = {"token_candidates": {}, "whitelisted": {}, "exempt": {}}
    for color, occ in found.items():
        if color in DATA_PALETTE_WHITELIST:
            cats["whitelisted"][color] = occ
            continue
        # 若所有出现都在豁免文件里 → exempt
        files = {f for f, _l, _r in occ}
        if files and all(f in EXEMPT_FILES for f in files):
            cats["exempt"][color] = occ
            continue
        cats["token_candidates"][color] = occ
    return cats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true", help="每处一行 file,line,color")
    args = ap.parse_args()

    found = scan()
    cats = classify(found)

    if args.csv:
        for color, occ in sorted(found.items()):
            for f, line, raw in occ:
                cat = ("whitelist" if color in DATA_PALETTE_WHITELIST
                       else "exempt" if f in EXEMPT_FILES else "candidate")
                print(f"{cat},{f},{line},{color}")
        return 0

    total_occ = sum(len(o) for o in found.values())
    print(f"== 硬编码色值扫描 == 唯一色值 {len(found)} 个 / 出现 {total_occ} 处\n")

    def _dump(title, d):
        print(f"\n### {title}({len(d)} 个色值 / {sum(len(o) for o in d.values())} 处)")
        for color, occ in sorted(d.items(), key=lambda kv: -len(kv[1])):
            files = sorted({f for f, _l, _r in occ})
            print(f"  {color:<24} x{len(occ):<3} {', '.join(files[:4])}"
                  f"{'...' if len(files) > 4 else ''}")
            if color in DATA_PALETTE_WHITELIST:
                print(f"    ├ 白名单: {DATA_PALETTE_WHITELIST[color]}")
            # 列出少量样本行号(最多 6 处)
            for f, line, _raw in occ[:6]:
                print(f"    ├ {f}:{line}")
            if len(occ) > 6:
                print(f"    └ ... 还有 {len(occ) - 6} 处")

    _dump("主题 token 候选(需迁 ui_tokens.py)", cats["token_candidates"])
    _dump("数据调色板(白名单豁免,不迁)", cats["whitelisted"])
    _dump("豁免文件(标题栏等,登记不迁)", cats["exempt"])

    print(f"\n== 摘要 == 候选 {sum(len(o) for o in cats['token_candidates'].values())} 处 / "
          f"白名单 {sum(len(o) for o in cats['whitelisted'].values())} 处 / "
          f"豁免 {sum(len(o) for o in cats['exempt'].values())} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
