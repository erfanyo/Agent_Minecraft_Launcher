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
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from fetch_versions import fetch_version_manifest
from background_tasks import BackgroundTask
from instance_wizard import LOADER_CHOICES, OPTIMIZE_MODS, SHADER_MODS
from i18n import t
from loaders import list_fabric_loaders, list_forge_versions, list_neoforge_versions
from modrinth import list_mod_versions
from ui_style import (arrow_style, card_style, hint_style, inner_style,
                      list_style, primary_btn_style, set_style, danger_color,
                      text_color)
from version_tree import fill_version_tree


class DownloadTab(QWidget):
    """下载新实例选项卡:左侧菜单 + 右侧分类面板"""

    def __init__(self, parent=None, *, auto_load_versions: bool = True):
        super().__init__(parent)
        self._auto_load_versions = auto_load_versions
        self.mc = ""           # 选中的游戏版本
        self.loader_key = None
        self.modrinth_loader = None
        self._expanded_loader = None    # 当前展开版本下拉的加载器 key(或 None)
        self.loader_versions = {}   # loader -> QComboBox(指定版本)
        self.loader_available = {}  # loader -> bool(当前版本该加载器是否有可用版本,由异步检测填充)
        self._loader_checking = set()  # 正在异步检测版本可用性的 loader key 集合(避免重复请求)
        self.shader_combo = None
        self.opt_combos = {}        # mod slug -> QComboBox

        # 异步加载:版本/Mod 列表来自网络,全部放后台线程,UI 不卡
        self._async_cache = {}      # cache_key -> 已加载的版本列表
        self._async_tasks = set()   # 保持任务对象存活，并便于窗口关闭时统一释放
        self._async_inflight = {}   # cache_key -> [(成功回调, 失败回调)]

        # ---- 左侧:同级别菜单 ----
        self.menu = QListWidget()
        self.menu.setFixedWidth(168)
        set_style(self.menu, list_style)
        for title in ("游戏版本", "加载器", "光影 Mod", "优化 Mod"):
            item = QListWidgetItem(title, self.menu)
            item.setData(Qt.ItemDataRole.UserRole, title)
        self.menu.ai_pin_provider = self._pin_section
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
        set_style(self.download_btn, primary_btn_style)   # 蓝底白字
        self.download_btn.clicked.connect(self._on_start)
        # 按钮始终可点:没选版本时点击会给明确提示(见 _on_start)

        # 直接选本地整合包文件导入(复用文件菜单的导入整合包流程,不用先配 MC 版本/加载器)
        self.import_btn = QPushButton("导入整合包(.mrpack/.zip)…")
        self.import_btn.setToolTip("已有整合包文件(Modrinth .mrpack / CurseForge .zip / 实例文件夹 zip)?直接选文件导入成新实例")
        self._import_cb = None

        bottom = QHBoxLayout()
        bottom.addWidget(self.status_label)
        bottom.addStretch()
        bottom.addWidget(self.progress_bar)
        bottom.addWidget(self.import_btn)
        bottom.addWidget(self.download_btn)

        # 左侧菜单与右侧面板之间用 QSplitter:分隔线可拖到任意位置
        center = QSplitter(Qt.Orientation.Horizontal)
        self.menu.setFixedWidth(168)
        center.addWidget(self.menu)
        center.addWidget(self.stack)
        center.setStretchFactor(0, 0)
        center.setStretchFactor(1, 1)
        center.setSizes([168, 832])   # 步骤名称更舒展，版本面板仍占主要空间

        layout = QVBoxLayout(self)
        layout.addWidget(center)
        layout.addLayout(bottom)

    def _on_start(self):
        """点"开始下载实例":没选版本时给出明确提示(先选版本,再选加载器)"""
        if not self.mc:
            self.status_label.setText("⚠️ 请先到「游戏版本」选择一个版本(如 1.21.1)")
            self.status_label.setStyleSheet(f"color: {danger_color()};")
            self.menu.setCurrentRow(0)
            return
        self.status_label.setStyleSheet(hint_style())
        self.on_start_requested.emit() if hasattr(self, "on_start_requested") else None

    # ================= 面板构建 =================
    def _pin_section(self, pos):
        item = self.menu.itemAt(self.menu.viewport().mapFromGlobal(pos))
        if item is None:
            return None
        title = item.text()
        descriptions = {"游戏版本": "选择要下载的 Minecraft 版本",
                        "加载器": "选择原版或 Mod 加载器及其版本",
                        "光影 Mod": "选择提供光影支持的 Mod",
                        "优化 Mod": "选择随实例安装的性能优化 Mod"}
        return {"id": "download-section:" + title, "kind": "download_section",
                "name": "下载实例 · " + title, "content": descriptions.get(title, title),
                "minecraft": self.mc or "尚未选择",
                "note": "固定的是下载设置区域，不代表执行下载或更改选项"}

    def _pin_version(self, pos):
        item = self.version_tree.itemAt(self.version_tree.viewport().mapFromGlobal(pos))
        data = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(data, dict):
            return None
        version = data.get("id")
        if version:
            return {"id": "mc-version:" + version, "kind": "mc_version",
                    "name": f"MC {version} 版", "content": f"MC {version} 版",
                    "minecraft": version, "version_type": data.get("type", ""),
                    "note": "用户引用的游戏版本，尚未授权下载"}
        major = data.get("__major__")
        if major:
            return {"id": "mc-series:" + major, "kind": "mc_version",
                    "name": f"MC {major}.x 系列", "content": f"MC {major}.x 系列（未指定具体版本）",
                    "recommended": data.get("recommended") or ""}
        return None

    def _build_version_panel(self):
        panel = QWidget()
        title = QLabel("选择游戏版本")
        title.setStyleSheet(f"color: {text_color()}; font-size: 20px; font-weight: 700;")
        subtitle = QLabel("选择一个系列会采用推荐版本；展开后可以指定具体版本")
        subtitle.setStyleSheet(hint_style())
        self.version_tree = QTreeWidget()
        self.version_tree.ai_pin_provider = self._pin_version
        self.version_tree.setObjectName("version_tree")
        self.version_tree.setHeaderHidden(True)
        self.version_tree.currentItemChanged.connect(self._on_version_selected)
        if self._auto_load_versions:
            self._load_tree()
        layout = QVBoxLayout(panel)
        # 面板整体往右移一点,避免和左侧菜单/"下载新实例"区贴太近
        layout.setContentsMargins(20, 6, 8, 4)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.version_tree)
        return panel

    def _build_loader_panel(self):
        panel = QWidget()
        panel.setObjectName("loader_panel")
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
            # 非原版加载器默认隐藏:等选中版本后由 _refresh_loader_cards 按可用性显示,
            # 避免"先全部显示、再隐藏不可用项"的闪烁。原版始终可见。
            if key is not None:
                card.setVisible(False)
                card.setEnabled(False)
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

        # 加载器是什么:一句通俗解释,帮新手理解(不改"加载器"这个词,只加说明)
        self.loader_explain = QLabel(t("LOADER_EXPLAIN"))
        self.loader_explain.setWordWrap(True)
        self.loader_explain.setStyleSheet(hint_style())
        vbox.addWidget(self.loader_explain)

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
        """版本清单后台加载,不阻塞界面(构造时也可能触发)。"""
        self._async(("tree",), fetch_version_manifest, self._fill_tree)

    def _fill_tree(self, manifest):
        if not manifest:
            label = getattr(self, "status_label", None)
            if label is not None:
                label.setText("版本列表获取失败,请检查网络")
            return
        fill_version_tree(self.version_tree, manifest)

    def _on_version_selected(self, current, _prev):
        if current is None:
            return
        v = current.data(0, Qt.ItemDataRole.UserRole)
        # 点中大版本分组节点(折叠态):自动选中它的推荐具体版,再走叶子逻辑
        if isinstance(v, dict) and "__major__" in v:
            rec = v.get("recommended") or ""
            leaf = self._find_leaf_version(current, rec)
            if leaf is not None:
                self.version_tree.blockSignals(True)
                self.version_tree.setCurrentItem(leaf)
                self.version_tree.blockSignals(False)
                self._on_version_selected(leaf, current)
            return
        if not (isinstance(v, dict) and "id" in v):
            return
        self.mc = v["id"]
        # 收起版本树,自动跳到"加载器"分类
        for i in range(self.version_tree.topLevelItemCount()):
            self.version_tree.topLevelItem(i).setExpanded(False)
        self.status_label.setText(f"已选版本:{self.mc}")
        self.menu.setCurrentRow(1)
        # 按新版本重新检测各加载器可用性,决定显示哪些卡片
        self._refresh_loader_cards()

    @staticmethod
    def _find_leaf_version(root, version_str: str):
        """在某大版本节点下找指定具体版字符串的叶子(QTreeWidgetItem)。"""
        if not version_str:
            return None
        for i in range(root.childCount()):
            ch = root.child(i)
            if isinstance(ch.data(0, Qt.ItemDataRole.UserRole), dict) \
                    and ch.data(0, Qt.ItemDataRole.UserRole).get("id") == version_str:
                return ch
        return None

    # ================= 菜单切换 =================
    def _switch_panel(self, row):
        previous = self.stack.currentIndex()
        self.stack.setCurrentIndex(row)
        if previous != row:
            from ui_anim import reveal
            reveal(self.stack.currentWidget())
        if row == 1 and self.mc:
            self._refresh_loader_cards()   # 打开加载器面板时按版本刷新卡片可见性
            self._request_loader_versions(self.loader_key)   # 只刷当前加载器,异步
        elif row == 2:
            self._request_shader()
        elif row == 3:
            self._request_optimize()

    # ================= 异步加载(网络请求不卡 UI) =================
    def _async(self, cache_key: tuple, fetch, on_done, on_error=None):
        """后台线程跑网络请求 fetch(),完成后回主线程调 on_done(版本列表)。
        结果按 cache_key 缓存,第二次直接同步回调(不重复请求)。"""
        if cache_key in self._async_cache:
            on_done(self._async_cache[cache_key])
            return
        if cache_key in self._async_inflight:
            self._async_inflight[cache_key].append((on_done, on_error))
            return
        self._async_inflight[cache_key] = [(on_done, on_error)]

        task = BackgroundTask(lambda _task: fetch(), self)
        self._async_tasks.add(task)

        def apply_result(result):
            self._async_cache[cache_key] = result
            callbacks = self._async_inflight.pop(cache_key, [])
            for callback, _error_callback in callbacks:
                try:
                    callback(result)
                except Exception:
                    pass

        def apply_error(error):
            # 网络失败不是“服务器成功返回空列表”，不能缓存，也不能据此隐藏加载器。
            callbacks = self._async_inflight.pop(cache_key, [])
            for callback, error_callback in callbacks:
                try:
                    if error_callback is not None:
                        error_callback(error)
                    else:
                        callback([])
                except Exception:
                    pass

        task.succeeded.connect(apply_result)
        task.failed.connect(apply_error)
        task.finished.connect(lambda: self._async_tasks.discard(task))
        task.start()

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
        # 防御:若目标加载器在当前版本已知不可用,拒绝切换(卡片已隐藏,正常点不到,
        # 但防止代码/异步回调误触发)。原版(None)始终允许。
        if key is not None and self.mc and key in self.loader_available \
                and self.loader_available[key].get("mc") == self.mc \
                and not self.loader_available[key]["ok"]:
            return
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

    def _loader_versions_of(self, key: str, mc: str | None = None) -> list:
        """返回某加载器在 self.mc 下的可用版本列表(fabric/forge/neoforge)。"""
        mc = mc or self.mc
        if key == "fabric":
            return list_fabric_loaders(mc)
        if key == "forge":
            return list_forge_versions(mc)
        return list_neoforge_versions(mc)

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
        requested_mc = self.mc
        ck = ("loader", key, requested_mc)

        def fetch():
            return self._loader_versions_of(key, requested_mc)

        self._async(
            ck, fetch,
            lambda vs, c=combo, mc=requested_mc:
                self._fill_loader_combo(c, vs) if self.mc == mc else None,
            lambda error, c=combo, mc=requested_mc:
                self._fill_loader_error(c, error) if self.mc == mc else None,
        )

    def _fill_loader_error(self, combo: QComboBox, _error):
        combo.clear()
        combo.addItem("(获取失败，收起后重新展开即可重试)", None)
        combo.setEnabled(False)

    # ================= 加载器卡片可用性(按版本决定显示哪些卡片) =================
    def _refresh_loader_cards(self):
        """按当前版本决定哪些加载器卡片可见。
        对每个非原版加载器异步检测版本可用性;有版本则显示卡片,无版本则隐藏。
        版本切换/加载器面板打开时调用;结果回主线程后调用 _apply_loader_availability。
        先全部隐藏非原版卡片,再逐个按可用性显示,避免"先显示再隐藏"或切换版本时的残留。"""
        if not self.mc:
            return
        # 先隐藏非原版卡片(切换版本/首次进入时清掉残留可见状态;可用项稍后回填)
        for key, card, _arrow, _combo in self.loader_rows:
            if key is None:
                card.setVisible(True)
                card.setEnabled(True)
            else:
                card.setVisible(False)
                card.setEnabled(False)
        # 逐个非原版加载器:命中缓存直接显示,否则异步检测后显示
        for key, card, _arrow, _combo in self.loader_rows:
            if key is None:
                continue
            if key in self.loader_available and self.loader_available[key].get("mc") == self.mc:
                self._apply_loader_availability(key, card, self.loader_available[key]["ok"])
                continue
            requested_mc = self.mc
            checking_key = (key, requested_mc)
            if checking_key in self._loader_checking:
                continue
            self._loader_checking.add(checking_key)
            ck = ("loader", key, requested_mc)   # 与版本下拉复用同一 cache_key,避免重复下载
            self._async(
                ck,
                lambda k=key, mc=requested_mc: self._loader_versions_of(k, mc),
                lambda vs, k=key, c=card, mc=requested_mc:
                    self._on_loader_availability(k, vs, c, mc),
                lambda error, k=key, c=card, mc=requested_mc:
                    self._on_loader_availability_error(k, c, mc, error),
            )

    def _on_loader_availability(self, key, versions, card, requested_mc=None):
        """异步检测回调:记录可用性并应用显示/隐藏。"""
        requested_mc = requested_mc or self.mc
        self._loader_checking.discard((key, requested_mc))
        if self.mc != requested_mc:
            return
        ok = bool(versions)
        self.loader_available[key] = {"mc": requested_mc, "ok": ok}
        self._apply_loader_availability(key, card, ok)
        # 若当前选中的加载器变为不可用,回退到"原版",避免状态停留在隐形的加载器上
        if not ok and self.loader_key == key:
            self._select_loader(None)

    def _on_loader_availability_error(self, key, card, requested_mc, _error):
        """查询失败时保持入口可见；用户展开卡片即可重试，不伪装成不兼容。"""
        self._loader_checking.discard((key, requested_mc))
        if self.mc != requested_mc:
            return
        self.loader_available.pop(key, None)
        self._apply_loader_availability(key, card, True)
        card.setToolTip("暂时无法查询版本；点击卡片后展开版本列表可重试")

    def _apply_loader_availability(self, key, card, ok):
        card.setVisible(ok)
        card.setEnabled(ok)
        if ok:
            card.setToolTip("点击卡片选中该加载器")

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

    def bind_import(self, callback):
        """绑定"导入整合包"回调(选本地 .mrpack/.zip 直接导入成新实例)"""
        self._import_cb = callback
        self.import_btn.clicked.connect(self._on_import)

    def _on_import(self):
        """点"导入整合包":把选择交给外层(打开文件对话框 + 后台导入)"""
        if self._import_cb:
            self._import_cb()
