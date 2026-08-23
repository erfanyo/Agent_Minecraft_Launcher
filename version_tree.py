# -*- coding: utf-8 -*-
"""
版本树:把 Mojang 版本清单按大版本分类填进树。
主窗口和"下载新实例"选项卡共用,所以独立成模块,避免循环导入。
"""
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHeaderView, QTreeWidget, QTreeWidgetItem

# 黄金版本:模组生态最活跃的经典版本(灵感 #1,静态列表版)。
# 经典版本几乎不再变动,没必要实时统计;以后想加版本直接往这里添一行。
GOLDEN_VERSIONS = {
    "1.7.10", "1.8.9", "1.12.2", "1.16.5",
    "1.18.2", "1.19.2", "1.20.1", "1.21.1",
}

# 大版本划分规则(配着例子看更好懂):
#   旧体系(第一段是 1):"1.21.4" → "1.21"(取前两段)
#   新体系(26 起,如 26.2):"26.2" → "26"(只取第一段,整个 26.x 算一个大版本)
#   "26.3-snapshot-9" → 去掉 "-snapshot-9" 后缀 → "26"
#   "25w14a"          → 不是数字版本号,返回 None,交给时间映射处理
def major_version(version_id: str) -> str | None:
    base = version_id.split("-")[0]  # 去掉 "-xxx" 后缀
    parts = base.split(".")
    if len(parts) >= 2 and all(p.isdigit() for p in parts[:2]):
        if parts[0] == "1":     # 旧体系:1.21.4 → 1.21
            return ".".join(parts[:2])
        return parts[0]         # 新体系:26.2 → 26
    return None  # 提取不出大版本(如周快照 25w14a)


def snapshot_target_major(snapshot_time: str, releases_sorted: list) -> str:
    """周快照(如 25w14a)名字里没有版本号,但它预览的是"发布晚于它"的第一个正式版。
    找到那个正式版,取它的大版本,周快照就归到那里。"""
    st = datetime.fromisoformat(snapshot_time)
    for r in releases_sorted:
        if datetime.fromisoformat(r["releaseTime"]) > st:
            return major_version(r["id"])
    # 它的目标版本还没发布(如当前开发中的新大版本):先归到最新正式版的大版本
    return major_version(releases_sorted[-1]["id"])


def make_tree_node(title):
    """建一个分类节点(不可选中)。注意:展开状态要在节点挂到树之后再设置(Qt 的坑)。"""
    node = QTreeWidgetItem([title])
    node.setFlags(node.flags() & ~Qt.ItemFlag.ItemIsSelectable)
    return node


def fill_version_tree(tree: QTreeWidget, manifest: dict) -> tuple:
    """把 Mojang 版本清单按大版本分类填进树。
    返回 (正式版数, 快照数, 远古数, 愚人节数)。"""
    tree.setColumnCount(2)
    tree.setHeaderLabels(["版本", "发布年月"])
    # 版本列加宽且可拖;年月列固定宽度(够完整显示"2025-06"+表头,右对齐但留出右缘边距)
    tree.setColumnWidth(0, 440)
    tree.setColumnWidth(1, 100)
    header = tree.header()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)

    # 愚人节版本:4 月 1 日发布且不是正式版(如 20w14infinite、23w13a_or_b)
    april_fools = [v for v in manifest["versions"]
                   if v.get("releaseTime", "")[5:10] == "04-01"
                   and v["type"] != "release"]

    # 先把正式版按发布时间排好:用来给"周快照"(如 25w14a)找归属
    releases_sorted = sorted(
        (v for v in manifest["versions"] if v["type"] == "release"),
        key=lambda v: datetime.fromisoformat(v["releaseTime"]),
    )

    majors = {}    # 大版本 -> {"release": [...], "snapshot": [...]}
    ancients = []  # 远古版本(alpha/beta)单独一桶
    for v in manifest["versions"]:
        if v in april_fools:
            continue  # 愚人节版本单独分类
        vtype = v["type"]
        if vtype in ("release", "snapshot"):
            m = major_version(v["id"])
            if m is None:  # 25w14a 这类周快照:按时间找它预览的正式版的大版本
                m = snapshot_target_major(v["releaseTime"], releases_sorted)
            bucket = majors.setdefault(m, {"release": [], "snapshot": []})
            bucket[vtype].append(v)
        else:
            ancients.append(v)

    def _leaf(parent, v):
        """加一个版本叶子:第 0 列版本(黄金版本加 🏅),第 1 列灰色年月(右对齐)"""
        star = " 🏅" if v["id"] in GOLDEN_VERSIONS else ""
        item = QTreeWidgetItem([f"{v['id']}  ({v['type']}){star}",
                                v.get("releaseTime", "")[:7]])
        item.setData(0, Qt.ItemDataRole.UserRole, v)
        item.setForeground(1, QColor("#999999"))  # 灰色年月
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        parent.addChild(item)
        return item

    tree.clear()
    for m, bucket in majors.items():   # majors 保持清单顺序 = 新的大版本在前
        root = make_tree_node(f"{m}.xx")
        for v in bucket["release"]:
            _leaf(root, v)
        if bucket["snapshot"]:
            snap_node = make_tree_node("预览版")
            for v in bucket["snapshot"]:
                _leaf(snap_node, v)
            root.addChild(snap_node)
        tree.addTopLevelItem(root)

    ancients_root = make_tree_node(f"远古版本(alpha/beta, {len(ancients)} 个)")
    for v in ancients:
        _leaf(ancients_root, v)
    tree.addTopLevelItem(ancients_root)

    # 愚人节版本:单独折叠分类
    if april_fools:
        april_root = make_tree_node(f"愚人节版本({len(april_fools)} 个)")
        for v in april_fools:
            _leaf(april_root, v)
        tree.addTopLevelItem(april_root)

    # 展开/折叠:必须等节点全部挂到树之后再设置,否则不生效(Qt 的坑)
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        top.setExpanded(i == 0)  # 只展开最新的大版本
        for j in range(top.childCount()):
            child = top.child(j)
            if child.text(0) in ("预览版",):
                child.setExpanded(False)

    return sum(len(b["release"]) for b in majors.values()), \
        sum(len(b["snapshot"]) for b in majors.values()), len(ancients), len(april_fools)
