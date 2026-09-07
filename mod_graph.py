# -*- coding: utf-8 -*-
"""
Mod 依赖网络渲染(简单版):QGraphicsView/QGraphicsScene 画节点(mid)+ 边(依赖),
带简单的力导向布局 + 拖拽平移 + 滚轮缩放。无第三方依赖。

数据来自 mod_deps.build_graph()(离线解析 jar 元数据)。这版先画"能看懂的网",
后续想更华丽(曲线边/图标/筛选/图片节点)可在此类上增强,数据层不变。
"""
import math

from PySide6.QtCore import QRectF, Qt, QPointF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QFontMetricsF, QPolygonF, QPainterPath
from PySide6.QtWidgets import (
    QDialog, QGraphicsView, QGraphicsScene, QGraphicsItem, QLabel, QVBoxLayout, QHBoxLayout,
    QCheckBox, QLineEdit, QPushButton,
)

import mod_deps as md


# 节点/边配色
_NODE_COL = {"normal": QColor("#4A90D9"), "disabled": QColor("#9AA0A6"), "missing": QColor("#E05B5B")}
_EDGE_COL = {
    md.REQUIRED: (QColor("#6E8FBF"), Qt.PenStyle.SolidLine),
    md.OPTIONAL: (QColor("#9AA0A6"), Qt.PenStyle.DashLine),
    md.INCOMPATIBLE: (QColor("#E05B5B"), Qt.PenStyle.DashLine),
}
_ARROW_LEN = 10.0
_PAD = 86.0


def _node_label_lines(text: str, font: QFont, max_text_width: float = 184.0) -> list[str]:
    """把较长 Mod 名按字符宽度拆为最多两行，保留 tooltip 作为极长名称兜底。"""
    text = text or "(未命名 Mod)"
    fm = QFontMetricsF(font)
    if fm.horizontalAdvance(text) <= max_text_width:
        return [text]
    lines, current = [], ""
    for char in text:
        candidate = current + char
        if current and fm.horizontalAdvance(candidate) > max_text_width:
            lines.append(current)
            current = char
            if len(lines) == 1:
                continue
            break
        current = candidate
    if len(lines) < 2 and current:
        lines.append(current)
    # 两行仍放不下时，第二行省略；完整名称始终可通过 tooltip 查看。
    consumed = sum(len(line) for line in lines)
    if consumed < len(text):
        lines[-1] = fm.elidedText(text[len(lines[0]):], Qt.TextElideMode.ElideRight, max_text_width)
    return lines[:2]


def _node_size(node: md.ModNode, font: QFont) -> tuple[float, float]:
    fm = QFontMetricsF(font)
    lines = _node_label_lines(node.name, font)
    width = max(76.0, max(fm.horizontalAdvance(line) for line in lines) + 18.0)
    return min(width, 202.0), max(28.0, len(lines) * math.ceil(fm.height()) + 10.0)


def _fit_positions_to_scene(pos: dict, sizes: dict) -> tuple[dict, float, float]:
    """按实际布局范围扩展场景并平移到正坐标，避免把外圈节点硬挤到边界。"""
    if not pos:
        return {}, 900.0, 620.0
    min_x = min(x - sizes.get(nid, (90.0, 30.0))[0] / 2 for nid, (x, _y) in pos.items())
    max_x = max(x + sizes.get(nid, (90.0, 30.0))[0] / 2 for nid, (x, _y) in pos.items())
    min_y = min(y - sizes.get(nid, (90.0, 30.0))[1] / 2 for nid, (_x, y) in pos.items())
    max_y = max(y + sizes.get(nid, (90.0, 30.0))[1] / 2 for nid, (_x, y) in pos.items())
    shifted = {nid: (x - min_x + _PAD, y - min_y + _PAD) for nid, (x, y) in pos.items()}
    return shifted, max(900.0, max_x - min_x + 2 * _PAD), max(620.0, max_y - min_y + 2 * _PAD)


def _has_overlaps(pos: dict, nodes: list, sizes: dict) -> bool:
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            aw, ah = sizes.get(a, (90.0, 30.0)); bw, bh = sizes.get(b, (90.0, 30.0))
            if abs(pos[a][0] - pos[b][0]) < (aw + bw) / 2 + 8 and \
               abs(pos[a][1] - pos[b][1]) < (ah + bh) / 2 + 8:
                return True
    return False


