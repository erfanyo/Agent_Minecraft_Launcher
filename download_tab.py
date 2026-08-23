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
import queue
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from fetch_versions import fetch_version_manifest
from instance_wizard import LOADER_CHOICES, OPTIMIZE_MODS, SHADER_MODS
from loaders import list_fabric_loaders, list_forge_versions, list_neoforge_versions
from modrinth import list_mod_versions
from ui_style import arrow_style, card_style, hint_style, inner_style, primary_btn_style
from version_tree import fill_version_tree


class DownloadTab(QWidget):
    """下载新实例选项卡:左侧菜单 + 右侧分类面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mc = ""           # 选中的游戏版本
        self.loader_key = None
        self.modrinth_loader = None
        self._expanded_loader = None    # 当前展开版本下拉的加载器 key(或 None)
        self.loader_versions = {}   # loader -> QComboBox(指定版本)
        self.shader_combo = None
        self.opt_combos = {}        # mod slug -> QComboBox

        # 异步加载:版本/Mod 列表来自网络,全部放后台线程,UI 不卡
        self._async_q = queue.Queue()
        self._async_cache = {}      # cache_key -> 已加载的版本列表
        self._async_timer = QTimer(self)
        self._async_timer.timeout.connect(self._drain_async)
        self._async_timer.start(60)

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
        self.download_btn.setStyleSheet(primary_btn_style())   # 蓝底白字
        self.download_btn.clicked.connect(self._on_start)
        # 按钮始终可点:没选版本时点击会给明确提示(见 _on_start)

        bottom = QHBoxLayout()
        bottom.addWidget(self.status_label)
        bottom.addStretch()
        bottom.addWidget(self.progress_bar)
        bottom.addWidget(self.download_btn)

        # 左侧菜单与右侧面板之间用 QSplitter:分隔线可拖到任意位置
        center = QSplitter(Qt.Orientation.Horizontal)
        self.menu.setFixedWidth(140)
        center.addWidget(self.menu)
        center.addWidget(self.stack)
        center.setStretchFactor(0, 0)
        center.setStretchFactor(1, 1)
        center.setSizes([140, 860])   # 版本面板默认更宽

        layout = QVBoxLayout(self)
        layout.addWidget(center)
        layout.addLayout(bottom)

    def _on_start(self):
        """点"开始下载实例":没选版本时给出明确提示(先选版本,再选加载器)"""
        if not self.mc:
            self.status_label.setText("⚠️ 请先到「游戏版本」选择一个版本(如 1.21.1)")
            self.status_label.setStyleSheet("color: #E53935;")
            self.menu.setCurrentRow(0)
            return
        self.status_label.setStyleSheet(hint_style())
        self.on_start_requested.emit() if hasattr(self, "on_start_requested") else None

    # ================= 面板构建 =================
    def _build_version_panel(self):
        panel = QWidget()
        self.version_tree = QTreeWidget()
        self.version_tree.setHeaderLabel("版本")
        self.version_tree.currentItemChanged.connect(self._on_version_selected)
        self._load_tree()
        layout = QVBoxLayout(panel)
        # 面板整体往右移一点,避免和左侧菜单/"下载新实例"区贴太近
        layout.setContentsMargins(16, 0, 0, 0)
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
            # 卡片只放:名称 + 展开箭头(版本下拉统一在面板底部版本行,避免卡片拥挤)
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
            combo.setVisible(False)  # 展开箭头后,出现在面板底部"加载器版本"行

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

            vbox.addWidget(card)
            self.loader_rows.append((key, card, arrow, combo))
            self.loader_versions[key] = combo

        # 底部"加载器版本"行:点箭头后在此显示当前加载器的版本下拉(一次只显示一个)
        self.loader_version_row = QWidget()
        lvr_layout = QHBoxLayout(self.loader_version_row)
        lvr_layout.setContentsMargins(0, 0, 0, 0)
        lvr_layout.addWidget(QLabel("加载器版本:"))
        for _name, key, _mr in LOADER_CHOICES:
            lvr_layout.addWidget(self.loader_versions[key], 1)
        lvr_layout.addStretch()
        self.loader_version_row.setVisible(False)
        vbox.addWidget(self.loader_version_row)

        self.loader_hint = QLabel("点击卡片选中加载器;点卡片右侧的箭头可展开选择版本")
        self.loader_hint.setStyleSheet(hint_style())
        vbox.addWidget(self.loader_hint)

        # Fabric API:绝大多数 Fabric 模组需要它,选中 Fabric 后自动出现版本选择
        self.fabric_api_row = QWidget()
        fa_layout = QHBoxLayout(self.fabric_api_row)
        fa_layout.setContentsMargins(0, 0, 0, 0)
        fa_layout.addWidget(QLabel("Fabric API 版本:"))
        self.fabric_api_combo = QComboBox()
        self.fabric_api_combo.setToolTip("Fabric 模组前置库,默认选最新;可指定版本")
        fa_layout.addWidget(self.fabric_api_combo, 1)
        fa_layout.addWidget(QLabel("(默认最新)"))
        self.fabric_api_row.setVisible(False)
        vbox.addWidget(self.fabric_api_row)

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
            self._request_loader_versions(self.loader_key)   # 只刷当前加载器,异步
        elif row == 2:
            self._request_shader()
        elif row == 3:
            self._request_optimize()

    # ================= 异步加载(网络请求不卡 UI) =================
    def _async(self, cache_key: tuple, fetch, on_done):
        """后台线程跑网络请求 fetch(),完成后回主线程调 on_done(版本列表)。
        结果按 cache_key 缓存,第二次直接同步回调(不重复请求)。"""
        if cache_key in self._async_cache:
            on_done(self._async_cache[cache_key])
            return

        def worker():
            try:
                result = fetch()
            except Exception:
                result = []
            self._async_q.put((cache_key, result, on_done))

        threading.Thread(target=worker, daemon=True).start()

    def _drain_async(self):
        """主线程:把后台结果搬回 UI"""
        while True:
            try:
                cache_key, result, on_done = self._async_q.get_nowait()
            except queue.Empty:
                return
            self._async_cache[cache_key] = result
            try:
                on_done(result)
            except Exception:
                pass

    def _fill_combo(self, combo: QComboBox, versions: list):
        """填充下拉:清空 → 逐项加入 → 默认选最新的"""
        combo.clear()
        for v in versions:
            combo.addItem(v, v)
        combo.setEnabled(bool(versions))
        if versions:
            combo.setCurrentIndex(0)

    # ================= 加载器 =================
    def _select_loader(self, key):
        self.loader_key = key
        for k, card, _a, _c in self.loader_rows:
            card.setChecked(k == key)
        self.modrinth_loader = None
        for _name, k, mr in LOADER_CHOICES:
            if k == key:
                self.modrinth_loader = mr
        # 切换加载器时收起已展开的版本行(避免显示上一个加载器的下拉)
        self._expanded_loader = None
        for k, _card, arrow, c in self.loader_rows:
            c.setVisible(False)
            arrow.setText("▸")
        self.loader_version_row.setVisible(False)
        # 异步填充:UI 立即响应,网络结果后台到了再更新
        self._request_loader_versions(key)
        self._request_shader()
        self._request_optimize()
        self._request_fabric_api()
        self._update_ready()

    def _request_fabric_api(self):
        """选中 Fabric 时异步加载 Fabric API 版本;其他加载器隐藏"""
        if self.loader_key == "fabric" and self.mc:
            self.fabric_api_row.setVisible(True)
            self.fabric_api_combo.clear()
            self.fabric_api_combo.addItem("加载中...", None)
            self.fabric_api_combo.setEnabled(False)
            import modrinth
            self._async(("fa", self.mc),
                        lambda: modrinth.list_mod_versions("fabric-api", self.mc, "fabric"),
                        self._fill_fabric_api)
        else:
            self.fabric_api_row.setVisible(False)

    def _fill_fabric_api(self, versions):
        self.fabric_api_combo.clear()
        for v in versions:
            self.fabric_api_combo.addItem(v, v)
        self.fabric_api_combo.setEnabled(bool(versions))
        if versions:
            self.fabric_api_combo.setCurrentIndex(0)   # 默认最新

    def _toggle_loader_versions(self, key):
        """展开/收起面板底部的"加载器版本"行(一次只显示一张加载器的版本下拉)"""
        if self._expanded_loader == key:
            self._expanded_loader = None
        else:
            self._expanded_loader = key
        show = self._expanded_loader is not None
        for k, _card, arrow, c in self.loader_rows:
            on = show and k == self._expanded_loader
            c.setVisible(on)
            arrow.setText("▾" if on else "▸")
        self.loader_version_row.setVisible(show)
        if show:
            self._request_loader_versions(key)   # 只刷这一张,异步

    def _fill_loader_combo(self, combo: QComboBox, versions: list):
        """加载器版本填充:空时明确提示'该版本暂无此加载器'"""
        combo.clear()
        if not versions:
            combo.addItem("(该版本暂无此加载器可用)", None)
            combo.setEnabled(False)
            return
        for v in versions:
            combo.addItem(v, v)
        combo.setEnabled(True)
        combo.setCurrentIndex(0)

    def _request_loader_versions(self, key=None):
        """异步加载某加载器的版本列表(只刷 key,不重复请求其他加载器)"""
        key = self.loader_key if key is None else key
        combo = self.loader_versions.get(key)
        if combo is None:
            return
        if key is None:
            combo.clear()
            combo.addItem("(原版无需加载器)", None)
            combo.setEnabled(False)
            return
        if not self.mc:
            return
        combo.clear()
        combo.addItem("加载中...", None)
        combo.setEnabled(False)
        ck = ("loader", key, self.mc)

        def fetch():
            if key == "fabric":
                return list_fabric_loaders(self.mc)
            if key == "forge":
                return list_forge_versions(self.mc)
            return list_neoforge_versions(self.mc)

        self._async(ck, fetch, lambda vs, c=combo: self._fill_loader_combo(c, vs))

    # ================= 光影 =================
    def _request_shader(self):
        slug = SHADER_MODS.get(self.loader_key or "")
        if not slug or not self.mc:
            self.shader_name_label.setText("当前加载器对应的光影 Mod:—(需先选 Fabric/Forge)")
            self.shader_combo.clear()
            self.shader_combo.addItem("(无)", None)
            self.shader_combo.setEnabled(False)
            return
        self.shader_name_label.setText(f"光影 Mod:{slug}({self.loader_key})")
        self.shader_combo.clear()
        self.shader_combo.addItem("加载中...", None)
        self.shader_combo.setEnabled(False)
        self._async(("shader", slug, self.mc, self.loader_key),
                    lambda: list_mod_versions(slug, self.mc, self.loader_key),
                    self._fill_shader)

    def _fill_shader(self, versions):
        self.shader_combo.clear()
        for v in versions:
            self.shader_combo.addItem(v, v)
        self.shader_combo.setEnabled(bool(versions))
        if versions:
            self.shader_combo.setCurrentIndex(0)

    # ================= 优化 =================
    def _request_optimize(self):
        """重建优化 Mod 行(本地操作,快),版本列表异步填"""
        for w in self._opt_rows:
            w.deleteLater()
        self._opt_rows.clear()
        self.opt_combos.clear()
        box_layout = QVBoxLayout(self.optimize_box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        mods = OPTIMIZE_MODS.get(self.loader_key or "", [])
        if not mods:
            box_layout.addWidget(QLabel("当前加载器没有内置优化 Mod 列表(选 Fabric 或 Forge)"))
            return
        for slug in mods:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.addWidget(QLabel(slug), 1)
            combo = QComboBox()
            combo.addItem("加载中...", None)
            combo.setEnabled(False)
            rl.addWidget(combo)
            box_layout.addWidget(row)
            self._opt_rows.append(row)
            self.opt_combos[slug] = combo
            self._async(("opt", slug, self.mc, self.loader_key),
                        lambda: list_mod_versions(slug, self.mc, self.loader_key),
                        lambda vs, c=combo: self._fill_combo(c, vs))

    # ================= 汇总与下载 =================
    def _update_ready(self):
        # 按钮始终可点:没选版本时点击会给出明确提示(见 _on_start)
        if self.mc:
            loader_name = self.loader_key or "原版(无加载器)"
            self.status_label.setText(f"已选版本:{self.mc} | 加载器:{loader_name}")
            self.status_label.setStyleSheet(hint_style())

    def state(self) -> dict:
        """汇总全部选择"""
        fa_ver = self.fabric_api_combo.currentData() if self.loader_key == "fabric" else None
        return {
            "version": self.mc,
            "loader_key": self.loader_key,
            "modrinth_loader": self.modrinth_loader,
            "shader": self.shader_check.isChecked(),
            "shader_version": self.shader_combo.currentData(),
            "optimize": self.optimize_check.isChecked(),
            "loader_version": self.loader_versions.get(self.loader_key, QComboBox()).currentData(),
            "fabric_api_version": fa_ver,   # 仅 Fabric 且选择了版本时非空
            "optimize_versions": {slug: c.currentData() for slug, c in self.opt_combos.items()},
        }

    def set_status(self, text: str):
        self.status_label.setText(text)

    def set_progress(self, done: int, total: int):
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)

    def set_busy(self, busy: bool):
        self.download_btn.setEnabled(not busy)
        self.menu.setEnabled(not busy)

    def bind_start(self, callback):
        """绑定"开始下载"回调(与 _on_start 并存,先检查版本再触发下载)"""
        self.download_btn.clicked.connect(callback)
