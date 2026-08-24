# -*- coding: utf-8 -*-
"""
「下载新资源」综合入口:像逛商场一样挑资源。

- 左侧可折叠菜单栏:首页 / 实例 / Mod / 光影包 / 数据包 / 资源包
- 右侧分类面板:
  - 首页:分类大卡片入口 + 最新版本提示(最新版 mod 生态一般很不好)
  - 实例:下载新实例向导(版本树 → 加载器 → 光影/优化)
  - Mod / 光影包 / 数据包 / 资源包:同一套"资源浏览器"
    (搜索 + 目标实例 + 筛选 + 结果列表 + 详情面板,信息丰富)

设计要点:
- 目标实例在 ResourceCenter 层全局共享:在一个分类页选了实例,其他分类页一并生效。
- 搜索 / 项目详情 / 版本列表全部走后台线程(异步),不卡 UI。
- 「游戏版本 / 加载器 / 版本」三个组合框由项目数据填充,版本真正驱动下载。
"""
import os
import queue
import threading
import urllib.parse

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from i18n import t
from ui_style import (card_btn_style, hint_style, launch_btn_style, list_style,
                      muted_color, panel_style, text_color)

# 资源分类(左侧菜单 + Modrinth project_type + 安装目录子文件夹)
RESOURCE_CATEGORIES = [
    ("mod", "🧩 Mod", "mods"),
    ("shader", "🌄 光影包", "shaderpacks"),
    ("datapack", "🗂 数据包", "datapacks"),
    ("resourcepack", "🎨 资源包", "resourcepacks"),
]

# 标签(分类)多级菜单结构:按逻辑分组(中文组名→Modrinth 分类)。替代以前"手输标签"。
# - mod/modpack 的 Modrinth 分类全是 header="categories"(扁平)→ 按语义分组;
# - shader/resourcepack 用 Modrinth 的 header 分组(特性/风格/分辨率/性能影响);
# - datapack 在 Modrinth 暂无分类标签 → 空(按钮禁用)。
_CATEGORY_GROUPS = {
    "mod": [
        ("玩法", ["adventure", "cursed", "game-mechanics", "magic", "minigame", "mobs", "worldgen"]),
        ("内容", ["decoration", "economy", "equipment", "food", "storage", "transportation"]),
        ("功能", ["library", "management", "social", "technology", "utility"]),
        ("性能", ["optimization"]),
    ],
    "modpack": [
        ("玩法", ["adventure", "combat", "magic", "quests", "multiplayer"]),
        ("内容", ["kitchen-sink", "challenging"]),
        ("性能", ["optimization", "lightweight"]),
    ],
    "shader": [
        ("特性", ["atmosphere", "bloom", "colored-lighting", "foliage", "path-tracing",
                  "pbr", "reflections", "shadows"]),
        ("风格", ["cartoon", "cursed", "fantasy", "realistic", "semi-realistic", "vanilla-like"]),
        ("性能影响", ["high", "low", "medium", "potato", "screenshot"]),
    ],
    "resourcepack": [
        ("分辨率", ["128x", "16x", "256x", "32x", "48x", "512x+", "64x", "8x-"]),
        ("特性", ["audio", "blocks", "core-shaders", "entities", "environment", "equipment",
                  "fonts", "gui", "items", "locale", "models"]),
        ("风格", ["combat", "cursed", "decoration", "modded", "realistic", "simplistic",
                  "themed", "tweaks", "utility", "vanilla-like"]),
    ],
    "datapack": [],   # 数据包暂无分类标签
}


def _tag_groups(project_type: str) -> list:
    """项目类型 → [(中文组名, [Modrinth 分类...]), ...];空 = 该类型无分类。"""
    return _CATEGORY_GROUPS.get(project_type, [])

# MC 社区资源结构科普(首页展示,让想自己挑资源的人先看懂"都是些什么";
# ui_mode=全面 时显示,摘要 时隐藏)
_RESOURCE_GUIDE = [
    "🧩 Mod:修改/扩展游戏玩法(如机械动力、JEI 物品管理器),放进 mods 文件夹,"
    "需要 Fabric/Forge/NeoForge 加载器才能用",
    "🌄 光影包:只改画面渲染(光线/水面/天空),放进 shaderpacks,"
    "需要 Iris/Oculus 等光影加载器配合",
    "🗂 数据包:原版官方支持的玩法调整(配方/生成/难度),放进存档的 datapacks 文件夹,"
    "不需要加载器",
    "🎨 资源包:改纹理/音效/界面外观,不改变玩法,放进 resourcepacks,原版直接支持",
    "📦 整合包:Mod + 配置 + 可选存档的一键合集,适合想直接玩成品的人",
    "⚡ 辅助 Mod:性能优化(钠/锂)和信息显示(玉/JEI),推荐先装这些",
]


class FlowLayout(QLayout):
    """响应式流式布局:widget 放不下时自动换到下一行(用于首页分类卡片等)。"""

    def __init__(self, parent=None, margin=0, hspacing=10, vspacing=10):
        super().__init__(parent)
        self._items = []
        self._hspace = hspacing
        self._vspace = vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_height = effective.x(), effective.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > effective.right() + 1 and line_height > 0:
                x = effective.x()
                y += line_height + self._vspace
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._hspace
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + m.bottom()


