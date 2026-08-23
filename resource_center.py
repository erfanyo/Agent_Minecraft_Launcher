# -*- coding: utf-8 -*-
"""
「下载新资源」综合入口:像逛商场一样挑资源。

- 左侧可折叠菜单栏:首页 / 实例 / Mod / 光影包 / 数据包 / 资源包
- 右侧分类面板:
  - 首页:分类大卡片入口 + 最新版本提示(最新版 mod 生态一般很不好)
  - 实例:下载新实例向导(版本树 → 加载器 → 光影/优化)
  - Mod / 光影包 / 数据包 / 资源包:同一套"资源浏览器"
    (搜索 + 目标实例 + 筛选 + 结果列表 + 详情面板,信息丰富)
"""
import os
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from i18n import t
from ui_style import card_style, hint_style, inner_style

# 资源分类(左侧菜单 + Modrinth project_type + 安装目录子文件夹)
RESOURCE_CATEGORIES = [
    ("mod", "🧩 Mod", "mods"),
    ("shader", "🌄 光影包", "shaderpacks"),
    ("datapack", "🗂 数据包", "datapacks"),
    ("resourcepack", "🎨 资源包", "resourcepacks"),
]


class ResourceBrowser(QWidget):
    """资源浏览器(Mod / 光影包 / 数据包 / 资源包共用):
    目标实例(可折叠) + 筛选 + 搜索 + 结果列表(信息丰富) + 详情面板(版本/加载器/下载)"""

    def __init__(self, project_type: str, label: str, sub_dir: str,
                 on_download, get_instance_loader, parent=None):
        super().__init__(parent)
        self.project_type = project_type
        self.label = label
        self.sub_dir = sub_dir            # mods / shaderpacks / ...
        self.on_download = on_download    # (slug, version, inst, custom_dir) -> 结果
        self.get_instance_loader = get_instance_loader   # (inst) -> loader or None

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            t(f"搜索{label},如 sodium / 钠 / 名字(回车搜索)", f"Search {label}..."))
        self.search_edit.returnPressed.connect(self.do_search)
        search_btn = QPushButton(t("搜索", "Search"))
        search_btn.clicked.connect(self.do_search)

        # 目标实例(折叠):装到哪个实例的对应目录
        self.inst_cards_toggle = QPushButton("▸ 目标实例: 未选择")
        self.inst_cards_toggle.setCheckable(True)
        self.inst_cards_toggle.setChecked(False)
        self.inst_cards_toggle.clicked.connect(self._toggle_cards)
        self.instance_cards_box = QWidget()
        self.instance_cards_layout = QVBoxLayout(self.instance_cards_box)
        self.instance_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.instance_cards_layout.setSpacing(4)
        self._inst_cards = []          # [(inst, card)]
        self._none_card = None
        self.selected_inst = None
        self.custom_dir = None
        self.custom_label = QLabel("")
        self.custom_label.setStyleSheet(hint_style())
        self.custom_label.setWordWrap(True)

        # 筛选
        self.filter_version = QComboBox()
        self.filter_version.setEditable(True)
        self.filter_version.setToolTip("筛选的游戏版本,可自行输入")
        self.filter_loader = QComboBox()
        self.filter_loader.addItem(t("全部加载器", "All loaders"), None)
        for label, value in [("Fabric", "fabric"), ("Forge", "forge"),
                             ("NeoForge", "neoforge"), ("Quilt", "quilt")]:
            self.filter_loader.addItem(label, value)

        # 结果列表 + 详情面板
        self.result_list = QListWidget()
        self.result_list.setWordWrap(True)
        self.result_list.currentItemChanged.connect(self._on_selected)
        self.panel = QWidget()
        self.panel.setMinimumWidth(260)
        self.panel.setMaximumWidth(500)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(56, 56)
        self.icon_label.setStyleSheet(inner_style())
        self.title_label = QLabel("")
        self.title_label.setWordWrap(True)
        self.meta_label = QLabel("")
        self.meta_label.setStyleSheet(hint_style())
        self.meta_label.setWordWrap(True)
        self.desc_label = QLabel("")
        self.desc_label.setStyleSheet(hint_style())
        self.desc_label.setWordWrap(True)
        self.gv_combo = QComboBox()
        self.loader_combo = QComboBox()
        self.ver_combo = QComboBox()
        self.dl_btn = QPushButton(t("下载", "Download"))
        self.dl_btn.clicked.connect(self._download)
        self.gv_combo.currentIndexChanged.connect(self._refresh_versions)
        self.loader_combo.currentIndexChanged.connect(self._refresh_versions)
        p = QVBoxLayout(self.panel)
        p.addWidget(self.icon_label)
        p.addWidget(self.title_label)
        p.addWidget(self.meta_label)
        p.addWidget(self.desc_label)
        p.addWidget(QLabel(t("游戏版本:", "Game version:")))
        p.addWidget(self.gv_combo)
        p.addWidget(QLabel(t("加载器:", "Loader:")))
        p.addWidget(self.loader_combo)
        p.addWidget(QLabel(t("版本:", "Version:")))
        p.addWidget(self.ver_combo)
        p.addWidget(self.dl_btn)
        self.empty_label = QLabel(t("← 在左侧选择一个项目\n展开它的版本 / 加载器选项",
                                    "← Select a project on the left"))
        self.empty_label.setStyleSheet(hint_style())
        self.empty_label.setWordWrap(True)
        p.addWidget(self.empty_label)
        p.addStretch()
        for w in (self.icon_label, self.title_label, self.meta_label, self.desc_label,
                  self.gv_combo, self.loader_combo, self.ver_combo, self.dl_btn):
            w.setVisible(False)

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(self.result_list)
        panel_scroll = QScrollArea()
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setWidget(self.panel)
        self.split.addWidget(panel_scroll)
        self.split.setChildrenCollapsible(False)
        self.split.setSizes([380, 320])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.inst_cards_toggle)
        layout.addWidget(self.instance_cards_box)
        layout.addWidget(self.custom_label)
        layout.addLayout(self._row(self.filter_version, self.filter_loader))
        layout.addLayout(self._row(self.search_edit, search_btn))
        layout.addWidget(self.split, 1)

    def _row(self, *widgets):
        r = QHBoxLayout()
        for w in widgets:
            r.addWidget(w, 1)
        return r

    # ---- 目标实例 ----
    def set_instances(self, instances: list):
        """刷新实例卡片(可选的安装目标)"""
        for _inst, card in self._inst_cards:
            card.deleteLater()
        self._inst_cards = []
        self.instance_cards_layout.takeAt(0)
        for inst in instances:
            card = QPushButton(f"{inst['label']}")
            card.setCheckable(True)
            card.setStyleSheet(card_style())
            card.clicked.connect(lambda _c, i=inst: self._select_inst(i))
            self.instance_cards_layout.addWidget(card)
            self._inst_cards.append((inst, card))
        none_card = QPushButton(t("无(手动选目录)", "None (pick folder)"))
        none_card.setCheckable(True)
        none_card.setStyleSheet(card_style())
        none_card.clicked.connect(self._select_none)
        self.instance_cards_layout.addWidget(none_card)
        self._none_card = none_card

    def _toggle_cards(self):
        show = self.inst_cards_toggle.isChecked()
        self.instance_cards_box.setVisible(show)
        self.inst_cards_toggle.setText(
            ("▾ " if show else "▸ ") + self.inst_cards_toggle.text()[2:])

    def _select_inst(self, inst):
        self.selected_inst = inst
        self.custom_dir = None
        for i, card in self._inst_cards:
            card.setChecked(i["id"] == inst["id"])
        if self._none_card:
            self._none_card.setChecked(False)
        self.custom_label.setText("")
        self.inst_cards_toggle.setText(f"▸ 目标实例: {inst['id']}")
        self.inst_cards_toggle.setChecked(False)
        self.instance_cards_box.setVisible(False)
        # 筛选同步到该实例的基础版本 + 加载器
        self.filter_version.setCurrentText(inst["base"])
        idx = self.filter_loader.findData(inst["loader"])
        if idx >= 0:
            self.filter_loader.setCurrentIndex(idx)

    def _select_none(self):
        self.selected_inst = None
        for i, card in self._inst_cards:
            card.setChecked(False)
        if self._none_card:
            self._none_card.setChecked(True)
        self.inst_cards_toggle.setText("▸ 目标实例: 未选择(手动选目录)")

    def pick_custom_dir(self, game_dir: str):
        """用户用文件管理器选安装位置(装到其他启动器的目录)"""
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, t("选择安装位置", "Pick folder"), game_dir)
        if d:
            self.custom_dir = d
            self.custom_label.setText(f"{t('安装到', 'Install to')}: {d}")
            self.custom_label.setVisible(True)

    # ---- 搜索 ----
    def do_search(self):
        query = self.search_edit.text().strip()
        if not query:
            return
        import modrinth
        try:
            hits = modrinth.search_mods_cn(
                query, self.filter_version.currentText().strip(),
                self.filter_loader.currentData(), limit=30,
                project_type=self.project_type)
        except Exception as e:
            hits = []
            self.result_list.clear()
            QListWidgetItem(f"搜索失败:{e}", self.result_list)
        self.result_list.clear()
        for h in hits:
            author = h.get("author", "")
            dl = f"⬇{h.get('downloads', 0):,}" if h.get("downloads") else ""
            meta = "  ".join(x for x in (author, dl) if x)
            text = f"{h['title']}\n{h.get('description', '')[:60]}" + (f"\n{meta}" if meta else "")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, h)
            self.result_list.addItem(item)
        if not hits and not self.result_list.count():
            QListWidgetItem(t("(没有找到结果)", "(no results)"), self.result_list)

    def _on_selected(self, current, _prev):
        if current is None:
            return
        h = current.data(Qt.ItemDataRole.UserRole)
        if not h:
            return
        self._current = h
        for w in (self.icon_label, self.title_label, self.meta_label,
                  self.desc_label, self.gv_combo, self.loader_combo,
                  self.ver_combo, self.dl_btn):
            w.setVisible(True)
        self.empty_label.setVisible(False)
        self.title_label.setText(h["title"])
        meta = []
        if h.get("author"):
            meta.append(f"作者:{h['author']}")
        if h.get("downloads"):
            meta.append(f"⬇{h['downloads']:,}")
        if h.get("categories"):
            meta.append("·".join(h["categories"][:6]))
        self.meta_label.setText("  ".join(meta))
        self.desc_label.setText(h.get("description", ""))
        self.icon_label.setText("")
        icon_url = h.get("icon_url")
        if icon_url:
            threading.Thread(target=self._load_icon, args=(icon_url,), daemon=True).start()
        self._refresh_versions()

    def _load_icon(self, url: str):
        try:
            import requests
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                from PySide6.QtGui import QPixmap
                from PySide6.QtCore import QByteArray, QBuffer
                pix = QPixmap()
                pix.loadFromData(resp.content)
                QTimer.singleShot(0, lambda: (self.icon_label.setPixmap(
                    pix.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation))))
        except Exception:
            pass

    def _refresh_versions(self):
        if not getattr(self, "_current", None):
            return
        import modrinth
        slug = self._current["slug"]
        gv = self.gv_combo.currentText().strip()
        loader = self.loader_combo.currentData()
        versions = []
        if gv:
            try:
                versions = modrinth.list_mod_versions(slug, gv, loader)
            except Exception:
                versions = []
        self.ver_combo.clear()
        for v in versions:
            self.ver_combo.addItem(v, v)
        self.ver_combo.setEnabled(bool(versions))
        if versions:
            self.ver_combo.setCurrentIndex(0)

    # ---- 下载 ----
    def _download(self):
        if not getattr(self, "_current", None):
            return
        inst = self.selected_inst
        if inst is None and not self.custom_dir:
            self.inst_cards_toggle.setChecked(True)
            self._toggle_cards()
            self.inst_cards_toggle.setText("▾ 请先选目标实例(或选\"无\"手动选目录)")
            return
        target = None
        if inst:
            target = os.path.join(self.get_instance_dir(inst["id"]), self.sub_dir)
        elif self.custom_dir:
            target = self.custom_dir
        self.on_download(self._current, self.ver_combo.currentData(),
                         inst, target, self.sub_dir)

    def get_instance_dir(self, instance_id: str) -> str:
        """实例游戏目录(由外层注入)"""
        return self._instance_dir(instance_id)

    def set_instance_dir_fn(self, fn):
        self._instance_dir = fn