def _separate_overlaps(pos: dict, nodes: list, sizes: dict, width: float, height: float) -> None:
    """布局收敛后的局部矩形避让，不改变网络整体的力导向结构。"""
    for _ in range(260):
        moved = False
        delta = {nid: [0.0, 0.0] for nid in nodes}
        for i, a in enumerate(nodes):
            for j in range(i + 1, len(nodes)):
                b = nodes[j]
                aw, ah = sizes.get(a, (90.0, 30.0)); bw, bh = sizes.get(b, (90.0, 30.0))
                dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
                ox = (aw + bw) / 2 + 10.0 - abs(dx)
                oy = (ah + bh) / 2 + 10.0 - abs(dy)
                if ox <= 0 or oy <= 0:
                    continue
                moved = True
                # 沿原有连心线微调，不按固定横纵轴塞成方格。
                distance = math.hypot(dx, dy)
                if distance < 0.01:
                    angle = (i * 0.618 + j * 1.732) % (2 * math.pi)
                    ux, uy = math.cos(angle), math.sin(angle)
                else:
                    ux, uy = dx / distance, dy / distance
                push = min(max(ox, oy) / 2 + 0.35, 12.0)
                delta[a][0] += ux * push; delta[a][1] += uy * push
                delta[b][0] -= ux * push; delta[b][1] -= uy * push
        for nid in nodes:
            pos[nid][0] += delta[nid][0]
            pos[nid][1] += delta[nid][1]
        if not moved:
            break
    # 极密组件仍有少量碰撞时整体等比松开，而不是退化成方格；边的相对关系保留。
    for _ in range(8):
        if not _has_overlaps(pos, nodes, sizes):
            break
        cx = sum(pos[n][0] for n in nodes) / max(len(nodes), 1)
        cy = sum(pos[n][1] for n in nodes) / max(len(nodes), 1)
        for nid in nodes:
            pos[nid][0] = cx + (pos[nid][0] - cx) * 1.13
            pos[nid][1] = cy + (pos[nid][1] - cy) * 1.13


def _force_layout(nodes: list, edges: list, width: float, height: float,
                  sizes: dict | None = None, iterations: int = 150) -> dict:
    """轻量力导向布局(Fruchterman-Reingold 简化):返回 {mod_id: (x, y)}。
    初始按圆周分布(确定性),迭代松弛后回缩到边界。少数节点也稳定。"""
    n = len(nodes)
    if n == 0:
        return {}
    if n == 1:
        return {nodes[0]: (width / 2, height / 2)}
    cx, cy = width / 2, height / 2
    r = min(width, height) * 0.4
    pos = {}
    for i, nid in enumerate(nodes):
        ang = 2 * math.pi * i / n
        pos[nid] = [cx + r * math.cos(ang), cy + r * math.sin(ang)]
    sizes = sizes or {}
    k = math.sqrt(width * height / n) * 0.92  # 理想边长
    temperature = k * 0.18
    for _ in range(iterations):
        disp = {nid: [0.0, 0.0] for nid in nodes}
        # 斥力
        for i in range(n):
            a = nodes[i]
            for j in range(i + 1, n):
                b = nodes[j]
                dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
                # 节点不是点：把标签矩形的半宽/半高也算进最小间距。
                aw, ah = sizes.get(a, (90.0, 30.0)); bw, bh = sizes.get(b, (90.0, 30.0))
                need_x, need_y = (aw + bw) / 2 + 16.0, (ah + bh) / 2 + 14.0
                if abs(dx) < need_x and abs(dy) < need_y:
                    # 已重叠时沿更容易分开的轴额外推开，专门解决边缘节点相压。
                    if need_x - abs(dx) < need_y - abs(dy):
                        ux, uy = (1.0 if dx >= 0 else -1.0), 0.0
                    else:
                        ux, uy = 0.0, (1.0 if dy >= 0 else -1.0)
                    push = min(k * 0.42, 70.0)
                    disp[a][0] += ux * push; disp[a][1] += uy * push
                    disp[b][0] -= ux * push; disp[b][1] -= uy * push
                d = max(math.hypot(dx, dy), math.hypot(need_x, need_y) * 0.52, 0.01)
                f = k * k / d
                raw_d = math.hypot(dx, dy) or 0.01
                ux, uy = dx / raw_d, dy / raw_d
                disp[a][0] += ux * f; disp[a][1] += uy * f
                disp[b][0] -= ux * f; disp[b][1] -= uy * f
        # 引力(沿边)
        for (sa, sb) in edges:
            dx, dy = pos[sa][0] - pos[sb][0], pos[sa][1] - pos[sb][1]
            d = math.hypot(dx, dy) or 0.01
            f = d * d / k
            ux, uy = dx / d, dy / d
            disp[sa][0] -= ux * f; disp[sa][1] -= uy * f
            disp[sb][0] += ux * f; disp[sb][1] += uy * f
        # 应用 + 逐步冷却：早期先拉开，后期收敛，不会无限向外发散。
        for nid in nodes:
            # 轻微向心力，避免所有外围节点长期撞在硬边界上排成一堵墙。
            disp[nid][0] += (cx - pos[nid][0]) * 0.08
            disp[nid][1] += (cy - pos[nid][1]) * 0.08
            dx, dy = disp[nid]
            d = math.hypot(dx, dy) or 0.01
            step = min(d, temperature)
            pos[nid][0] += dx / d * step
            pos[nid][1] += dy / d * step
        temperature *= 0.94
    _separate_overlaps(pos, nodes, sizes, width, height)
    return {nid: (pos[nid][0], pos[nid][1]) for nid in nodes}


