# -*- coding: utf-8 -*-
"""
版本树:把 Mojang 版本清单按大版本分类填进树。
主窗口和"下载新实例"选项卡共用,所以独立成模块,避免循环导入。
"""
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHeaderView, QTreeWidget, QTreeWidgetItem

from ui_style import muted_color

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
    # 版本列加宽且可拖(拉伸占满剩余宽度);年月列固定窄列、紧贴版本列右侧,
    # 位置固定不随窗口漂移,年月左边不留空隙
    tree.setColumnWidth(0, 440)
    tree.setColumnWidth(1, 72)
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
        """加一个版本叶子:第 0 列版本(黄金版本加 🏅),第 1 列灰色年月(左对齐贴版本列)"""
        star = " 🏅" if v["id"] in GOLDEN_VERSIONS else ""
        item = QTreeWidgetItem([f"{v['id']}  ({v['type']}){star}",
                                v.get("releaseTime", "")[:7]])
        item.setData(0, Qt.ItemDataRole.UserRole, v)
        item.setForeground(1, QColor(muted_color()))  # 灰色年月(次要色)
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        parent.addChild(item)
        return item

    tree.clear()
    for m, bucket in majors.items():   # majors 保持清单顺序 = 新的大版本在前
        # 大版本节点本身可点(折叠时点它 → 选中推荐具体版;展开可精确选)。
        # 用单独标记 {"__major__": m} 方便外部区分"大版本分组节点"与"具体版叶子"。
        root = make_tree_node(f"{m}.xx")
        root.setFlags(root.flags() | Qt.ItemFlag.ItemIsSelectable)
        rec = recommended_version(m, bucket["release"])
        root.setData(0, Qt.ItemDataRole.UserRole, {"__major__": m, "recommended": rec})
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


def releases_grouped_by_major(manifest: dict) -> dict:
    """把正式版按大版本分桶(releases_in_major,新→旧)。快照忽略(资源筛选只要正式版)。"""
    grouped = {}
    for v in manifest["versions"]:
        if v["type"] != "release":
            continue
        m = major_version(v["id"])
        if m is None:
            continue
        grouped.setdefault(m, []).append(v)
    return grouped


def recommended_version(major: str, release_list: list) -> str:
    """给定某大版本的正式版列表(新→旧),返回推荐的具体版:
    优先该大版本里的黄金版(GOLDEN_VERSIONS);没有黄金版 → 该大版本最新正式版。"""
    for v in release_list:
        if v["id"] in GOLDEN_VERSIONS:
            return v["id"]
    return release_list[0]["id"] if release_list else ""


class GameVersionTree(QTreeWidget):
    """可复用的「游戏版本」选择树(手动下载卡 / 资源筛选用):
    顶层是「无(全部版本)」+ 各大版本,每个大版本下挂正式版明细;
    点大版本(不展开)→ 自动选中它的推荐版(GOLDEN_VERSIONS 优先,否则最新);
    展开可精确选某正式版。选中变化发 version_changed(带当前具体版 or "")。"""
    version_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("filter_version")      # 教程定位复用(原顶部筛选的 objectName)
        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setAlternatingRowColors(False)
        self.setVerticalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)   # 逐像素滚动,触控板更顺
        self.setHorizontalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self.header().setStretchLastSection(True)
        self.currentItemChanged.connect(self._on_current_changed)
        self._none_item = None

    def populate(self, manifest: dict, none_label: str = "无(全部版本)"):
        """用版本清单填树。选中的版本值是 UserRole 里的具体版字符串;"" = 无(全部)。"""
        self.clear()
        self._none_item = QTreeWidgetItem([none_label])
        self._none_item.setData(0, Qt.ItemDataRole.UserRole, "")
        self.addTopLevelItem(self._none_item)
        grouped = releases_grouped_by_major(manifest)
        for major, releases in grouped.items():   # 新→旧
            rec = recommended_version(major, releases)
            root = QTreeWidgetItem([f"{major}.xx(推荐 {rec})"])
            root.setData(0, Qt.ItemDataRole.UserRole, major)
            self.addTopLevelItem(root)
            for v in releases:
                leaf = QTreeWidgetItem([v["id"]])
                leaf.setData(0, Qt.ItemDataRole.UserRole, v["id"])
                root.addChild(leaf)
            root.setExpanded(False)
        self.setCurrentItem(self._none_item)

    def _on_current_changed(self, cur, _prev):
        if cur is None:
            return
        v = cur.data(0, Qt.ItemDataRole.UserRole)
        # 大版本节点被点中(未展开明细):自动选它的推荐具体版
        if isinstance(v, str) and v:
            # 找到该大版本下 = 推荐版 的叶子并选中(不发重复信号)
            rec = self._recommended_of(cur)
            leaf = self._find_leaf(cur, rec)
            if leaf is not None:
                self.blockSignals(True)
                self.setCurrentItem(leaf)
                self.blockSignals(False)
                self.version_changed.emit(leaf.data(0, Qt.ItemDataRole.UserRole))
                return
        self.version_changed.emit(v or "")

    @staticmethod
    def _recommended_of(root) -> str:
        # 解析 root 文本里的 "(推荐 x)" 或直接算
        import re
        m = re.search(r"推荐 ([^\s)]+)", root.text(0))
        if m:
            return m.group(1)
        return ""

    @staticmethod
    def _find_leaf(root, version_str: str):
        if not version_str:
            return None
        for i in range(root.childCount()):
            ch = root.child(i)
            if ch.data(0, Qt.ItemDataRole.UserRole) == version_str:
                return ch
        return None

    def current_version(self) -> str:
        """当前选中的具体版本字符串;"" = 无(全部版本)。"""
        cur = self.currentItem()
        if cur is None:
            return ""
        v = cur.data(0, Qt.ItemDataRole.UserRole)
        return v or ""

    def select_version(self, version_str: str):
        """按具体版字符串选中对应叶子;找不到则回退到「无」。"""
        if not version_str:
            if self._none_item is not None:
                self.setCurrentItem(self._none_item)
            return
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            leaf = self._find_leaf(top, version_str)
            if leaf is not None:
                self.setCurrentItem(leaf)
                return
        if self._none_item is not None:
            self.setCurrentItem(self._none_item)
