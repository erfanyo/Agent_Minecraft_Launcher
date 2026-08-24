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
    QLineEdit, QPushButton,
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
_PAD = 60.0


def _force_layout(nodes: list, edges: list, width: float, height: float,
                  iterations: int = 100) -> dict:
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
    k = math.sqrt(width * height / n) * 0.9   # 理想边长
    for _ in range(iterations):
        disp = {nid: [0.0, 0.0] for nid in nodes}
        # 斥力
        for i in range(n):
            a = nodes[i]
            for j in range(i + 1, n):
                b = nodes[j]
                dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
                d = math.hypot(dx, dy) or 0.01
                f = k * k / d
                ux, uy = dx / d, dy / d
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
        # 应用 + 限制单步位移 + 回缩到边界
        for nid in nodes:
            dx, dy = disp[nid]
            d = math.hypot(dx, dy) or 0.01
            step = min(d, k * 0.9)
            pos[nid][0] += dx / d * step
            pos[nid][1] += dy / d * step
            pos[nid][0] = max(_PAD, min(width - _PAD, pos[nid][0]))
            pos[nid][1] = max(_PAD, min(height - _PAD, pos[nid][1]))
    return {nid: (pos[nid][0], pos[nid][1]) for nid in nodes}


class _NodeItem(QGraphicsItem):
    def __init__(self, node: md.ModNode, x: float, y: float, font: QFont):
        super().__init__()
        self.node = node
        self._font = font
        fm = QFontMetricsF(font)
        text = node.name
        # 大型整合包节点多:宽度收紧(最短 56 / 最长 110),名字长了靠 tooltip 看全名
        self._w = min(max(fm.horizontalAdvance(text) + 16, 56), 110)
        self._h = 24
        self.setPos(x - self._w / 2, y - self._h / 2)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
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
        # 名字太长画不下 → 直接画省略号结尾
        p.drawText(self.boundingRect(), Qt.AlignmentFlag.AlignCenter, self.node.name)


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
        self.setWindowTitle(f"Mod 依赖网络 — {inst_id}")
        self.resize(900, 660)
        self._graph = graph

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
        canvas_w = max(900, int(_m.sqrt(max(n, 1)) * 110))
        canvas_h = max(620, int(_m.sqrt(max(n, 1)) * 82))
        self._pos = _force_layout(node_ids, edge_pairs, canvas_w, canvas_h)

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

        top = QHBoxLayout()
        top.addWidget(self.search_edit, 1)
        top.addWidget(self._search_status)
        top.addWidget(fit_btn)
        top.addWidget(zin)
        top.addWidget(zout)
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
            "拖拽平移、滚轮缩放;点节点高亮它和它依赖/被依赖的对象,再滚近点看细节\n"
            "⚠ 注意:红色「缺失」也可能是整合包**主动去掉的选装/需自行编译资源**(如 voxy 为选装、需跑编译脚本),"
            "未必真缺——结合整合包说明判断,别盲目补装。")

        layout = QVBoxLayout(self)
        layout.addWidget(overview)
        layout.addLayout(top)
        layout.addWidget(self.view, 1)
        layout.addWidget(legend)

    # ---- 高亮:点节点 → 它 + 直接相连的节点全亮,其余变淡 ----
    def _apply_highlight(self, focus: str | None):
        nb = set()
        if focus:
            for s, t, _i in self._edge_items:
                if s == focus:
                    nb.add(t)
                if t == focus:
                    nb.add(s)
        for mid, item in self._items.items():
            on = focus is None or mid == focus or mid in nb
            item.setOpacity(1.0 if on else 0.18)
        for s, t, item in self._edge_items:
            on = focus is None or focus in (s, t)
            item.setOpacity(1.0 if on else 0.10)

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