class ResourceCenter(QWidget):
    """下载新资源:左侧可折叠菜单 + 右侧分类面板(首页/实例/Mod/光影/数据包/资源包)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._instance_dir = lambda iid: iid
        self._on_download_cb = None
        self._get_inst_loader = lambda inst: inst.get("loader")

        # ---- 左侧菜单(可折叠) ----
        self.menu_widget = QWidget()
        self.menu_widget.setFixedWidth(150)
        self.menu_layout = QVBoxLayout(self.menu_widget)
        self.menu_layout.setContentsMargins(4, 4, 4, 4)
        self.menu_layout.setSpacing(4)
        self.collapse_btn = QPushButton("◀ 收起")
        self.collapse_btn.clicked.connect(self._toggle_menu)
        self.menu_layout.addWidget(self.collapse_btn)
        self._menu_buttons = []   # (按钮, 面板 index)
        for idx, (label, icon) in enumerate([
                (t("首页", "Home"), "🏠"),
                (t("实例", "Instances"), "📦"),
                ("🧩 " + t("Mod", "Mods"), None),
                ("🌄 " + t("光影包", "Shaders"), None),
                ("🗂 " + t("数据包", "Datapacks"), None),
                ("🎨 " + t("资源包", "Resourcepacks"), None)]):
            btn = QPushButton(icon + " " + label if label.startswith(("🏠", "📦")) else label)
            btn.setCheckable(True)
            btn.setStyleSheet(card_style())
            btn.clicked.connect(lambda _c, i=idx: self.switch_to(i))
            self.menu_layout.addWidget(btn)
            self._menu_buttons.append(btn)
        self.menu_layout.addStretch()

        # ---- 右侧面板 ----
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_home())            # 0 首页
        self.browsers = {}

        # 实例面板:下载新实例向导(复用 DownloadTab)
        from download_tab import DownloadTab
        self.download_tab = DownloadTab()
        self.download_tab.bind_start(self._on_start_instance)
        self.stack.addWidget(self.download_tab)             # 1 实例

        # 资源浏览器:Mod / 光影 / 数据包 / 资源包
        for idx, (ptype, label, sub) in enumerate(RESOURCE_CATEGORIES, start=2):
            br = ResourceBrowser(ptype, label, sub,
                                 on_download=self._browser_download,
                                 get_instance_loader=self._get_inst_loader)
            br.set_instance_dir_fn(self._instance_dir)
            self.browsers[ptype] = br
            self.stack.addWidget(br)                        # 2..5

        # ---- 布局 ----
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.menu_widget)
        layout.addWidget(self.stack, 1)
        self.switch_to(0)

    # ---- 菜单 ----
    def _toggle_menu(self):
        collapsed = self.menu_widget.width() < 60
        self.menu_widget.setFixedWidth(44 if not collapsed else 150)
        self.collapse_btn.setText("▶ 展开" if not collapsed else "◀ 收起")
        for btn in self._menu_buttons:
            btn.setText(btn.text()[:2] if not collapsed else btn.text())

    def switch_to(self, idx: int):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._menu_buttons):
            btn.setChecked(i == idx)

    # ---- 首页 ----
    def _build_home(self):
        home = QWidget()
        layout = QVBoxLayout(home)
        layout.setContentsMargins(16, 16, 16, 16)
        self.home_latest = QLabel(t("最新正式版: -- | 最新快照版: --",
                                    "Latest release: -- | Latest snapshot: --"))
        self.home_latest.setStyleSheet("font-weight: bold;")
        self.home_hint = QLabel(
            t("💡 提示:最新版游戏的 Mod 生态一般很不好(模组还没跟上),"
              "推荐使用模组活跃的版本,如 1.21.1 / 1.20.1。",
              "Tip: the newest MC version usually has poor mod support. "
              "Prefer active versions like 1.21.1 / 1.20.1."))
        self.home_hint.setWordWrap(True)
        self.home_hint.setStyleSheet(hint_style())
        layout.addWidget(self.home_latest)
        layout.addWidget(self.home_hint)
        layout.addSpacing(16)
        layout.addWidget(QLabel(t("像逛商场一样挑资源:", "Browse resources:")))
        cards = QHBoxLayout()
        entries = [
            (t("📦 创建实例", "Instances"), 1),
            ("🧩 " + t("Mod", "Mods"), 2),
            ("🌄 " + t("光影包", "Shaders"), 3),
            ("🗂 " + t("数据包", "Datapacks"), 4),
            ("🎨 " + t("资源包", "Resourcepacks"), 5),
        ]
        for text, idx in entries:
            b = QPushButton(text)
            b.setMinimumSize(120, 80)
            b.setStyleSheet(card_style())
            b.clicked.connect(lambda _c, i=idx: self.switch_to(i))
            cards.addWidget(b)
        layout.addLayout(cards)
        layout.addStretch()
        return home

    # ---- 对外接口 ----
    def set_hooks(self, instance_dir, on_download, on_start_instance):
        """注入:实例目录函数 / 下载回调 / 开始下载实例回调"""
        self._instance_dir = instance_dir
        self._on_download_cb = on_download
        self._on_start_cb = on_start_instance
        for br in self.browsers.values():
            br.set_instance_dir_fn(instance_dir)

    def set_latest_versions(self, release: str, snapshot: str):
        self.home_latest.setText(
            t(f"最新正式版: {release} | 最新快照版: {snapshot}",
              f"Latest release: {release} | Latest snapshot: {snapshot}"))

    def refresh_browser_instances(self, instances: list):
        """刷新各资源浏览器里的目标实例卡片"""
        for br in self.browsers.values():
            br.set_instances(instances)

    def _browser_download(self, hit, version, inst, target_dir, sub_dir):
        if self._on_download_cb:
            self._on_download_cb(hit, version, inst, target_dir, sub_dir)

    def _on_start_instance(self):
        if hasattr(self, "_on_start_cb") and self._on_start_cb:
            self._on_start_cb()