class _NodeItem(QGraphicsItem):
    def __init__(self, node: md.ModNode, x: float, y: float, font: QFont):
        super().__init__()
        self.node = node
        self._font = font
        fm = QFontMetricsF(font)
        self._lines = _node_label_lines(node.name, font)
        self._w, self._h = _node_size(node, font)
        self.setPos(x - self._w / 2, y - self._h / 2)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setToolTip(f"{node.name}  ({node.mod_id})\n"
                        f"文件:{node.file or '(缺失,未安装)'}\n"
                        f"加载器:{node.loader or '-'}  版本:{node.version or '-'}\n"
                        f"{'已禁用' if not node.enabled else '已启用'}"
                        f"{'  ·  ⚠ 缺失' if node.missing else ''}\n"
                        f"{'点击高亮:看它依赖谁 / 谁依赖它'}")
        self._on_click = None

    def set_click_handler(self, fn):
        self._on_click = fn

    def mousePressEvent(self, ev):
        super().mousePressEvent(ev)
        if self._on_click:
            self._on_click(self.node.mod_id)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._w, self._h)

    def paint(self, p: QPainter, *_):
        state = "missing" if self.node.missing else ("disabled" if not self.node.enabled else "normal")
        color = _NODE_COL[state]
        p.setPen(QPen(QColor("#20262e"), 1))
        p.setBrush(QBrush(color))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.drawRoundedRect(self.boundingRect(), 5, 5)
        p.setPen(QColor("#ffffff"))
        p.setFont(self._font)
        line_h = QFontMetricsF(self._font).height()
        for i, line in enumerate(self._lines):
            rect = QRectF(4, 4 + i * line_h, self._w - 8, line_h)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, line)