class ResourceBrowser(QWidget):
    """资源浏览器(Mod / 光影包 / 数据包 / 资源包共用):
    目标实例(可折叠,全局共享) + 筛选 + 搜索(异步) + 结果列表 + 详情面板(版本/加载器/下载)。"""

    def __init__(self, project_type: str, label: str, sub_dir: str,
                 on_download, get_instance_loader, parent=None, is_modpack: bool = False):
        super().__init__(parent)
        self.project_type = project_type
        self.label = label
        self.sub_dir = sub_dir            # mods / shaderpacks / ...
        self.on_download = on_download    # (slug, version, inst, custom_dir) -> 结果
        self.get_instance_loader = get_instance_loader
        self.is_modpack = is_modpack      # 整合包:下载 .mrpack 并导入成"新实例",不装进已有实例
        self.on_modpack_download = None   # 整合包下载回调(hit, version) -> 由外层注入

        # 目标实例:镜像全局共享的(inst, custom_dir);真正的单一来源在 ResourceCenter
        self.selected_inst = None
        self.custom_dir = None
        self._target_getter = lambda: (None, None)
        self._target_setter = lambda inst, dir_: None

        # 异步队列(网络请求不卡 UI),带缓存
        self._async_q = queue.Queue()
        self._async_cache = {}
        self._async_timer = QTimer(self)
        self._async_timer.timeout.connect(self._drain_async)
        self._async_timer.start(60)

        # 是否已加载过「默认浏览」(打开页即显示列表);已加载则不重复拉取
        self._auto_loaded = False

        self._build_ui()

    def _build_ui(self):
        # ---- 搜索区 ----
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            t(f"搜索{self.label},如 sodium / 钠 / 名字(回车搜索)", f"Search {self.label}..."))
        self.search_edit.returnPressed.connect(self.do_search)
        search_btn = QPushButton(t("搜索", "Search"))
        search_btn.clicked.connect(self.do_search)
        search_btn.setStyleSheet(card_btn_style())

        self.sort_combo = QComboBox()
        for lbl, val in [("按下载量排序", "downloads"),
                         ("按相关度排序", "relevance"),
                         ("按最近更新", "updated")]:
            self.sort_combo.addItem(t(lbl, lbl), val)

        # 标签(分类)多级菜单:替代以前"手输标签"。点开是一棵分组菜单,可多选。
        self.tag_btn = QToolButton()
        self.tag_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.tag_btn.setStyleSheet(card_btn_style())
        self.tag_btn.setToolTip("按分类标签筛选(可多选;组内是子菜单)")
        self._selected_tags = set()
        self.tag_menu = QMenu(self.tag_btn)
        self.tag_btn.setMenu(self.tag_menu)
        self._build_tag_menu()

        # ---- 目标实例(折叠):装到哪个实例的对应目录(全局共享) ----
        self.inst_cards_toggle = QPushButton("▸ 目标实例: 未选择")
        self.inst_cards_toggle.setCheckable(True)
        self.inst_cards_toggle.setChecked(False)
        self.inst_cards_toggle.clicked.connect(self._toggle_cards)
        self.inst_cards_toggle.setStyleSheet(card_btn_style())
        self.instance_cards_box = QWidget()
        self.instance_cards_layout = QVBoxLayout(self.instance_cards_box)
        self.instance_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.instance_cards_layout.setSpacing(4)
        self._inst_cards = []          # [(inst, card)]
        self._none_card = None
        self.custom_label = QLabel("")
        self.custom_label.setStyleSheet(hint_style())
        self.custom_label.setWordWrap(True)
        # 实例可能很多:卡片区放进可滚动容器,展开时也不把筛选/搜索挤出界面
        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setWidget(self.instance_cards_box)
        self.cards_scroll.setMaximumHeight(210)
        self.cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cards_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        self.cards_scroll.setVisible(False)

        # ---- 筛选(游戏版本 + 加载器) ----
        self.filter_version = QComboBox()
        self.filter_version.setEditable(True)
        self.filter_version.setToolTip("筛选的游戏版本,可自行输入")
        self.filter_loader = QComboBox()
        self.filter_loader.addItem(t("全部加载器", "All loaders"), None)
        for label, value in [("Fabric", "fabric"), ("Forge", "forge"),
                             ("NeoForge", "neoforge"), ("Quilt", "quilt")]:
            self.filter_loader.addItem(label, value)

        # ---- 结果列表 + 详情面板 ----
        self.result_list = QListWidget()
        self.result_list.setWordWrap(True)
        self.result_list.setStyleSheet(list_style())
        self.result_list.currentItemChanged.connect(self._on_selected)

        self.panel = QWidget()
        self.panel.setStyleSheet(panel_style())
        self.panel.setMinimumWidth(260)
        self.panel.setMaximumWidth(500)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(56, 56)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label = QLabel("")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(f"font-weight: bold; font-size: 15px; color: {text_color()};")
        self.meta_label = QLabel("")
        self.meta_label.setStyleSheet(hint_style())
        self.meta_label.setWordWrap(True)
        self.desc_label = QLabel("")
        self.desc_label.setStyleSheet(hint_style())
        self.desc_label.setWordWrap(True)
        self.desc_note_label = QLabel("")
        self.desc_note_label.setWordWrap(True)
        self.desc_note_label.setStyleSheet(f"color: {muted_color()}; font-size: 11px;")
        self.desc_note_label.setVisible(False)
        # 「在 MC百科查看」链接:仅选中时显示,点击用系统浏览器打开 mcmod 按名搜索页。
        self.mcmod_link = QLabel()
        self.mcmod_link.setTextFormat(Qt.TextFormat.RichText)
        self.mcmod_link.setOpenExternalLinks(False)   # 点击走 QDesktopServices,统一 URL 构造
        self.mcmod_link.linkActivated.connect(self._open_mcmod_link)
        self.mcmod_link.setStyleSheet("color: #5B8DEF; font-size: 12px;")
        self.mcmod_link.setVisible(False)
        self.gv_combo = QComboBox()
        self.loader_combo = QComboBox()
        self.ver_combo = QComboBox()
        self.dl_btn = QPushButton(t("下载", "Download"))
        self.dl_btn.setStyleSheet(launch_btn_style())
        self.dl_btn.clicked.connect(self._download)
        self.gv_combo.currentIndexChanged.connect(self._refresh_versions)
        self.loader_combo.currentIndexChanged.connect(self._refresh_versions)

        p = QVBoxLayout(self.panel)
        p.setContentsMargins(14, 14, 14, 14)
        p.setSpacing(8)
        p.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignCenter)
        p.addWidget(self.title_label)
        p.addWidget(self.meta_label)
        p.addWidget(self.desc_label)
        p.addWidget(self.desc_note_label)
        p.addWidget(self.mcmod_link)
        for _lbl, combo in [(t("游戏版本:", "Game version:"), self.gv_combo),
                            (t("加载器:", "Loader:"), self.loader_combo),
                            (t("版本:", "Version:"), self.ver_combo)]:
            row = QHBoxLayout()
            row.addWidget(QLabel(_lbl))
            row.addWidget(combo, 1)
            p.addLayout(row)
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
        layout.setSpacing(8)
        if self.is_modpack:
            # 整合包=一键全集:下载后作为「新实例」导入,无需选目标实例/目录
            self.modpack_hint = QLabel(
                t("📦 整合包=Mod+配置(+可选存档)的一键合集。选好版本点「下载」,"
                  "会自动下载 .mrpack 并作为【新实例】导入(自动装基础+加载器+全部 mod),"
                  "不用先选目标实例。",
                  "Modpack = mods+config(+optional saves) in one. Pick a version and Download: "
                  "it auto-downloads the .mrpack and imports as a NEW instance."))
            self.modpack_hint.setStyleSheet(hint_style())
            self.modpack_hint.setWordWrap(True)
            layout.addWidget(self.modpack_hint)
            self.inst_cards_toggle.setVisible(False)
            self.cards_scroll.setVisible(False)
            self.custom_label.setVisible(False)
        else:
            layout.addWidget(self.inst_cards_toggle)
            layout.addWidget(self.cards_scroll)
            layout.addWidget(self.custom_label)
        layout.addLayout(self._row(self.filter_version, self.filter_loader))
        # 排序(占 1)+ 标签多级菜单(不拉宽)
        tags_row = QHBoxLayout()
        tags_row.addWidget(self.sort_combo, 1)
        tags_row.addWidget(self.tag_btn)
        layout.addLayout(tags_row)
        layout.addLayout(self._row(self.search_edit, search_btn))
        layout.addWidget(self.split, 1)

        # 切换排序时,若处于默认浏览(空关键词)则重新拉取
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)

    def _row(self, *widgets):
        r = QHBoxLayout()
        for w in widgets:
            r.addWidget(w, 1)
        return r

    # ---- 标签多级菜单 ----
    def _build_tag_menu(self):
        """重建标签菜单:先清空,再按 project_type 的结构重建(勾选态跟 self._selected_tags)。"""
        self.tag_menu.clear()
        self._tag_actions = []
        groups = _tag_groups(self.project_type)
        if not groups:
            self.tag_btn.setEnabled(False)
            self.tag_btn.setText(t("无标签", "No tags"))
            return
        self.tag_btn.setEnabled(True)
        for group_label, cats in groups:
            sub = self.tag_menu.addMenu(t(group_label, group_label))
            for cat in cats:
                a = sub.addAction(cat)
                a.setCheckable(True)
                a.setData(cat)
                a.setChecked(cat in self._selected_tags)
                # triggered 在 Qt 勾选态变更之后发出,isChecked() 即最新勾选态(真实菜单点击下可靠)
                a.triggered.connect(lambda _ch=False, act=a: self._on_tag_toggled(act))
                self._tag_actions.append(a)
        self.tag_menu.addSeparator()
        clr = self.tag_menu.addAction(t("清除所有标签", "Clear all tags"))
        clr.setEnabled(bool(self._selected_tags))
        clr.triggered.connect(self._clear_tags)
        self._update_tag_btn()

    def _on_tag_toggled(self, act: QAction):
        cat = act.data()
        if act.isChecked():
            self._selected_tags.add(cat)
        else:
            self._selected_tags.discard(cat)
        self._update_tag_btn()
        # 开启/取消标签时,若有默认浏览(空关键词)也刷一下,让结果跟着分类走
        self.do_search()

    def _update_tag_btn(self):
        n = len(self._selected_tags)
        self.tag_btn.setText(f"标签 {n}✓ ▾" if n else "标签 ▾")

    def _clear_tags(self):
        if self._selected_tags:
            self._selected_tags.clear()
            self._build_tag_menu()   # 重建,取消所有勾选 + 清空项禁用
            self.do_search()

    # ---- 目标实例(全局共享) ----
    def _set_target_hooks(self, getter, setter):
        self._target_getter = getter
        self._target_setter = setter

    def set_instances(self, instances: list):
        """刷新实例卡片(可选的安装目标),并反映当前全局目标。"""
        for _inst, card in self._inst_cards:
            card.deleteLater()
        self._inst_cards = []
        self.instance_cards_layout.takeAt(0)
        self.instance_cards_layout.takeAt(0)  # 清空"无"卡片
        for inst in instances:
            card = QPushButton(inst["label"])
            card.setCheckable(True)
            card.setMinimumHeight(40)
            card.setStyleSheet(card_btn_style())
            card.clicked.connect(lambda _c, i=inst: self._select_inst(i))
            self.instance_cards_layout.addWidget(card)
            self._inst_cards.append((inst, card))
        none_card = QPushButton(t("无(手动选目录)", "None (pick folder)"))
        none_card.setCheckable(True)
        none_card.setMinimumHeight(40)
        none_card.setStyleSheet(card_btn_style())
        none_card.clicked.connect(self._select_none)
        self.instance_cards_layout.addWidget(none_card)
        self._none_card = none_card
        # 内容区最小高度 = 卡片数×(卡片高40 + 间距4):widgetResizable 不会把 box 压到低于该值,
        # 内容超出视口(210)时滚动区才真正滚动,而不是把卡片压扁/互相重叠
        n = len(self._inst_cards) + (1 if self._none_card else 0)
        self.instance_cards_box.setMinimumHeight(n * 44)
        self.cards_scroll.updateGeometry()

        self._sync_target_ui()

    def _apply_inst_cards(self, inst_id):
        """把卡片勾选状态对齐到某个实例(inst_id 为 None 时勾"无")。"""
        for i, card in self._inst_cards:
            card.setChecked(i["id"] == inst_id)
        if self._none_card:
            self._none_card.setChecked(inst_id is None)

    def _sync_target_ui(self):
        """把全局目标反映到本浏览器的文案/勾选状态。不触发 setter,避免递归。"""
        inst, dir_ = self._target_getter()
        self.selected_inst = inst
        self.custom_dir = dir_
        if inst is not None:
            self.inst_cards_toggle.setText(f"▸ 目标实例: {inst['id']}")
            self._apply_inst_cards(inst["id"])
            self.custom_label.setText("")
        elif dir_:
            self.inst_cards_toggle.setText("▸ 目标实例: 自定义目录")
            self._apply_inst_cards(None)
            self.custom_label.setText(f"{t('安装到', 'Install to')}: {dir_}")
            self.custom_label.setVisible(True)
        else:
            self.inst_cards_toggle.setText("▸ 目标实例: 未选择")
            self._apply_inst_cards(None)

    def _toggle_cards(self):
        show = self.inst_cards_toggle.isChecked()
        self.cards_scroll.setVisible(show)
        self.inst_cards_toggle.setText(
            ("▾ " if show else "▸ ") + self.inst_cards_toggle.text()[2:])

    def _select_inst(self, inst):
        """选中某实例:更新本地卡片+筛选,并广播到全局(其他分类页一并生效)。"""
        self._apply_inst_cards(inst["id"])
        # 选中后自动折叠目标实例区,界面清爽
        self.inst_cards_toggle.setChecked(False)
        self.cards_scroll.setVisible(False)
        # 筛选同步到该实例的基础版本 + 加载器
        self.filter_version.setCurrentText(inst["base"])
        idx = self.filter_loader.findData(inst["loader"])
        if idx >= 0:
            self.filter_loader.setCurrentIndex(idx)
        self._target_setter(inst, None)

    def _select_none(self):
        """选"无":改用自定义目录(或稍后手动选位置),并广播全局。"""
        self._target_setter(None, None)

    def pick_custom_dir(self, game_dir: str):
        """用户用文件管理器选安装位置(装到其他启动器的目录)。"""
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, t("选择安装位置", "Pick folder"), game_dir)
        if d:
            self._target_setter(None, d)

    # ---- 异步基础设施 ----
    def _async(self, cache_key, fetch, on_done, cache: bool = True):
        """后台线程跑网络请求 fetch(),完成后回主线程调 on_done(结果)。
        cache=True 时按 cache_key 缓存,第二次直接同步回调;False 则总是重新请求。"""
        if cache and cache_key in self._async_cache:
            on_done(self._async_cache[cache_key])
            return

        def worker():
            try:
                result = fetch()
            except Exception:
                result = None
            self._async_q.put((cache_key, result, on_done, cache))

        threading.Thread(target=worker, daemon=True).start()

    def _drain_async(self):
        """主线程:把后台结果搬回 UI。"""
        while True:
            try:
                cache_key, result, on_done, cache = self._async_q.get_nowait()
            except queue.Empty:
                return
            if cache:
                self._async_cache[cache_key] = result
            try:
                on_done(result)
            except Exception:
                pass

    # ---- 搜索 ----
    def do_search(self):
        query = self.search_edit.text().strip()
        # 允许空关键词:打开资源页即「默认浏览」(空 query → 按 sort_combo 排序,默认 downloads)。
        # 目标实例/加载器/版本筛选会被尊重(为空则全量);不覆盖用户已输入的关键词。
        gv = self.filter_version.currentText().strip()
        loader = self.filter_loader.currentData()
        order = self.sort_combo.currentData() or "downloads"
        tags = ",".join(sorted(self._selected_tags))
        self._last_query = query
        self.result_list.clear()
        QListWidgetItem(t("搜索中...", "Searching..."), self.result_list)

        def fetch():
            import modrinth
            return modrinth.search_mods_cn(
                query, gv, loader, limit=30, project_type=self.project_type,
                order_by=order, tags=tags)

        self._async(("search", query, gv, loader, self.project_type, order, tags),
                    fetch, self._fill_results, cache=False)

    def maybe_auto_load(self):
        """打开/切到本资源页时,若搜索框为空,自动触发一次「默认浏览」。
        已加载过默认浏览(或正在显示)则不再重复拉取;不覆盖用户已输入的关键词。"""
        if self.search_edit.text().strip():
            return
        if getattr(self, "_auto_loaded", False):
            return
        self.do_search()

    def _on_sort_changed(self):
        """排序切换:处于默认浏览(空关键词)时重新拉取,让列表按新排序刷新。"""
        if self.search_edit.text().strip():
            return
        self.do_search()

    def _fill_results(self, hits):
        self.result_list.clear()
        if hits is None:
            self._auto_loaded = False
            QListWidgetItem(t("搜索失败,请检查网络", "Search failed, check network"), self.result_list)
            return
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
        # 记录默认浏览是否已加载(空关键词的结果),供 maybe_auto_load 判断是否重复拉取
        self._auto_loaded = (getattr(self, "_last_query", "") == "")

    # ---- 详情面板 ----
    def _mcmod_url(self, display_name: str) -> str:
        """构造在 MC百科(mcmod.cn)按名搜索该 Mod 的链接;用 quote 编码中文/特殊字符。
        mcmod 用自己的 class id,与 Modrinth slug 非 1:1,故用「按名搜索」最稳。"""
        return "https://search.mcmod.cn/s?key=" + urllib.parse.quote(display_name)

    def _open_mcmod_link(self, url: str):
        """点击链接 → 系统浏览器打开 mcmod 搜索页。仅用户主动打开,无爬取/缓存/入库。"""
        QDesktopServices.openUrl(QUrl(url))

    def _on_selected(self, current, _prev):
        if current is None:
            self.mcmod_link.setVisible(False)
            return
        h = current.data(Qt.ItemDataRole.UserRole)
        if not h:
            self.mcmod_link.setVisible(False)
            return
        self._current = h
        for w in (self.icon_label, self.title_label, self.meta_label,
                  self.desc_label, self.gv_combo, self.loader_combo,
                  self.ver_combo, self.dl_btn):
            w.setVisible(True)
        self.empty_label.setVisible(False)
        self.title_label.setText(h["title"])
        # 「在 MC百科查看」链接:用显示名(优先已替换的中文名)按名搜索,中文最准;
        # 标题为空 → 退回 slug/描述(纯英文标题即 Modrinth 原名,也直接可用)。
        name = (h.get("title") or "").strip()
        if not name:
            name = (h.get("slug") or "").strip()
        if not name:
            name = (h.get("description") or "").strip()[:80]
        if name:
            self.mcmod_link.setText(
                '<a href="%s">🔗 %s</a>' % (
                    self._mcmod_url(name),
                    t("在 MC百科查看", "View on MC百科 (mcmod.cn)")))
            self.mcmod_link.setVisible(True)
        else:
            self.mcmod_link.setVisible(False)
        meta = []
        if h.get("author"):
            meta.append(f"作者:{h['author']}")
        if h.get("downloads"):
            meta.append(f"⬇{h['downloads']:,}")
        if h.get("categories"):
            meta.append("·".join(h["categories"][:6]))
        self.meta_label.setText("  ".join(meta))
        self.desc_label.setText(h.get("description", ""))
        self.desc_note_label.setText("")
        self.desc_note_label.setVisible(False)
        self.icon_label.setText("")
        icon_url = h.get("icon_url")
        if icon_url:
            threading.Thread(target=self._load_icon, args=(icon_url,), daemon=True).start()
        # 异步加载项目支持的版本/加载器,并刷新版本下拉
        self.gv_combo.clear()
        self.loader_combo.clear()
        self.ver_combo.clear()
        self._load_project(h)
        # 后台线程翻译 Mod 描述(不卡 UI);若关闭开关则保持原文
        self._start_desc_translation(h)

    def _start_desc_translation(self, h):
        """后台线程翻译当前 Mod 描述(英→中),不卡 UI。

        遵守 mod_translate 规则:
        - `ai_mod_translate` 关 → 直接显示原文(无翻译调用);
        - 本身已中文 / 空文本 → 原样;
        - 命中缓存 → 秒回(二次打开不再触发推理);
        - 引擎不可用 → 优雅显示原文 + 失败标注,不报错。
        结果只在当前选中的项目没变时才应用(避免快速切换时旧结果覆盖新选择)。"""
        desc = (h.get("description") or "").strip()
        requested_slug = h.get("slug", "")
        if not desc:
            self.desc_note_label.setVisible(False)
            return
        try:
            import mod_translate
            if not mod_translate.enabled():
                self.desc_note_label.setVisible(False)
                return
            # 本身已中文 → 无需翻译,也不闪"翻译中"占位
            if mod_translate._has_cjk(desc):
                self.desc_note_label.setVisible(False)
                return
        except Exception:
            self.desc_note_label.setVisible(False)
            return

        # 翻译中提示(占位文案,完成后替换)
        self.desc_note_label.setText(t("🔄 正在翻译描述…", "🔄 Translating…"))
        self.desc_note_label.setStyleSheet(f"color: {muted_color()}; font-size: 11px;")
        self.desc_note_label.setVisible(True)

        def fetch():
            try:
                import mod_translate
                return mod_translate.translate_text_safe(desc, slug=requested_slug, field="description")
            except Exception:
                return None

        def on_done(result):
            # 结果只在当前选中的项目仍等于本次请求时应用
            cur = getattr(self, "_current", None)
            if not cur or cur.get("slug") != requested_slug:
                return
            self._apply_translation(result)

        # cache=False:让 mod_translate 每次重新读 enabled()/缓存,避免把"关闭时"的
        # 结果长期缓存到 _async_cache(否则用户之后打开开关也不生效)。
        self._async(("tr", requested_slug), fetch, on_done, cache=False)

    def _apply_translation(self, result):
        """把翻译结果应用到详情面板:中文 + 机翻标注 / 失败/关闭 → 原文。"""
        if not result or not isinstance(result, dict):
            # 未知异常:保持原文,清掉提示
            self.desc_note_label.setVisible(False)
            return
        source = result.get("source")
        text = result.get("text") or ""
        if source == "disabled":
            self.desc_label.setText(text)
            self.desc_note_label.setVisible(False)
            return
        if source == "already_cn" or source == "original":
            self.desc_label.setText(text)
            self.desc_note_label.setVisible(False)
            return
        if source == "failed":
            self.desc_label.setText(text)
            self.desc_note_label.setText(t("⚠ 翻译失败,已显示原文", "⚠ Translation failed, showing original"))
            self.desc_note_label.setStyleSheet(f"color: #c78a2e; font-size: 11px;")
            self.desc_note_label.setVisible(True)
            return
        if result.get("machine"):
            self.desc_label.setText(text)
            note = t("🤖 机翻仅供参考,请以英文原意为准", "🤖 Machine translation, see original for accuracy")
            if result.get("confidence") == "low":
                note = t("🤖 机翻仅供参考(低可信),请以英文原意为准",
                         "🤖 Machine translation (low confidence), see original")
            self.desc_note_label.setText(note)
            self.desc_note_label.setStyleSheet(f"color: #c78a2e; font-size: 11px;")
            self.desc_note_label.setVisible(True)
            return
        # 兜底:显示原文
        self.desc_label.setText(text)
        self.desc_note_label.setVisible(False)

    def _load_icon(self, url: str):
        try:
            import requests
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                from PySide6.QtGui import QPixmap
                pix = QPixmap()
                pix.loadFromData(resp.content)
                QTimer.singleShot(0, lambda: self.icon_label.setPixmap(
                    pix.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)))
        except Exception:
            pass

    def _load_project(self, h):
        """异步拉项目详情,填充 游戏版本/加载器 两个下拉。"""
        def fetch():
            import modrinth
            return modrinth.get_project(h["slug"])
        self._async(("proj", h["slug"]), fetch, self._populate_project)

    def _populate_project(self, proj):
        if not proj:
            return
        # Modrinth 的 game_versions 一般是升序,转成最新在前
        gvs = list(reversed(proj.get("game_versions", [])))
        loaders = proj.get("loaders", [])
        self.gv_combo.clear()
        for gv in gvs:
            self.gv_combo.addItem(gv, gv)
        self.loader_combo.clear()
        for ld in loaders:
            self.loader_combo.addItem(ld, ld)
        # 默认对齐:优先目标实例的基础版本/加载器
        inst = self.selected_inst
        if inst:
            i = self.gv_combo.findText(inst["base"])
            if i >= 0:
                self.gv_combo.setCurrentIndex(i)
            li = self.loader_combo.findData(inst["loader"])
            if li >= 0:
                self.loader_combo.setCurrentIndex(li)
        self._refresh_versions()

    def _refresh_versions(self):
        if not getattr(self, "_current", None):
            return
        slug = self._current["slug"]
        gv = self.gv_combo.currentText().strip()
        loader = self.loader_combo.currentData()
        self.ver_combo.clear()
        self.ver_combo.addItem(t("加载中...", "Loading..."), None)
        self.ver_combo.setEnabled(False)
        if not gv:
            self.ver_combo.clear()
            self.ver_combo.setEnabled(False)
            return

        def fetch():
            import modrinth
            return modrinth.list_mod_versions(slug, gv, loader)
        self._async(("ver", slug, gv, loader), fetch, self._fill_versions)

    def _fill_versions(self, versions):
        self.ver_combo.clear()
        if not versions:
            self.ver_combo.addItem(t("(暂无可用版本)", "(no versions)"), None)
            self.ver_combo.setEnabled(False)
            return
        for v in versions:
            self.ver_combo.addItem(v, v)
        self.ver_combo.setEnabled(True)
        self.ver_combo.setCurrentIndex(0)

    # ---- 下载 ----
    def _download(self):
        if not getattr(self, "_current", None):
            return
        if self.is_modpack:
            # 整合包:下载 .mrpack → 导入成新实例(无需目标实例)
            if self.on_modpack_download:
                self.on_modpack_download(self._current, self.ver_combo.currentData())
            else:
                self.inst_cards_toggle.setChecked(True)
                self._toggle_cards()
                self.inst_cards_toggle.setText("▾ 整合包下载未接好(请联系开发者)")
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
    """下载新资源:左侧可折叠菜单 + 右侧分类面板(首页/实例/Mod/光影/数据包/资源包)。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._instance_dir = lambda iid: iid
        self._on_download_cb = None
        self._get_inst_loader = lambda inst: inst.get("loader")

        # 全局目标实例(四个分类页共享)
        self._shared_inst = None
        self._shared_dir = None

        # ---- 左侧菜单(可折叠) ----
        self.menu_widget = QWidget()
        self.menu_widget.setFixedWidth(150)
        self.menu_layout = QVBoxLayout(self.menu_widget)
        self.menu_layout.setContentsMargins(8, 8, 8, 8)
        self.menu_layout.setSpacing(4)
        self.collapse_btn = QPushButton("◀ 收起")
        self.collapse_btn.setStyleSheet(card_btn_style())
        self.collapse_btn.clicked.connect(self._toggle_menu)
        self.menu_layout.addWidget(self.collapse_btn)
        self._menu_buttons = []   # (按钮, 面板 index)
        for idx, (label, icon) in enumerate([
                (t("首页", "Home"), "🏠"),
                (t("实例", "Instances"), "📦"),
                ("🎁 " + t("整合包", "Modpacks"), None),
                ("🧩 " + t("Mod", "Mods"), None),
                ("🌄 " + t("光影包", "Shaders"), None),
                ("🗂 " + t("数据包", "Datapacks"), None),
                ("🎨 " + t("资源包", "Resourcepacks"), None)]):
            btn = QPushButton(icon + " " + label if label.startswith(("🏠", "📦")) else label)
            btn.setCheckable(True)
            btn.setStyleSheet(card_btn_style())
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

        # 整合包:像 Mod 一样浏览 Modrinth 整合包,点「下载」自动导入成新实例
        mp = ResourceBrowser("modpack", t("整合包", "Modpacks"), "",
                             on_download=self._browser_download,
                             get_instance_loader=self._get_inst_loader,
                             is_modpack=True)
        mp.on_modpack_download = self._on_modpack_download
        mp.set_instance_dir_fn(self._instance_dir)
        mp._set_target_hooks(self._get_shared_target, self._set_shared_target)
        self.browsers["modpack"] = mp
        self.stack.addWidget(mp)                            # 2 整合包

        # 资源浏览器:Mod / 光影 / 数据包 / 资源包
        for idx, (ptype, label, sub) in enumerate(RESOURCE_CATEGORIES, start=3):
            br = ResourceBrowser(ptype, label, sub,
                                 on_download=self._browser_download,
                                 get_instance_loader=self._get_inst_loader)
            br.set_instance_dir_fn(self._instance_dir)
            br._set_target_hooks(self._get_shared_target, self._set_shared_target)
            self.browsers[ptype] = br
            self.stack.addWidget(br)                        # 3..6

        # ---- 布局 ----
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.menu_widget)
        layout.addWidget(self.stack, 1)
        self.switch_to(0)

    # ---- 全局目标实例 ----
    def _get_shared_target(self):
        return self._shared_inst, self._shared_dir

    def _set_shared_target(self, inst, dir_):
        self._shared_inst = inst
        self._shared_dir = dir_
        for br in self.browsers.values():
            br._sync_target_ui()

    # ---- 菜单 ----
    def _toggle_menu(self):
        collapsed = self.menu_widget.width() < 60
        self.menu_widget.setFixedWidth(44 if not collapsed else 150)
        self.collapse_btn.setText("▶ 展开" if not collapsed else "◀ 收起")
        for btn in self._menu_buttons:
            btn.setText(btn.text()[:2] if not collapsed else btn.text())

    def switch_to(self, idx: int):
        self.stack.setCurrentIndex(idx)
        # 切到资源浏览器页且搜索框为空 → 自动默认浏览(打开即显示列表,无需先搜索)
        cur = self.stack.currentWidget()
        if isinstance(cur, ResourceBrowser):
            cur.maybe_auto_load()
        for i, btn in enumerate(self._menu_buttons):
            btn.setChecked(i == idx)

    # ---- 首页 ----
    def _build_home(self):
        home = QWidget()
        layout = QVBoxLayout(home)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        self.home_latest = QLabel(t("最新正式版: -- | 最新快照版: --",
                                    "Latest release: -- | Latest snapshot: --"))
        self.home_latest.setStyleSheet(f"font-weight: bold; font-size: 15px; color: {text_color()};")
        self.home_hint = QLabel(
            t("💡 提示:最新版游戏的 Mod 生态一般很不好(模组还没跟上),"
              "推荐使用模组活跃的版本,如 1.21.1 / 1.20.1。",
              "Tip: the newest MC version usually has poor mod support. "
              "Prefer active versions like 1.21.1 / 1.20.1."))
        self.home_hint.setWordWrap(True)
        self.home_hint.setStyleSheet(hint_style())
        layout.addWidget(self.home_latest)
        layout.addWidget(self.home_hint)
        layout.addSpacing(14)
        layout.addWidget(QLabel(t("像逛商场一样挑资源:", "Browse resources:")))
        cards = FlowLayout(hspacing=12, vspacing=12)
        entries = [
            (t("📦 创建实例", "Instances"), 1),
            ("🎁 " + t("整合包", "Modpacks"), 2),
            ("🧩 " + t("Mod", "Mods"), 3),
            ("🌄 " + t("光影包", "Shaders"), 4),
            ("🗂 " + t("数据包", "Datapacks"), 5),
            ("🎨 " + t("资源包", "Resourcepacks"), 6),
        ]
        for text, idx in entries:
            b = QPushButton(text)
            b.setMinimumSize(150, 96)   # 高一点的分类卡片;放不下时自动换行
            b.setStyleSheet(card_btn_style())
            b.clicked.connect(lambda _c, i=idx: self.switch_to(i))
            cards.addWidget(b)
        layout.addLayout(cards)
        layout.addSpacing(18)
        # MC 资源结构科普(「全面」模式显示,「摘要」模式隐藏;见 set_ui_mode)
        self.guide_title = QLabel(
            t("📚 了解 MC 资源结构(自己挑资源前先看一眼):",
              "MC resource types (read before picking):"))
        self.guide_title.setStyleSheet(f"font-weight: bold; color: {text_color()};")
        layout.addWidget(self.guide_title)
        self._guide_labels = []
        for line in _RESOURCE_GUIDE:
            l = QLabel("• " + line)
            l.setWordWrap(True)
            l.setStyleSheet(hint_style())
            layout.addWidget(l)
            self._guide_labels.append(l)
        layout.addStretch()
        return home

    def set_ui_mode(self, mode: str):
        """界面模式(对外叫「全面 / 摘要」,内部 beginner/expert 兼容旧配置):
        全面(beginner)= 显示科普/提示;摘要(expert)= 隐藏科普、精简提示。
        ⚠️ 规范:以后新增界面提示/科普,都要来这里按模式做显隐(见 项目规划.md 界面规范)。
        """
        self._ui_mode = "expert" if str(mode or "") in ("expert", "summary") else "beginner"
        full = self._ui_mode != "expert"
        if hasattr(self, "guide_title"):
            self.guide_title.setVisible(full)
        for l in getattr(self, "_guide_labels", []):
            l.setVisible(full)
        if hasattr(self, "home_hint"):
            self.home_hint.setVisible(full)

    def is_full_mode(self) -> bool:
        """当前是否为「全面」模式(显示科普/详细提示)。"""
        return getattr(self, "_ui_mode", "beginner") != "expert"

    # ---- 对外接口 ----
    def set_hooks(self, instance_dir, on_download, on_start_instance,
                  on_import_modpack=None, on_modpack_download=None):
        """注入:实例目录函数 / 下载回调 / 开始下载实例回调 / 导入整合包回调 / 整合包下载回调"""
        self._instance_dir = instance_dir
        self._on_download_cb = on_download
        self._on_start_cb = on_start_instance
        self._on_import_cb = on_import_modpack
        self._on_modpack_cb = on_modpack_download
        for br in self.browsers.values():
            br.set_instance_dir_fn(instance_dir)
        if self.download_tab is not None and on_import_modpack:
            self.download_tab.bind_import(on_import_modpack)
        if on_modpack_download and "modpack" in self.browsers:
            self.browsers["modpack"].on_modpack_download = on_modpack_download

    def set_latest_versions(self, release: str, snapshot: str):
        self.home_latest.setText(
            t(f"最新正式版: {release} | 最新快照版: {snapshot}",
              f"Latest release: {release} | Latest snapshot: {snapshot}"))

    def refresh_browser_instances(self, instances: list):
        """刷新各资源浏览器里的目标实例卡片(反映全局目标)。"""
        for br in self.browsers.values():
            br.set_instances(instances)

    def _browser_download(self, hit, version, inst, target_dir, sub_dir):
        if self._on_download_cb:
            self._on_download_cb(hit, version, inst, target_dir, sub_dir)

    def _on_modpack_download(self, hit, version):
        """整合包下载:转发给主窗口(下载 .mrpack 并导入成新实例)"""
        if getattr(self, "_on_modpack_cb", None):
            self._on_modpack_cb(hit, version)

    def _on_start_instance(self):
        if hasattr(self, "_on_start_cb") and self._on_start_cb:
            self._on_start_cb()
