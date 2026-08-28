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
import collections

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
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
                      muted_color, panel_style, text_color, set_style,
                      accent_color, warning_color)
from version_tree import GameVersionTree

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
        for item in list(self._items):
            try:
                hint = item.sizeHint()
            except RuntimeError:
                # 底层 C++ QWidgetItem 已被删除(页面切换/隐藏时 Qt 回收),跳过,防崩溃
                try:
                    self._items.remove(item)
                except (ValueError, RuntimeError):
                    pass
                continue
            if x + hint.width() > effective.right() + 1 and line_height > 0:
                x = effective.x()
                y += line_height + self._vspace
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._hspace
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + m.bottom()


class PopupCard(QWidget):
    """无边框 Qt.Popup 浮层:点外面自动关闭,并在关闭时发 closed 信号(供同步标题箭头)。"""
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.closed.emit()


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
        # 懒加载图标:只为"当前可见"的行拉图,按顺序串行,用户没看到的先不拉不存。
        self._icon_loaded = {}          # id(row) -> slug(已请求过图标的行,避免重复拉)
        self._icon_queue = collections.deque()   # 待拉图标的 (list_item, slug, url)
        self._icon_loading = False      # 是否正在串行拉一张(避免并发burst)
        self._icon_visibility_timer = QTimer(self)
        self._icon_visibility_timer.setSingleShot(True)
        self._icon_visibility_timer.timeout.connect(self._enqueue_visible_icons)
        self._icon_visibility_timer.start(120)   # 列表填充/滚动后稍等,等布局稳定再算可见行
        self._icon_placeholder = self._make_placeholder_icon(44)   # 列表项左侧固定占位(图到前先占住)

        self._build_ui()

    @staticmethod
    def _make_placeholder_icon(size: int = 44):
        """预置的占位图标(淡灰圆角方块):列表项左侧固定占位,文本从它右侧开始。
        真图标懒加载后来替换这个占位,文本位置不变(不重排/不跳动)。"""
        try:
            from PySide6.QtGui import QColor, QPainter, QPixmap, QIcon
            pix = QPixmap(size, size)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QColor("#2b2f3a")); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(1, 1, size - 2, size - 2, 8, 8)
            p.end()
            return QIcon(pix)
        except Exception:
            return QIcon()

    def _build_ui(self):
        # ---- 搜索区 ----
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            t(f"搜索{self.label},回车确认(如 sodium / 钠 / 名字)", f"Search {self.label}, press Enter..."))
        self.search_edit.returnPressed.connect(self.do_search)

        self.sort_combo = QComboBox()
        for lbl, val in [("按下载量排序", "downloads"),
                         ("按相关度排序", "relevance"),
                         ("按最近更新", "updated")]:
            self.sort_combo.addItem(t(lbl, lbl), val)

        # 标签(分类)多级菜单:替代以前"手输标签"。点开是一棵分组菜单,可多选。
        self.tag_btn = QToolButton()
        self.tag_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        set_style(self.tag_btn, card_btn_style)
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
        set_style(self.inst_cards_toggle, card_btn_style)
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

        # ---- 筛选(游戏版本 + 加载器)——全局一套,移到底部「版本与下载」展开区;
        #      不再用独立的 filter_version/filter_loader(方案一:与下载参数合一) ----
        # (原 filter_version/filter_loader 移除;全局筛选 = 底部 gv_combo/loader_combo)

        # ---- 结果列表 + 详情面板 ----
        self.result_list = QListWidget()
        self.result_list.setWordWrap(True)
        self.result_list.setIconSize(QSize(44, 44))     # 资源卡片左侧显示 Mod 图标(默认 16px 太小不显眼)
        self.result_list.setSpacing(2)
        self.result_list.setUniformItemSizes(False)
        set_style(self.result_list, list_style)
        self.result_list.currentItemChanged.connect(self._on_selected)
        # 懒加载图标:滚动/改变大小时,只为当前可见的行拉图(并按顺序慢慢存)
        self.result_list.verticalScrollBar().valueChanged.connect(self._on_icon_visibility)
        self.result_list.verticalScrollBar().rangeChanged.connect(self._on_icon_visibility)

        self.panel = QWidget()
        set_style(self.panel, panel_style)
        self.panel.setMinimumWidth(260)
        self.panel.setMaximumWidth(500)
        self.icon_label = None   # 详情面板顶部不再放大图;Mod 图标改在左侧列表卡片显示
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
        self.mcmod_link.setStyleSheet(f"color: {accent_color()}; font-size: 12px;")
        self.mcmod_link.setVisible(False)
        # ---- 全局版本/加载器(方案一:搜索筛选 + 下载默认合一,底部卡显示) ----
        # 游戏版本用版本树(按大版本分组,点大版本自动选推荐版),不再是可编辑下拉。
        self.gv_combo = GameVersionTree()
        self.gv_combo.setToolTip(t("PICK_A_GAME_VERSION_CLICK_A_MAJOR_TO_AUTO_PICK_ITS_RECOMMENDED_EXPAND_FOR_EXACT"))
        self._gv_none_label = t("ANY_VERSION")
        self.loader_combo = QComboBox()
        self.loader_combo.setObjectName("filter_loader")
        self.loader_combo.addItem(t("ANY_LOADER"), None)
        for label, value in [("Fabric", "fabric"), ("Forge", "forge"),
                             ("NeoForge", "neoforge"), ("Quilt", "quilt")]:
            self.loader_combo.addItem(label, value)
        self.ver_combo = QComboBox()
        self.dl_btn = QPushButton(t("DOWNLOAD"))
        set_style(self.dl_btn, launch_btn_style)
        self.dl_btn.clicked.connect(self._download)
        self.gv_combo.version_changed.connect(self._refresh_versions_global)
        self.loader_combo.currentIndexChanged.connect(self._refresh_versions_global)

        # 版本/加载器/mod版本 + 下载,改放【底部向上展开的折叠条】(bottom_bar),不占右侧窄条。
        # 右侧 panel 只留描述/作者/百科链接 → Mod 列表更宽、能多展示。
        # 注: self.gv_combo 等属性名保留(现有 _download/_refresh_versions/_load_project 引用不变),
        #     只改放到哪。

        p = QVBoxLayout(self.panel)
        p.setContentsMargins(14, 14, 14, 14)
        p.setSpacing(8)
        p.addWidget(self.title_label)
        p.addWidget(self.meta_label)
        p.addWidget(self.desc_label)
        p.addWidget(self.desc_note_label)
        p.addWidget(self.mcmod_link)
        self.empty_label = QLabel(t("SELECT_A_PROJECT_ON_THE_LEFT"))
        self.empty_label.setStyleSheet(hint_style())
        self.empty_label.setWordWrap(True)
        p.addWidget(self.empty_label)
        p.addStretch()
        for w in (self.title_label, self.meta_label, self.desc_label):
            w.setVisible(False)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(self.result_list)
        panel_scroll = QScrollArea()
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setWidget(self.panel)
        self.split.addWidget(panel_scroll)
        self.split.setChildrenCollapsible(False)
        self.split.setSizes([440, 280])   # 列表更宽,右窄条更窄

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        if self.is_modpack:
            # 整合包=一键全集:下载后作为「新实例」导入,无需选目标实例/目录
            self.modpack_hint = QLabel(
                t("MODPACK_MODS_CONFIG_OPTIONAL_SAVES_IN_ONE_PICK_A_VERSION_AND_DOWNLOAD_IT_AUTO_DOWNLOADS_THE_MRPACK_AND_IMPORTS_AS_A_NEW_INSTANCE"))
            self.modpack_hint.setStyleSheet(hint_style())
            self.modpack_hint.setWordWrap(True)
            layout.addWidget(self.modpack_hint)
            # 目标实例卡放到底部;整合包不需要,进 _build_bottom_bar 里隐藏
        # 顶部统一操作行:搜索(占1) + 排序 + 标签
        top_row = QHBoxLayout()
        top_row.addWidget(self.search_edit, 1)
        top_row.addWidget(self.sort_combo)
        top_row.addWidget(self.tag_btn)
        layout.addLayout(top_row)
        layout.addWidget(self.split, 1)

        # ---- 底部向上展开的折叠条:版本 + 目标实例 + 下载(最后一步设参数→下载) ----
        self._build_bottom_bar()
        layout.addWidget(self.bottom_bar)

        # 切换排序时,若处于默认浏览(空关键词)则重新拉取
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)

    def _build_bottom_bar(self):
        """底部三张并排卡片(独占一行,不等宽,默认各自收起、点开各自展开):
           [手动下载] [目标实例] [下载]
         手动下载 = 游戏版本/加载器/mod版本(精确指定);目标实例 = 装到哪个实例/目录;
         下载 = 一键下载按钮。三者互不干扰,符合同一条「先挑内容、最后一步下单」的直觉。"""
        self.bottom_bar = QWidget()
        self.bottom_bar.setStyleSheet("QWidget { background: transparent; }")
        row = QHBoxLayout(self.bottom_bar)
        row.setContentsMargins(8, 0, 8, 6)
        row.setSpacing(6)

        # ---- 底部三按钮:窄 / 宽 / 窄(手动下载=窄,目标实例=宽,下载=窄) ----
        # 手动下载 / 目标实例 点开都是【悬浮层】,不把底部栏撑大;下载是按钮。

        # 手动下载按钮(窄)
        self.manual_toggle = QPushButton("▸ " + t("MANUAL_DOWNLOAD"))
        self.manual_toggle.setCheckable(True)
        self.manual_toggle.setToolTip(t("SET_GAME_LOADER_MOD_VERSION"))
        set_style(self.manual_toggle, card_btn_style)
        self.manual_toggle.clicked.connect(self._toggle_manual_popup)
        row.addWidget(self.manual_toggle, 2)

        # 手动下载悬浮层(装 游戏版本树 + 加载器 + mod版本)
        self.manual_popup = PopupCard(self)
        self.manual_popup.setObjectName("manual_popup")
        set_style(self.manual_popup, panel_style)
        mp = QVBoxLayout(self.manual_popup)
        mp.setContentsMargins(10, 8, 10, 8)
        mp.setSpacing(6)
        mp.addWidget(QLabel(t("GAME_VERSION_CLICK_A_MAJOR_TO_AUTO_PICK")))
        self.gv_combo.setMaximumHeight(180)
        self.gv_combo.setMinimumHeight(110)
        mp.addWidget(self.gv_combo)
        for lbl, combo in [(t("LOADER"), self.loader_combo),
                           (t("MOD_VERSION"), self.ver_combo)]:
            r = QHBoxLayout()
            r.addWidget(QLabel(lbl))
            r.addWidget(combo, 1)
            mp.addLayout(r)
        self.manual_popup.setFixedWidth(340)
        self.manual_popup.hide()
        self.manual_popup.closed.connect(self._on_manual_popup_closed)

        # 目标实例按钮(宽)
        self.inst_cards_toggle.setCheckable(True)
        self.inst_cards_toggle.clicked.disconnect()
        self.inst_cards_toggle.clicked.connect(self._toggle_cards)
        set_style(self.inst_cards_toggle, card_btn_style)
        row.addWidget(self.inst_cards_toggle, 4)

        # 目标实例悬浮层(装 实例卡片 + 自定义目录提示)
        self.inst_popup = PopupCard(self)
        self.inst_popup.setObjectName("inst_popup")
        set_style(self.inst_popup, panel_style)
        pp = QVBoxLayout(self.inst_popup)
        pp.setContentsMargins(10, 8, 10, 8)
        pp.setSpacing(4)
        pp.addWidget(self.cards_scroll)
        pp.addWidget(self.custom_label)
        self.inst_popup.setFixedWidth(320)
        self.inst_popup.hide()
        self.inst_popup.closed.connect(self._on_popup_closed_autoclose)

        # 下载按钮(窄)
        dl_card = QWidget()
        set_style(dl_card, card_btn_style)
        db = QVBoxLayout(dl_card)
        db.setContentsMargins(8, 8, 8, 8)
        db.addWidget(self.dl_btn)
        self.dl_card = dl_card
        row.addWidget(dl_card, 2)

        # 整合包:不需要选目标实例,把目标实例按钮隐藏(手动下载+下载保留)
        if self.is_modpack:
            self.inst_cards_toggle.setVisible(False)

        # 目标实例卡标题文本先同步成当前全局目标(之前靠顶部显示,现在卡内)
        self._sync_target_ui()

    def _toggle_cards(self):
        """点目标实例按钮:弹出/收起悬浮层(叠加在资源页上方,不把底部栏撑大)。"""
        show = self.inst_cards_toggle.isChecked()
        if show:
            # 让滚动区先按内容算出高度(widgetResizable),再据此给浮窗定型
            self.cards_scroll.setVisible(True)
            self.cards_scroll.updateGeometry()
            self.inst_popup.layout().activate()
            hint = self.inst_popup.layout().sizeHint()
            self.inst_popup.resize(max(320, hint.width()), max(60, hint.height()))
            self._popup_above(self.inst_popup, self.inst_cards_toggle)
            self.inst_popup.show()
            self.inst_popup.raise_()
            self.inst_cards_toggle.setText(
                "▾ " + self.inst_cards_toggle.text()[2:])
        else:
            self._close_inst_popup()

    def _toggle_manual_popup(self):
        """点手动下载按钮:弹出/收起悬浮层(游戏版本树 + 加载器 + mod版本)。"""
        show = self.manual_toggle.isChecked()
        if show:
            self.manual_popup.layout().activate()
            hint = self.manual_popup.layout().sizeHint()
            self.manual_popup.resize(max(340, hint.width()), max(160, hint.height()))
            self._popup_above(self.manual_popup, self.manual_toggle)
            self.manual_popup.show()
            self.manual_popup.raise_()
            self.manual_toggle.setText(
                "▾ " + self.manual_toggle.text()[2:])
        else:
            self._close_manual_popup()

    def _popup_above(self, popup, anchor):
        """把浮窗放在 anchor(按钮)正上方,并夹在窗口水平范围内。"""
        g = anchor.mapToGlobal(anchor.rect().topLeft())
        top = self.window().mapToGlobal(self.window().rect().topLeft())
        x = max(top.x(), min(g.x(), top.x() + self.window().width() - popup.width()))
        y = g.y() - popup.height()
        popup.move(x, y)

    def _close_manual_popup(self):
        """收起手动下载悬浮层并复位箭头。"""
        self.manual_popup.hide()
        self.manual_toggle.setChecked(False)
        self.manual_toggle.setText(
            "▸ " + self.manual_toggle.text()[2:])

    def _on_manual_popup_closed(self):
        if not self.manual_popup.isVisible() and self.manual_toggle.isChecked():
            self.manual_toggle.setChecked(False)
            self.manual_toggle.setText(
                "▸ " + self.manual_toggle.text()[2:])

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
            self.tag_btn.setText(t("NO_TAGS"))
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
        clr = self.tag_menu.addAction(t("CLEAR_ALL_TAGS"))
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

    def populate_game_versions(self, manifest: dict):
        """用版本清单填充游戏版本树(按大版本分组)。"""
        try:
            self.gv_combo.populate(manifest, self._gv_none_label)
        except Exception:
            pass   # 清单异常时版本树留空(默认「无(全部版本)」项由 populate 内部自建)

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
            set_style(card, card_btn_style)
            card.clicked.connect(lambda _c, i=inst: self._select_inst(i))
            self.instance_cards_layout.addWidget(card)
            self._inst_cards.append((inst, card))
        none_card = QPushButton(t("NONE_PICK_FOLDER"))
        none_card.setCheckable(True)
        none_card.setMinimumHeight(40)
        set_style(none_card, card_btn_style)
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
            self.custom_label.setText(f"{t("INSTALL_TO")}: {dir_}")
            self.custom_label.setVisible(True)
        else:
            self.inst_cards_toggle.setText("▸ 目标实例: 未选择")
            self._apply_inst_cards(None)

    def _select_inst(self, inst):
        """选中某实例:更新本地卡片+筛选,并广播到全局(其他分类页一并生效)。"""
        self._apply_inst_cards(inst["id"])
        # 选中后收起悬浮层,标题箭头复位
        self._close_inst_popup()
        # 全局筛选同步到该实例的基础版本 + 加载器(方案一:选中实例 → 底部 gv/loader 跟随)
        self.gv_combo.select_version(inst["base"])
        li = self.loader_combo.findData(inst["loader"])
        if li >= 0:
            self.loader_combo.setCurrentIndex(li)
        self._target_setter(inst, None)

    def _select_none(self):
        """选"无":改用自定义目录(或稍后手动选位置),并广播全局。"""
        self._close_inst_popup()
        self._target_setter(None, None)

    def _close_inst_popup(self):
        """收起目标实例悬浮层并复位标题箭头。"""
        self.inst_popup.hide()
        self.inst_cards_toggle.setChecked(False)
        self.inst_cards_toggle.setText(
            "▸ " + self.inst_cards_toggle.text()[2:])

    def _on_popup_closed_autoclose(self):
        """浮窗被点外面/其他途径关闭时,把标题箭头复位成收起态。"""
        if not self.inst_popup.isVisible() and self.inst_cards_toggle.isChecked():
            self.inst_cards_toggle.setChecked(False)
            self.inst_cards_toggle.setText(
                "▸ " + self.inst_cards_toggle.text()[2:])

    def pick_custom_dir(self, game_dir: str):
        """用户用文件管理器选安装位置(装到其他启动器的目录)。"""
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, t("PICK_FOLDER"), game_dir)
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
    def _current_gv(self):
        """返回当前全局游戏版本值;「无(全部版本)」或空 → None(不按版本过滤)。"""
        v = self.gv_combo.current_version() or ""
        if v == self._gv_none_label or v == "":
            return None
        return v

    def do_search(self):
        query = self.search_edit.text().strip()
        # 允许空关键词:打开资源页即「默认浏览」(空 query → 按 sort_combo 排序,默认 downloads)。
        # 全局版本/加载器筛选(底部 gv_combo/loader_combo)会被尊重(为空则全量)。
        gv = self._current_gv()                       # 「无(全部版本)」→ None
        loader = self.loader_combo.currentData() or None   # 「无(全部加载器)」→ None
        order = self.sort_combo.currentData() or "downloads"
        tags = ",".join(sorted(self._selected_tags))
        self._last_query = query
        self.result_list.clear()
        QListWidgetItem(t("SEARCHING"), self.result_list)

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

    def _refresh_versions_global(self):
        """全局版本/加载器筛选变化 → 重新搜索(列表按新筛选刷新)。
        方案一:gv/loader 是全局筛选(也是下载默认),变化即刷新列表。"""
        if self.search_edit.text().strip():
            return
        self.do_search()

    def _fill_results(self, hits):
        self.result_list.clear()
        if hits is None:
            self._auto_loaded = False
            QListWidgetItem(t("SEARCH_FAILED_CHECK_NETWORK"), self.result_list)
            return
        for h in hits:
            author = h.get("author", "")
            dl = f"⬇{h.get('downloads', 0):,}" if h.get("downloads") else ""
            meta = "  ".join(x for x in (author, dl) if x)
            text = f"{h['title']}\n{h.get('description', '')[:60]}" + (f"\n{meta}" if meta else "")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, h)
            # 左侧先占一个固定大小的框:文本从它右侧开始,真图标到了才替换(不重排)
            item.setIcon(self._icon_placeholder)
            self.result_list.addItem(item)
        if not hits and not self.result_list.count():
            QListWidgetItem(t("NO_RESULTS"), self.result_list)
        # 记录默认浏览是否已加载(空关键词的结果),供 maybe_auto_load 判断是否重复拉取
        self._auto_loaded = (getattr(self, "_last_query", "") == "")
        # 只给当前可见的条目按顺序懒加载图标(用户没看到的先不拉不存)
        self._icon_visibility_timer.start(80)

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
        for w in (self.title_label, self.meta_label,
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
                    t("VIEW_ON_MC_MOD")))
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
        # 异步加载项目详情,刷新【mod 可用版本】下拉(方案一:gv/loader 是全局筛选不清,
        # 只清并重填 ver_combo —— 它才是逐 Mod 的)
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
        self.desc_note_label.setText(t("TRANSLATING"))
        self.desc_note_label.setStyleSheet(f"color: {muted_color()}; font-size: 11px;")
        self.desc_note_label.setVisible(True)

        # 先查描述缓存(按 slug 键,跨版本复用;命中直接显示,不再推理)
        import image_cache
        cached = image_cache.get_cached_desc(requested_slug)
        if cached:
            cur0 = getattr(self, "_current", None)
            if cur0 and cur0.get("slug") == requested_slug:
                self.desc_label.setText(cached)
                self.desc_note_label.setText(t("CACHED_TRANSLATION"))
                self.desc_note_label.setStyleSheet(f"color: {muted_color()}; font-size: 11px;")
                self.desc_note_label.setVisible(True)
            return

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
        cur = getattr(self, "_current", None)
        slug = (cur or {}).get("slug", "") if cur else ""
        # 成功拿到文本(机翻或译文)→ 写回描述缓存(按 slug 键,跨版本复用)
        if source in ("translated", "already_cn", "original") and text and slug:
            try:
                import image_cache
                image_cache.set_cached_desc(slug, text)
            except Exception:
                pass
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
            self.desc_note_label.setText(t("TRANSLATION_FAILED_SHOWING_ORIGINAL"))
            self.desc_note_label.setStyleSheet(f"color: {warning_color()}; font-size: 11px;")
            self.desc_note_label.setVisible(True)
            return
        if result.get("machine"):
            self.desc_label.setText(text)
            note = t("MACHINE_TRANSLATION_SEE_ORIGINAL_FOR_ACCURACY")
            if result.get("confidence") == "low":
                note = t("MACHINE_TRANSLATION_LOW_CONFIDENCE_SEE_ORIGINAL")
            self.desc_note_label.setText(note)
            self.desc_note_label.setStyleSheet(f"color: {warning_color()}; font-size: 11px;")
            self.desc_note_label.setVisible(True)
            return
        # 兜底:显示原文
        self.desc_label.setText(text)
        self.desc_note_label.setVisible(False)

    # ---- 懒加载图标:只为"当前可见"的行按顺序拉,不并发burst、不后台埋大量下载 ----
    def _on_icon_visibility(self, *_):
        """滚动/范围改变/列表变化 → 稍等布局稳定后重新计算可见行入队。"""
        if self._icon_visibility_timer.isActive():
            self._icon_visibility_timer.stop()
        self._icon_visibility_timer.start(120)

    def _visible_rows(self) -> list:
        """返回当前视口内可见的行索引(用 visualItemRect 与 viewport 相交判断)。"""
        view = self.result_list.viewport()
        vrect = view.rect()
        rows = []
        n = self.result_list.count()
        if n == 0:
            return rows
        for i in range(n):
            item = self.result_list.item(i)
            try:
                rect = self.result_list.visualItemRect(item)
            except Exception:
                continue
            if rect.isValid() and rect.intersects(vrect):
                rows.append(i)
        return rows

    def _enqueue_visible_icons(self):
        """把当前可见、且还没请求过图标的行压入队列。队列按行序(从上到下),串行消费。"""
        try:
            for i in self._visible_rows():
                item = self.result_list.item(i)
                if item is None:
                    continue
                if i in self._icon_loaded:
                    continue
                h = item.data(Qt.ItemDataRole.UserRole) or {}
                slug = h.get("slug", "")
                icon_url = h.get("icon_url", "")
                if not slug or not icon_url:
                    self._icon_loaded[i] = True   # 无图/无url:标"处理过",不再反复看
                    continue
                if any(q[1] == slug for q in self._icon_queue):   # 已在队列(同slug复用)
                    continue
                self._icon_loaded[i] = True
                self._icon_queue.append((item, slug, icon_url))
            self._pump_icon_queue()
        except Exception:
            pass

    def _pump_icon_queue(self):
        """串行消费图标队列:一次只拉一张,拉完再拉下一张(避免并发burst)。
        结果经由 _async_q 排回主线程(与网络请求同一条可靠通道),避免跨线程 QTimer 丢失。"""
        if self._icon_loading:
            return
        if not self._icon_queue:
            return
        item, slug, url = self._icon_queue.popleft()
        self._icon_loading = True

        def worker():
            try:
                import image_cache
                from PySide6.QtGui import QPixmap, QIcon
                data = image_cache.load_icon(slug, url, size=48)
                icon = None
                if data:
                    pix = QPixmap()
                    if pix.loadFromData(data):
                        icon = QIcon(pix.scaled(
                            48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation))
                # 排回主线程(_async_timer._drain_async 会调 self._end_icon)
                self._async_q.put(("__icon__", (item, icon), self._end_icon, False))
            except Exception:
                self._async_q.put(("__icon__", (item, None), self._end_icon, False))

        threading.Thread(target=worker, daemon=True).start()

    def _end_icon(self, payload):
        """主线程:给条目设图标(成功才设),然后继续拉下一张。"""
        item, icon = payload if isinstance(payload, tuple) else (None, None)
        if icon is not None and item is not None:
            try:
                if item.listWidget() is not None:   # 条目可能已被清空/重建
                    item.setIcon(icon)
            except Exception:
                pass
        self._icon_loading = False
        self._pump_icon_queue()

    def _load_project(self, h):
        """异步拉项目详情,填充 游戏版本/加载器 两个下拉。"""
        def fetch():
            import modrinth
            return modrinth.get_project(h["slug"])
        self._async(("proj", h["slug"]), fetch, self._populate_project)

    def _populate_project(self, proj):
        if not proj:
            return
        # 方案一:gv_combo/loader_combo 是【全局】版本/加载器筛选(用户选,不随选中项变),
        # 不在这里重填。只刷新选中 Mod 的【可用 mod 版本】列表(_refresh_versions)。
        self._refresh_versions()

    def _refresh_versions(self):
        if not getattr(self, "_current", None):
            return
        slug = self._current["slug"]
        # 方案一:gv 是全局筛选(可为"无(全部版本)"→ None);loader 类似。
        # gv/loader 为空 → 该 Mod 的"可用版本"就全列(不按版本过滤)。
        gv = self._current_gv()                     # 「无(全部版本)」→ None
        loader = self.loader_combo.currentData() or None
        self.ver_combo.clear()
        self.ver_combo.addItem(t("LOADING"), None)
        self.ver_combo.setEnabled(False)

        def fetch():
            import modrinth
            # gv 为空 → 不按版本过滤,列该 mod 全部可用版本
            return modrinth.list_mod_versions(slug, gv or None, loader)
        self._async(("ver", slug, gv, loader), fetch, self._fill_versions)

    def _fill_versions(self, versions):
        self.ver_combo.clear()
        if not versions:
            self.ver_combo.addItem(t("NO_VERSIONS"), None)
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

        # ---- 左侧菜单(独立模块 LeftMenu,无折叠) ----
        # 图标用内置单色 SVG + 主题色(theme_icon),跟随深浅色/自定义主题;不再是 emoji。
        from left_menu import LeftMenu
        self.menu = LeftMenu(width=150)
        for label, icon in [
                (t("HOME"), "home"),
                (t("INSTANCES"), "instances"),
                (t("MODPACKS"), "modpack"),
                (t("MODS"), "mod"),
                (t("SHADERS"), "shader"),
                (t("DATAPACKS"), "datapack"),
                (t("RESOURCEPACKS"), "resourcepack"),
                (t("FAVORITES"), "favorite"),
                (t("LAUNCHER_PLUGINS"), "utility")]:
            self.menu.add_item(label, icon)
        self.menu.itemClicked.connect(self.switch_to)

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
        mp = ResourceBrowser("modpack", t("MODPACKS"), "",
                             on_download=self._browser_download,
                             get_instance_loader=self._get_inst_loader,
                             is_modpack=True)
        mp.on_modpack_download = self._on_modpack_download
        mp.set_instance_dir_fn(self._instance_dir)
        mp._set_target_hooks(self._get_shared_target, self._set_shared_target)
        mp.setObjectName("browser_modpack")
        self.browsers["modpack"] = mp
        self.stack.addWidget(mp)                            # 2 整合包

        # 资源浏览器:Mod / 光影 / 数据包 / 资源包
        for idx, (ptype, label, sub) in enumerate(RESOURCE_CATEGORIES, start=3):
            br = ResourceBrowser(ptype, label, sub,
                                 on_download=self._browser_download,
                                 get_instance_loader=self._get_inst_loader)
            br.set_instance_dir_fn(self._instance_dir)
            br._set_target_hooks(self._get_shared_target, self._set_shared_target)
            br.setObjectName(f"browser_{ptype}")
            self.browsers[ptype] = br
            self.stack.addWidget(br)                        # 3..6

        # 收藏夹:占位(收藏/批量下载/AI平替逻辑下一步做,先给入口)
        self.stack.addWidget(self._build_favorites_placeholder())   # 7

        # 启动器插件:占位页(插件生态建设中,先给入口)
        self.stack.addWidget(self._build_plugins_placeholder())   # 8

        # ---- 布局 ----
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.menu)
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
    def switch_to(self, idx: int):
        self.stack.setCurrentIndex(idx)
        # 切到资源浏览器页且搜索框为空 → 自动默认浏览(打开即显示列表,无需先搜索)
        cur = self.stack.currentWidget()
        if isinstance(cur, ResourceBrowser):
            cur.maybe_auto_load()
        self.menu.select(idx)

    # ---- 首页 ----
    def _build_home(self):
        home = QWidget()
        layout = QVBoxLayout(home)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        self.home_latest = QLabel(t("LATEST_RELEASE_LATEST_SNAPSHOT"))
        self.home_latest.setStyleSheet(f"font-weight: bold; font-size: 15px; color: {text_color()};")
        self.home_hint = QLabel(
            t("TIP_THE_NEWEST_MC_VERSION_USUALLY_HAS_POOR_MOD_SUPPORT_PREFER_ACTIVE_VERSIONS_LIKE_1_21_1_1_20_1"))
        self.home_hint.setWordWrap(True)
        self.home_hint.setStyleSheet(hint_style())
        layout.addWidget(self.home_latest)
        layout.addWidget(self.home_hint)
        layout.addSpacing(14)
        layout.addWidget(QLabel(t("BROWSE_RESOURCES")))
        cards = FlowLayout(hspacing=12, vspacing=12)
        entries = [
            (t("CREATE_INSTANCE"), 1),
            ("🎁 " + t("MODPACKS"), 2),
            ("🧩 " + t("MODS"), 3),
            ("🌄 " + t("SHADERS"), 4),
            ("🗂 " + t("DATAPACKS"), 5),
            ("🎨 " + t("RESOURCEPACKS"), 6),
            ("🧩 " + t("LAUNCHER_PLUGINS"), 7),
        ]
        for text, idx in entries:
            b = QPushButton(text)
            b.setMinimumSize(150, 96)   # 高一点的分类卡片;放不下时自动换行
            set_style(b, card_btn_style)
            b.clicked.connect(lambda _c, i=idx: self.switch_to(i))
            cards.addWidget(b)
        layout.addLayout(cards)
        layout.addSpacing(18)
        # MC 资源结构科普(「全面」模式显示,「摘要」模式隐藏;见 set_ui_mode)
        self.guide_title = QLabel(
            t("MC_RESOURCE_TYPES_READ_BEFORE_PICKING"))
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

    def _build_favorites_placeholder(self) -> QWidget:
        """收藏夹(占位):后续实现「收藏/批量下载/版本检查/AI 找平替」。先给入口 + 说明。"""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(8)
        title = QLabel("⭐ 收藏夹")
        title.setStyleSheet(f"font-weight: bold; font-size: 16px; color: {text_color()};")
        outer.addWidget(title)
        note = QLabel("这里汇聚你在各资源页收藏的 Mod(可收藏指定版本)。\n"
                      "后续支持:批量下载到目标实例、不兼容提示、用 AI 找功能类似的平替。\n\n"
                      "(当前为占位页,收藏/下载功能开发中。)")
        note.setWordWrap(True)
        note.setStyleSheet(hint_style())
        outer.addWidget(note)
        outer.addStretch()
        return page

    def _build_plugins_placeholder(self) -> QWidget:
        """启动器插件商店:手动注册仓库源 → 列出仓库里的插件 → 一键安装单文件。
        参考 DSH「仓库即商店」:你的官方插件放你项目仓库(如 GitHub),用户添加该仓库 URL 即可装。"""
        import plugin_manager
        page = QWidget()
        page.setObjectName("plugins_page")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(8)

        title = QLabel("🧩 启动器插件商店")
        title.setStyleSheet(f"font-weight: bold; font-size: 16px; color: {text_color()};")
        outer.addWidget(title)
        note = QLabel("插件仓库 = 一个 plugins.json 清单(列出 名/版本/下载地址)。\n"
                      "手动添加你的「官方」仓库(或任何第三方仓库)URL,即可浏览并一键安装;"
                      "装的插件可到 设置→插件 启停。")
        note.setWordWrap(True); note.setStyleSheet(hint_style())
        outer.addWidget(note)

        # ---- 仓库源管理 ----
        reg_title = QLabel("仓库源:")
        reg_title.setStyleSheet(f"font-weight: bold; color: {muted_color()};")
        outer.addWidget(reg_title)
        self._registry_list = QListWidget(); self._registry_list.setMaximumHeight(80)
        outer.addWidget(self._registry_list)
        reg_row = QHBoxLayout()
        self._registry_edit = QLineEdit()
        self._registry_edit.setPlaceholderText("仓库 plugins.json 地址,如 https://raw.githubusercontent.com/…/plugins.json")
        reg_row.addWidget(self._registry_edit, 1)
        add_reg = QPushButton("添加仓库"); set_style(add_reg, card_btn_style); add_reg.setMinimumHeight(30)
        add_reg.clicked.connect(self._add_registry)
        del_reg = QPushButton("删除选中"); set_style(del_reg, card_btn_style); del_reg.setMinimumHeight(30)
        del_reg.clicked.connect(self._del_registry)
        reg_row.addWidget(add_reg); reg_row.addWidget(del_reg)
        outer.addLayout(reg_row)

        # ---- 仓库里的插件(汇总) ----
        remote_title = QLabel("仓库里的插件:")
        remote_title.setStyleSheet(f"font-weight: bold; color: {muted_color()};")
        outer.addWidget(remote_title)
        self._plugin_store_list = QListWidget()
        self._plugin_store_list.setWordWrap(True)
        set_style(self._plugin_store_list, list_style)
        outer.addWidget(self._plugin_store_list, 1)
        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("刷新插件列表"); set_style(refresh_btn, card_btn_style); refresh_btn.setMinimumHeight(32)
        refresh_btn.clicked.connect(self._refresh_store)
        install_btn = QPushButton("安装选中插件"); set_style(install_btn, card_btn_style); install_btn.setMinimumHeight(32)
        install_btn.clicked.connect(self._install_store_plugin)
        btn_row.addWidget(refresh_btn); btn_row.addWidget(install_btn)
        outer.addLayout(btn_row)

        open_btn = QPushButton(t("OPEN_PLUGIN_MANAGER"))
        set_style(open_btn, card_btn_style); open_btn.setMinimumHeight(34)
        open_btn.clicked.connect(self._open_plugin_settings)
        outer.addWidget(open_btn)
        self._refresh_store()
        return page

    def _registries(self) -> list:
        """读当前插件仓库源设置。"""
        from settings import load_settings
        s = load_settings()
        return s.get("plugin_registries", []) or []

    def _save_registries(self, regs: list):
        from settings import load_settings, save_settings
        s = load_settings()
        s["plugin_registries"] = regs
        save_settings(s)

    def _add_registry(self):
        u = self._registry_edit.text().strip()
        if not u:
            return
        regs = list(self._registries())
        if any(r.get("url") == u for r in regs):
            self._registry_edit.setText("")
            return
        regs.append({"url": u, "name": u.split("/")[-1] or u})
        self._save_registries(regs)
        self._registry_edit.setText("")
        self._refresh_store()

    def _del_registry(self):
        cur = self._registry_list.currentRow()
        regs = list(self._registries())
        if 0 <= cur < len(regs):
            regs.pop(cur)
            self._save_registries(regs)
            self._refresh_store()

    def _refresh_store(self):
        import plugin_manager
        regs = self._registries()
        self._registry_list.clear()
        for r in regs:
            self._registry_list.addItem(r.get("url", ""))
        # 拉取汇总
        merged = plugin_manager.list_remote_plugins(regs) if regs else {}
        self._plugin_store_list.clear()
        if not regs:
            self._plugin_store_list.addItem("还没有仓库源,请先在上面添加一个仓库 URL。")
            return
        for name, e in sorted(merged.items()):
            title = e.get("title") or name
            ver = e.get("version") or ""
            desc = (e.get("description") or "")[:60]
            repo = (e.get("repo") or "").split("/")[-1]
            item = QListWidgetItem(f"{title}  <small>({ver})</small>   [{repo}]\n{desc}")
            item.setData(Qt.ItemDataRole.UserRole, e)
            self._plugin_store_list.addItem(item)
        if not merged:
            self._plugin_store_list.addItem("(仓库里没有可安装的插件,或拉取失败)")

    def _install_store_plugin(self):
        """安装选中的仓库插件(单文件下载+落盘)。"""
        import plugin_manager
        cur = self._plugin_store_list.currentItem()
        if cur is None:
            return
        entry = cur.data(Qt.ItemDataRole.UserRole) or {}
        r = plugin_manager.install_remote_plugin(entry)
        if r.get("ok"):
            QMessageBox.information(self, "安装插件",
                                    f"✅ 已安装插件 {r.get('name', '')}:{r.get('path', '')}\n【重启启动器】后生效,可到 设置→插件 启用。")
        else:
            QMessageBox.warning(self, "安装插件", f"❌ 安装失败:{r.get('error', '未知')}")

    def _open_plugin_settings(self):
        """打开 设置(切到插件页)。"""
        try:
            win = self.window()
            if win is not None and hasattr(win, "settings_center"):
                win.settings_center.shell.switch_by_label(t("PLUGINS"))
        except Exception:
            pass

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