class _EdgeItem(QGraphicsItem):
    def __init__(self, x1, y1, x2, y2, etype: str):
        super().__init__()
        self.p1 = QPointF(x1, y1)
        self.p2 = QPointF(x2, y2)
        color, style = _EDGE_COL.get(etype, _EDGE_COL[md.REQUIRED])
        self._pen = QPen(color, 1.6)
        self._pen.setStyle(style)
        self._color = color
        self.setZValue(-1)
        rect = QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)).adjusted(-8, -8, 8, 8)
        self._rect = rect

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, p: QPainter, *_):
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(self._pen)
        p.drawLine(self.p1, self.p2)
        # 箭头(在 target 端)
        dx, dy = self.p2.x() - self.p1.x(), self.p2.y() - self.p1.y()
        L = math.hypot(dx, dy) or 1
        ux, uy = dx / L, dy / L
        bx, by = self.p2.x() - ux * _ARROW_LEN, self.p2.y() - uy * _ARROW_LEN
        ang = math.atan2(dy, dx)
        a1 = ang + 2.6
        a2 = ang - 2.6
        tri = QPolygonF([QPointF(self.p2.x(), self.p2.y()),
                         QPointF(bx + math.cos(a1) * _ARROW_LEN * 0.6, by + math.sin(a1) * _ARROW_LEN * 0.6),
                         QPointF(bx + math.cos(a2) * _ARROW_LEN * 0.6, by + math.sin(a2) * _ARROW_LEN * 0.6)])
        p.setBrush(QBrush(self._color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(tri)


class _ZoomView(QGraphicsView):
    """支持滚轮缩放 + 双击/按钮缩放到视野的视图(AnchorUnderMouse 缩放)。"""

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self._fit_requested = True   # 首次 show 后自动 fitInView
        self._zoom_t = QTimer(self)
        self._zoom_t.setSingleShot(True)
        self._zoom_t.timeout.connect(self._do_fit)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def fit_now(self):
        self.resetTransform()
        self.fitInView(self.scene().itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def showEvent(self, ev):
        super().showEvent(ev)
        if self._fit_requested:
            self._fit_requested = False
            self._zoom_t.start(0)

    def _do_fit(self):
        try:
            self.fit_now()
        except Exception:
            pass


class ModDependencyGraphDialog(QDialog):
    """Mod 依赖网络对话框:蓝色=已装,灰=已禁用,红=缺失(被依赖但没装);
    实线=必须依赖,虚线=可选依赖 / 不兼容(红色虚线)。拖拽平移,滚轮缩放。

    大型整合包(几百个 mod)自动把画布按节点数放大 → 打开时整体 fit 缩小到一屏
    (不拥挤、能看到全貌),想看哪块就点节点高亮 / 放大到那一带。"""

    def __init__(self, inst_id: str, graph: md.ModGraph, parent=None):
        super().__init__(parent)
        # 这是面向复杂整合包的分析工作台，而非实例详情的附属弹窗。
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowTitle(f"Mod 依赖分析 — {inst_id}")
        self.setObjectName("mod_dependency_workspace")
        self.resize(1180, 760)
        self.setMinimumSize(900, 620)
        self._graph = graph
        self._focused_id = None

        font = QFont()
        font.setPointSize(9)
        node_ids = [nid for nid, node in graph.nodes.items()]
        edge_pairs = [(e.source, e.target) for e in graph.edges
                      if e.source in graph.nodes and e.target in graph.nodes \
                      and e.source != e.target]
        n = len(node_ids)
        # 画布按节点数扩大(避免几百个节点挤在一张小画布上):
        # 每 ~1 个节点大约需要边长 k ≈ sqrt(W*H/n)*0.9,这里直接按 sqrt(n) 线性放大。
        import math as _m
        # 宽标签节点需要比“点布局”更大的平均间距；画布增大由初始 fit 负责缩放，
        # 不会让打开图谱的第一眼更拥挤。
        node_sizes = {nid: _node_size(node, font) for nid, node in graph.nodes.items()}
        max_node_w = max((s[0] for s in node_sizes.values()), default=90.0)
        max_node_h = max((s[1] for s in node_sizes.values()), default=30.0)
        # 给长名称留足空间，但不强行按网格放大画布；相关 Mod 应优先保持相邻。
        node_scale = _m.sqrt(max(n, 1))
        canvas_w = max(1000, int(node_scale * 185), int(max_node_w * node_scale * 1.06 + 2 * _PAD))
        canvas_h = max(700, int(node_scale * 140), int(max_node_h * node_scale * 4.8 + 2 * _PAD))
        raw_pos = _force_layout(node_ids, edge_pairs, canvas_w, canvas_h, node_sizes)
        self._pos, canvas_w, canvas_h = _fit_positions_to_scene(raw_pos, node_sizes)

        self.scene = QGraphicsScene(self)
        self.scene.setSceneRect(0, 0, canvas_w, canvas_h)
        # 先画边,再画节点(节点盖住线端)
        self._edge_items = []   # (source, target, item)
        self._items = {}        # mod_id -> _NodeItem
        for e in graph.edges:
            if e.source not in self._pos or e.target not in self._pos or e.source == e.target:
                continue
            x1, y1 = self._pos[e.source]
            x2, y2 = self._pos[e.target]
            item = _EdgeItem(x1, y1, x2, y2, e.type)
            self.scene.addItem(item)
            self._edge_items.append((e.source, e.target, item))
        for nid, node in graph.nodes.items():
            if nid not in self._pos:
                continue
            x, y = self._pos[nid]
            item = _NodeItem(node, x, y, font)
            item.set_click_handler(self._focus_node)
            self.scene.addItem(item)
            self._items[nid] = item

        self.view = _ZoomView(self.scene, self)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.view.setBackgroundBrush(QBrush(QColor("#1e2430")))

        # ---- 顶部:定位搜索 + 缩放控制 ----
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入 mod 名 / id 回车定位(如 tacz、create、flywheel)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self._locate_from_search)
        self._search_status = QLabel("")
        self._search_status.setStyleSheet("color: #aab3c0;")
        self._search_status.setMaximumWidth(260)
        fit_btn = QPushButton("⌖ 适应")
        fit_btn.clicked.connect(self.view.fit_now)
        zin = QPushButton("＋")
        zin.setFixedWidth(32)
        zin.clicked.connect(lambda: self.view.scale(1.2, 1.2))
        zout = QPushButton("－")
        zout.setFixedWidth(32)
        zout.clicked.connect(lambda: self.view.scale(1 / 1.2, 1 / 1.2))
        clear_btn = QPushButton("取消高亮")
        clear_btn.clicked.connect(lambda: self._apply_highlight(None))
        self.focus_only = QCheckBox("专注模式")
        self.focus_only.setToolTip("选中节点后隐藏无关节点和连线，适合大型整合包逐块排查")
        self.focus_only.toggled.connect(lambda _checked: self._apply_highlight(self._focused_id))

        top = QHBoxLayout()
        top.addWidget(self.search_edit, 1)
        top.addWidget(self._search_status)
        top.addWidget(fit_btn)
        top.addWidget(zin)
        top.addWidget(zout)
        top.addWidget(self.focus_only)
        top.addWidget(clear_btn)

        # ---- 概览 ----
        st = graph.stats()
        overview = QLabel(
            f"共 {st['mods']} 个 Mod," 
            f"{st['edges']} 条依赖关系," 
            f"{st['missing']} 个缺失依赖"
            f"   ·   实例: {inst_id}")
        overview.setStyleSheet("color: #e8ecf2; font-weight: bold; background: transparent;")

        legend = QLabel(
            "● 蓝=已装  ·  ● 灰=已禁用  ·  ● 红=缺失(被依赖但没装)\n"
            "实线=必须依赖  ·  虚线=可选依赖  ·  红色虚线=不兼容冲突\n"
            "这是独立分析窗口：可保留打开并继续管理实例。拖拽平移、滚轮缩放；点节点高亮它和它依赖/被依赖的对象，"
            "大型整合包可开启「专注模式」隐藏无关节点。\n"
            "⚠ 注意:红色「缺失」也可能是整合包**主动去掉的选装/需自行编译资源**(如 voxy 为选装、需跑编译脚本),"
            "未必真缺——结合整合包说明判断,别盲目补装。")

        layout = QVBoxLayout(self)
        layout.addWidget(overview)
        layout.addLayout(top)
        layout.addWidget(self.view, 1)
        layout.addWidget(legend)

    # ---- 高亮:点节点 → 它 + 直接相连的节点全亮,其余变淡 ----
    def _apply_highlight(self, focus: str | None):
        self._focused_id = focus
        nb = set()
        if focus:
            for s, t, _i in self._edge_items:
                if s == focus:
                    nb.add(t)
                if t == focus:
                    nb.add(s)
        for mid, item in self._items.items():
            on = focus is None or mid == focus or mid in nb
            item.setOpacity(1.0 if on else (0.0 if self.focus_only.isChecked() else 0.18))
        for s, t, item in self._edge_items:
            on = focus is None or focus in (s, t)
            item.setOpacity(1.0 if on else (0.0 if self.focus_only.isChecked() else 0.10))

    def _focus_node(self, mod_id: str):
        item = self._items.get(mod_id)
        if item is None:
            return
        self._apply_highlight(mod_id)
        self._search_status.setText(
            f"高亮:{self._graph.nodes[mod_id].name}  (点击别处或按「取消高亮」恢复)")
        self.view.centerOn(item)
        # 放大一点,看清这块
        self.view.scale(1.28, 1.28)

    def _locate_from_search(self):
        q = self.search_edit.text().strip().lower()
        if not q:
            return
        for mid, item in self._items.items():
            node = self._graph.nodes[mid]
            if q in mid.lower() or q in (node.name or "").lower():
                self.search_edit.setText(mid)
                self._focus_node(mid)
                return
        self._search_status.setText(f"没找到:{q}(试着输入 mod 的 id,如 tacz)")
