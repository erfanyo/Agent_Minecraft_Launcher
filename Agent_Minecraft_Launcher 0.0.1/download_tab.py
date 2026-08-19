# -*- coding: utf-8 -*-
"""
"下载新实例"选项卡:左侧同级别菜单(游戏版本 / 加载器 / 光影 Mod / 优化 Mod),
点击某一项 → 右侧展示该分类的选项;选完版本树自动收起。

- 游戏版本:版本分类树,选中即收起树,并自动跳到"加载器"
- 加载器  :三张可点击的卡片(原版/Fabric/Forge),点击即选中(框选高亮);
           每张卡片右侧有展开箭头,展开后可选指定版本的加载器
- 光影 Mod:开关 + 光影 Mod 版本(随加载器变化)
- 优化 Mod:开关 + 每个优化 Mod 的版本(默认最新)

所有选择通过 state() 汇总,由主窗口拿去下载。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from fetch_versions import fetch_version_manifest
from instance_wizard import LOADER_CHOICES, OPTIMIZE_MODS, SHADER_MODS
from loaders import list_fabric_loaders, list_forge_versions, list_neoforge_versions
from modrinth import list_mod_versions
from ui_style import arrow_style, card_style, hint_style, inner_style
from version_tree import fill_version_tree


class DownloadTab(QWidget):
    """下载新实例选项卡:左侧菜单 + 右侧分类面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mc = ""           # 选中的游戏版本
        self.loader_key = None
        self.modrinth_loader = None
        self.loader_versions = {}   # loader -> QComboBox(指定版本)
        self.shader_combo = None
        self.opt_combos = {}        # mod slug -> QComboBox

        # ---- 左侧:同级别菜单 ----
        self.menu = QListWidget()
        self.menu.setFixedWidth(140)
        for title in ("游戏版本", "加载器", "光影 Mod", "优化 Mod"):
            QListWidgetItem(title, self.menu)
        self.menu.currentRowChanged.connect(self._switch_panel)

        # ---- 右侧:四个分类面板 ----
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_version_panel())
        self.stack.addWidget(self._build_loader_panel())
        self.stack.addWidget(self._build_shader_panel())
        self.stack.addWidget(self._build_optimize_panel())
        self.menu.setCurrentRow(0)  # 此时 stack 已就绪

        # ---- 底部:状态 + 进度 + 开始下载 ----
        self.status_label = QLabel("先在\"游戏版本\"里选一个版本")
        self.status_label.setStyleSheet(hint_style())
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.download_btn = QPushButton("开始下载实例")
        self.download_btn.clicked.connect(self._on_start)
        self.download_btn.setEnabled(False)

        bottom = QHBoxLayout()
        bottom.addWidget(self.status_label)
        bottom.addStretch()
        bottom.addWidget(self.progress_bar)
        bottom.addWidget(self.download_btn)

        center = QHBoxLayout()
        center.addWidget(self.menu)
        center.addWidget(self.stack, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(center)
        layout.addLayout(bottom)

    # ================= 面板构建 =================
    def _build_version_panel(self):
        panel = QWidget()
        self.version_tree = QTreeWidget()
        self.version_tree.setHeaderLabel("版本(按大版本分类,选完自动收起)")
        self.version_tree.currentItemChanged.connect(self._on_version_selected)
        self._load_tree()
        layout = QVBoxLayout(panel)
        layout.addWidget(self.version_tree)
        return panel

    def _build_loader_panel(self):
        panel = QWidget()
        self.loader_rows = []   # (key, card, arrow, combo)
        vbox = QVBoxLayout(panel)

        # 卡片样式来自 ui_style(深浅色主题兼容)
        card_style_sheet = card_style()
        arrow_style_sheet = arrow_style()

        self.loader_versions.clear()
        for name, key, mr in LOADER_CHOICES:
            # 卡片本身就是可点击的按钮,内部放:名称 + 展开箭头 + (展开后)版本下拉
            card = QPushButton()
            card.setCheckable(True)
            card.setMinimumHeight(42)
            card.setStyleSheet(card_style_sheet)
            card.setToolTip("点击卡片选中该加载器")
            card.clicked.connect(lambda _c, k=key: self._select_loader(k))

            arrow = QPushButton("▸")
            arrow.setFixedWidth(28)
            arrow.setStyleSheet(arrow_style_sheet)
            arrow.setToolTip("展开:选择指定版本的加载器")
            arrow.clicked.connect(lambda _c, k=key: self._toggle_loader_versions(k))

            combo = QComboBox()
            combo.setVisible(False)  # 展开箭头后,版本下拉出现在卡片内部

            name_label = QLabel(name)
            name_label.setStyleSheet(inner_style())

            top = QHBoxLayout()
            top.setContentsMargins(8, 0, 4, 0)
            top.addWidget(name_label)
            top.addStretch()
            top.addWidget(arrow)

            inner = QVBoxLayout(card)
            inner.setContentsMargins(0, 6, 0, 8)
            inner.addLayout(top)
            inner.addWidget(combo)

            vbox.addWidget(card)
            self.loader_rows.append((key, card, arrow, combo))
            self.loader_versions[key] = combo

        self.loader_hint = QLabel("点击卡片选中加载器;点卡片右侧的箭头可展开选择版本")
        self.loader_hint.setStyleSheet(hint_style())
        vbox.addWidget(self.loader_hint)
        vbox.addStretch()
        return panel

    def _build_shader_panel(self):
        panel = QWidget()
        self.shader_check = QCheckBox("安装光影加载器(支持光影包)")
        self.shader_check.setChecked(False)
        self.shader_name_label = QLabel("当前加载器对应的光影 Mod:—")
        self.shader_combo = QComboBox()
        self.shader_combo.addItem("(默认最新)", None)
        layout = QVBoxLayout(panel)
        layout.addWidget(self.shader_check)
        layout.addWidget(self.shader_name_label)
        layout.addWidget(QLabel("光影 Mod 版本:"))
        layout.addWidget(self.shader_combo)
        layout.addStretch()
        return panel

    def _build_optimize_panel(self):
        panel = QWidget()
        self.optimize_check = QCheckBox("安装基础优化模组(显著提升性能)—— 推荐")
        self.optimize_check.setChecked(False)
        self.optimize_box = QWidget()
        self.opt_combos.clear()
        self._opt_rows = []  # (slug, name_label, combo)
        layout = QVBoxLayout(panel)
        layout.addWidget(self.optimize_check)
        layout.addWidget(self.optimize_box)
        layout.addStretch()
        return panel

    # ================= 版本面板 =================
    def _load_tree(self):
        try:
            manifest = fetch_version_manifest()
        except Exception:
            self.status_label.setText("版本列表获取失败,请检查网络")
            return
        fill_version_tree(self.version_tree, manifest)

    def _on_version_selected(self, current, _prev):
        if current is None:
            return
        v = current.data(0, Qt.ItemDataRole.UserRole)
        if not (isinstance(v, dict) and "id" in v):
            return
        self.mc = v["id"]
        # 收起版本树,自动跳到"加载器"分类
        for i in range(self.version_tree.topLevelItemCount()):
            self.version_tree.topLevelItem(i).setExpanded(False)
        self.status_label.setText(f"已选版本:{self.mc}")
        self.menu.setCurrentRow(1)

    # ================= 菜单切换 =================
    def _switch_panel(self, row):
        self.stack.setCurrentIndex(row)
        if row == 1 and self.mc:
            self._refresh_loader_versions()
        elif row == 2:
            self._refresh_shader()
        elif row == 3:
            self._refresh_optimize()

    # ================= 加载器 =================
    def _select_loader(self, key):
        self.loader_key = key
        for k, card, _a, _c in self.loader_rows:
            card.setChecked(k == key)
        self.modrinth_loader = None
        for _name, k, mr in LOADER_CHOICES:
            if k == key:
                self.modrinth_loader = mr
        self._refresh_loader_versions()
        self._refresh_shader()
        self._refresh_optimize()
        self._update_ready()

    def _toggle_loader_versions(self, key):
        """展开/收起某张加载器卡片内部的版本下拉(一次只展开一张)"""
        for k, _card, arrow, combo in self.loader_rows:
            if k == key:
                show = not combo.isVisible()
                combo.setVisible(show)
                arrow.setText("▾" if show else "▸")
                if show:
                    self._refresh_loader_versions()
            else:
                combo.setVisible(False)
                arrow.setText("▸")

    def _refresh_loader_versions(self):
        for k, _card, _a, _c in self.loader_rows:
            combo = self.loader_versions[k]
            if k is None:
                combo.clear()
                combo.addItem("(原版无需加载器)", None)
                combo.setEnabled(False)
                continue
            if not self.mc:
                continue
            try:
                if k == "fabric":
                    versions = list_fabric_loaders(self.mc)
                elif k == "forge":
                    versions = list_forge_versions(self.mc)
                else:
                    versions = list_neoforge_versions(self.mc)
            except Exception:
                versions = []
            combo.clear()
            for v in versions:
                combo.addItem(v, v)
            combo.setEnabled(bool(versions))
            if versions:
                combo.setCurrentIndex(0)  # 默认选最新的那个

    # ================= 光影 =================
    def _refresh_shader(self):
        slug = SHADER_MODS.get(self.loader_key or "")
        if not slug or not self.mc:
            self.shader_name_label.setText("当前加载器对应的光影 Mod:—(需先选 Fabric/Forge)")
            self.shader_combo.clear()
            self.shader_combo.addItem("(无)", None)
            self.shader_combo.setEnabled(False)
            return
        try:
            versions = list_mod_versions(slug, self.mc, self.loader_key)
        except Exception:
            versions = []
        self.shader_name_label.setText(f"光影 Mod:{slug}({self.loader_key})")
        self.shader_combo.clear()
        for v in versions:
            self.shader_combo.addItem(v, v)
        self.shader_combo.setEnabled(bool(versions))
        if versions:
            self.shader_combo.setCurrentIndex(0)

    # ================= 优化 =================
    def _refresh_optimize(self):
        # 重建优化 Mod 列表(随加载器变化)
        for w in self._opt_rows:
            w.deleteLater()
        self._opt_rows.clear()
        self.opt_combos.clear()
        box_layout = QVBoxLayout(self.optimize_box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        mods = OPTIMIZE_MODS.get(self.loader_key or "", [])
        if not mods:
            box_layout.addWidget(QLabel("当前加载器没有内置优化 Mod 列表(选 Fabric 或 Forge)"))
        for slug in mods:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.addWidget(QLabel(slug), 1)
            combo = QComboBox()
            try:
                for v in list_mod_versions(slug, self.mc, self.loader_key):
                    combo.addItem(v, v)
            except Exception:
                pass
            combo.setEnabled(combo.count() > 0)
            rl.addWidget(combo)
            box_layout.addWidget(row)
            self._opt_rows.append(row)
            self.opt_combos[slug] = combo

    # ================= 汇总与下载 =================
    def _update_ready(self):
        ok = bool(self.mc) and self.loader_key is not None
        self.download_btn.setEnabled(ok)
        if ok:
            self.status_label.setText(f"已选版本:{self.mc} | 加载器:{self.loader_key}")

    def state(self) -> dict:
        """汇总全部选择"""
        return {
            "version": self.mc,
            "loader_key": self.loader_key,
            "modrinth_loader": self.modrinth_loader,
            "shader": self.shader_check.isChecked(),
            "shader_version": self.shader_combo.currentData(),
            "optimize": self.optimize_check.isChecked(),
            "loader_version": self.loader_versions.get(self.loader_key, QComboBox()).currentData(),
            "optimize_versions": {slug: c.currentData() for slug, c in self.opt_combos.items()},
        }

    def set_status(self, text: str):
        self.status_label.setText(text)

    def set_progress(self, done: int, total: int):
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)

    def set_busy(self, busy: bool):
        self.download_btn.setEnabled(not busy and bool(self.mc) and self.loader_key is not None)
        self.menu.setEnabled(not busy)

    def _on_start(self):
        self.on_start_requested.emit() if hasattr(self, "on_start_requested") else None

    def bind_start(self, callback):
        """绑定"开始下载"回调"""
        self.download_btn.clicked.connect(callback)
