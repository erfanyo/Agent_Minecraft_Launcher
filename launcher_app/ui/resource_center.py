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
from __future__ import annotations
from launcher_app.ui.ui_notifications import task_notice, task_warning, inline_notice, inline_warning, action_question
from launcher_app.ui.task_center import task_question
import os
import time
import urllib.parse
import collections

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QListView,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from launcher_app.core.i18n import t
from launcher_app.core.background_tasks import BackgroundTask
from launcher_app.ui.ui_style import (card_btn_style, hint_style, list_style,
                      muted_color, panel_style, popup_menu_style, popup_panel_style, text_color, set_style,
                      accent_color, warning_color, current_color, resource_control_style)


class _ResourceSourceDelegate(QStyledItemDelegate):
    """在资源列表右下角绘制低强调度的平台标识。"""
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        hit = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(hit, dict):
            return
        source = hit.get("source", "modrinth")
        label = "CurseForge" if source == "curseforge" else "Modrinth"
        # 颜色每次绘制时从主题槽读取：跟随系统深浅色和用户自定义主题。
        color = QColor(warning_color() if source == "curseforge" else accent_color())
        color.setAlpha(135)
        painter.save()
        font = painter.font()
        font.setPointSizeF(max(8.0, font.pointSizeF() - 1.5))
        painter.setFont(font)
        painter.setPen(color)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(label)
        rect = option.rect
        painter.drawText(rect.right() - width - 8, rect.bottom() - 6, label)
        painter.restore()

# 资源分类(左侧菜单 + Modrinth project_type + 安装目录子文件夹)
RESOURCE_CATEGORIES = [
    ("mod", "🧩 Mod", "mods"),
    ("shader", "🌄 光影包", "shaderpacks"),
    ("datapack", "🗂 数据包", "datapacks"),
    ("resourcepack", "🎨 资源包", "resourcepacks"),
]
FLEXIBLE_VERSION_TYPES = frozenset(('shader', 'datapack', 'resourcepack'))

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

# 首页分类卡片的短描述(每类一句话;原来 7 行长科普已移除,详情见各分类页)
_CATEGORY_DESC = {
    "instances": "新建 / 导入游戏实例",
    "modpack": "Mod + 配置的一键成品合集",
    "mod": "改玩法 / 加功能,需加载器",
    "shader": "只改画面渲染(光线/水面)",
    "datapack": "配方 / 生成,原版支持",
    "resourcepack": "纹理 / 音效 / 界面外观",
    "utility": "额外启动器功能",
}


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
    """无边框 Qt.Popup 浮层:点外面自动关闭,并在关闭时发 closed 信号(供同步标题箭头)。
    支持画共享壁纸(与主窗统一,壁纸透出);无壁纸时按当前主题画背景。"""
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._shared = None
        self._vx = self._vy = 0
        self._mask = 0.6

    def set_shared_view(self, scaled, vx, vy, mask=0.6):
        """壁纸模式下画主窗共享壁纸片段(相对位置)。scaled=None 则回退主题背景。"""
        self._shared = scaled
        self._vx = int(vx); self._vy = int(vy)
        self._mask = max(0.0, min(1.0, mask))
        self.update()

    def paintEvent(self, e):
        if self._shared is not None:
            from PySide6.QtGui import QPainter
            from launcher_app.ui.ui_background import mask_color
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(-self._vx, -self._vy, self._shared)
            if self._mask > 0:
                c = mask_color(); c.setAlphaF(self._mask)
                p.fillRect(self.rect(), c)
            p.end()
        else:
            super().paintEvent(e)   # 无壁纸:面板/牌桌底色照常

    def hideEvent(self, event):
        super().hideEvent(event)
        self.closed.emit()


class GameVersionFilter(QComboBox):
    """Only actual declared game versions; no recommended-version inference."""
    version_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('filter_version')
        self.addItem(t('任意', 'Any'), '')
        self.currentIndexChanged.connect(lambda: self.version_changed.emit(self.current_version()))

    def populate(self, manifest, none_label=''):
        previous = self.current_version()
        blocked = self.blockSignals(True)
        try:
            self.clear()
            self.addItem(t('任意', 'Any'), '')
            for version in manifest.get('versions', []):
                if version.get('type') == 'release':
                    self.addItem(version['id'], version['id'])
            self.select_version(previous)
        finally:
            self.blockSignals(blocked)

    def current_version(self):
        return self.currentData() or ''

    def select_version(self, version):
        self.setCurrentIndex(max(0, self.findData(version or '')))


class ResourceBrowser(QWidget):
    """资源浏览器(Mod / 光影包 / 数据包 / 资源包共用):
    目标实例(可折叠,全局共享) + 筛选 + 搜索(异步) + 结果列表 + 详情面板(版本/加载器/下载)。"""

    favorite_changed = Signal()

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

        # 后台任务(网络请求不卡 UI)，带缓存与同请求合并
        self._async_cache = {}
        self._async_tasks = set()
        self._async_inflight = {}  # cache_key -> 等待同一结果的回调，避免连续点击重复请求

        # 是否已加载过「默认浏览」(打开页即显示列表);已加载则不重复拉取
        self._auto_loaded = False
        # 分页(滚动到底加载更多)
        self._offset = 0            # 已加载结果数(游标)
        self._no_more = False       # 是否已没有更多
        self._more_loading = False  # 是否正在加载更多(防重入)
        self._search_params = None  # (source, query, order, tags, game_version, loader)
        self._search_generation = 0 # 丢弃更早搜索晚到的结果
        self._selection_generation = 0  # 丢弃更早资源详情/版本晚到的结果
        self._version_generation = 0    # 同一资源切换筛选时也只接受最后一次版本请求
        self._loaded_versions = None     # 文件全集；更换目标实例时只调整优先顺序
        # 只加载当前可见行，最多四张并行；CF 图标仍不缓存。
        self._icon_loaded = {}          # row -> 已启动请求或无图
        self._icon_queue = collections.deque()   # 待拉图标的 (list_item, slug, url)
        self._icon_active = 0
        self._icon_concurrency = 4
        self._icon_generation = 0
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

    def _initial_icon(self, h):
        """列表项初始图标:整合包无封面时逐级回退(加载器图标 → 草方块 → 占位)。"""
        if self.is_modpack and not h.get("icon_url"):
            return self._modpack_fallback_icon(h)
        return self._icon_placeholder

    def _modpack_fallback_icon(self, h):
        """整合包封面回退:有加载器 → 加载器图标;否则草方块;再否则占位。
        TODO:加载器图标暂为通用齿轮;待补 Fabric/Forge/NeoForge 官方 logo(需下载源+许可确认)。"""
        if h.get("loaders"):
            from launcher_app.ui.theme_icon import theme_icon
            ic = theme_icon("loader", 44)
            if not ic.isNull():
                return ic
        g = self._grass_block_icon()
        return g if not g.isNull() else self._icon_placeholder

    @staticmethod
    def _grass_block_icon(size: int = 44):
        """草方块图标(icons/grass_block.png),失败返回空 QIcon。"""
        import os
        from PySide6.QtGui import QIcon, QPixmap
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "icons", "grass_block.png")
        try:
            if os.path.isfile(p):
                pm = QPixmap(p)
                if not pm.isNull():
                    return QIcon(pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
        except Exception:
            pass
        return QIcon()

    def _build_ui(self):
        # ---- 搜索区 ----
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("resource_search")   # 教程定位(顶部常驻搜索框)
        self.search_edit.setPlaceholderText(
            t(f"搜索{self.label},回车确认(如 sodium / 钠 / 名字)", f"Search {self.label}, press Enter..."))
        self.search_edit.returnPressed.connect(self.do_search)
        self.clear_filters_btn = QPushButton(t("清除筛选", "Clear filters"))
        self.clear_filters_btn.setToolTip(t("清除关键词、版本、加载器和标签筛选", "Clear search, version, loader and tag filters"))
        self.clear_filters_btn.clicked.connect(self._clear_search_filters)
        set_style(self.clear_filters_btn, card_btn_style)

        self.sort_combo = QComboBox()
        for lbl, val in [("下载量", "downloads"),
                         ("相关度", "relevance"),
                         ("最近更新", "updated")]:
            self.sort_combo.addItem(t(lbl, lbl), val)
        self.sort_combo.setToolTip(t('排序方式', 'Sort order'))

        self.source_combo = QComboBox()
        self.source_combo.setObjectName('filter_source')
        self.source_combo.addItem(t("全部", "All"), "all")
        self.source_combo.addItem("Modrinth", "modrinth")
        self.source_combo.addItem("CurseForge", "curseforge")
        self.source_combo.setToolTip(t("资源来源", "Resource source"))
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)

        # 标签(分类)多级菜单:替代以前"手输标签"。点开是一棵分组菜单,可多选。
        self.tag_btn = QToolButton()
        self.tag_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        set_style(self.tag_btn, card_btn_style)
        self.tag_btn.setToolTip(t('按分类标签筛选 Modrinth 结果（可多选）'))
        self._selected_tags = set()
        self.tag_menu = QMenu(self.tag_btn)
        set_style(self.tag_menu, popup_menu_style)
        self.tag_btn.setMenu(self.tag_menu)
        self._build_tag_menu()
        control_height = max(36, self.search_edit.fontMetrics().height() + 16)
        filter_width = max(116, self.search_edit.fontMetrics().horizontalAdvance('CurseForge') + 44,
                           self.search_edit.fontMetrics().horizontalAdvance(self.clear_filters_btn.text()) + 28)
        for control in (self.search_edit, self.clear_filters_btn, self.source_combo, self.sort_combo, self.tag_btn):
            control.setFixedHeight(control_height)
            control.setFont(self.search_edit.font())
            set_style(control, resource_control_style)
        for control in (self.clear_filters_btn, self.source_combo, self.sort_combo, self.tag_btn):
            control.setFixedWidth(filter_width)

        # ---- 目标实例(折叠):装到哪个实例的对应目录(全局共享) ----
        self.inst_cards_toggle = QPushButton(t('▸ 目标实例: 未选择'))
        self.inst_cards_toggle.setCheckable(False)
        self.inst_cards_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.inst_cards_toggle.clicked.connect(self._toggle_cards)
        set_style(self.inst_cards_toggle, card_btn_style)
        self.instance_cards_box = QWidget()
        self.instance_cards_layout = QVBoxLayout(self.instance_cards_box)
        self.instance_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.instance_cards_layout.setSpacing(8)
        self._inst_cards = []          # [(inst, card)]
        self._none_card = None
        self.custom_label = QLabel("")
        set_style(self.custom_label, hint_style)
        self.custom_label.setWordWrap(True)
        # 实例可能很多:卡片区放进可滚动容器,展开时也不把筛选/搜索挤出界面
        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setWidget(self.instance_cards_box)
        self.cards_scroll.setMaximumHeight(300)
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
        self.result_list.ai_pin_provider = self._pin_resource
        self.result_list.setWordWrap(True)
        self.result_list.setIconSize(QSize(44, 44))     # 资源卡片左侧显示 Mod 图标(默认 16px 太小不显眼)
        self.result_list.setSpacing(2)
        self.result_list.setUniformItemSizes(False)
        # 逐像素滚动(触控板/滚轮更顺,与其它列表统一)
        self.result_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.result_list.setHorizontalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        set_style(self.result_list, list_style)
        self.result_list.setItemDelegate(_ResourceSourceDelegate(self.result_list))
        self.result_list.currentItemChanged.connect(self._on_selected)
        # 懒加载图标:滚动/改变大小时,只为当前可见的行拉图(并按顺序慢慢存)
        self.result_list.verticalScrollBar().valueChanged.connect(self._on_icon_visibility)
        self.result_list.verticalScrollBar().rangeChanged.connect(self._on_icon_visibility)
        # 滚动到底加载更多(分页)
        self.result_list.verticalScrollBar().valueChanged.connect(self._maybe_load_more)

        self.panel = QWidget()
        self.panel.setObjectName('resource_description')
        # 详情面板:透明底(壁纸直接透出)+ 细边框,不再用磨砂实心
        set_style(self.panel, lambda: f"QLabel, QCheckBox {{ border: none; background: transparent; color: {text_color()}; }}")
        self.icon_label = None   # 详情面板顶部不再放大图;Mod 图标改在左侧列表卡片显示
        self.title_label = QLabel("")
        self.title_label.setWordWrap(True)
        set_style(self.title_label, lambda: f"font-weight: bold; font-size: 15px; color: {text_color()};")
        self.meta_label = QLabel("")
        set_style(self.meta_label, hint_style)
        self.meta_label.setWordWrap(True)
        self.compat_range_label = QLabel("")
        self.compat_range_label.setWordWrap(True)
        self.compat_range_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        set_style(self.compat_range_label, lambda: f"color: {muted_color()}; font-size: 12px;")
        self.compat_range_label.setVisible(False)
        self.desc_label = QLabel("")
        set_style(self.desc_label, hint_style)
        self.desc_label.setWordWrap(True)
        self.desc_label.setTextFormat(Qt.TextFormat.PlainText)
        self.desc_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.desc_original_heading = QLabel(t('原文'))
        self.desc_translation_heading = QLabel(t('译文'))
        self.desc_translation_label = QLabel('')
        self.desc_translation_label.setWordWrap(True)
        self.desc_translation_label.setTextFormat(Qt.TextFormat.PlainText)
        self.desc_translation_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        set_style(self.desc_translation_label, hint_style)
        for heading in (self.desc_original_heading, self.desc_translation_heading):
            set_style(heading, lambda: f'color:{text_color()}; font-weight:bold; font-size:12px;')
            heading.hide()
        self.desc_translation_label.hide()
        self.desc_note_label = QLabel("")
        self.desc_note_label.setWordWrap(True)
        set_style(self.desc_note_label, lambda: f"color: {muted_color()}; font-size: 11px;")
        self.desc_note_label.setVisible(False)
        self.desc_translate_btn = QPushButton(t('生成翻译'))
        set_style(self.desc_translate_btn, card_btn_style)
        self.desc_translate_btn.setVisible(False)
        self.desc_translate_btn.clicked.connect(
            lambda: self._start_desc_translation(self._current or {}, manual=True))
        self.compat_box = QGroupBox(t('兼容与依赖'))
        set_style(self.compat_box, lambda:
            f"QGroupBox {{ color: {text_color()}; border: 1px solid {current_color('panel_border')};"
            " border-radius: 7px; margin-top: 6px; padding: 7px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }")
        compat_layout = QVBoxLayout(self.compat_box)
        compat_layout.setContentsMargins(4, 7, 4, 2)
        compat_layout.setSpacing(4)
        self.compat_summary = QLabel("")
        self.compat_summary.setWordWrap(True)
        set_style(self.compat_summary, lambda: f"color: {muted_color()}; font-size: 12px;")
        self.compat_detail = QLabel("")
        self.compat_detail.setWordWrap(True)
        set_style(self.compat_detail, lambda: f"color: {muted_color()}; font-size: 12px;")
        self.compat_detail.setVisible(False)
        self.compat_toggle = QPushButton(t('查看依赖详情'))
        self.compat_toggle.setFlat(True)
        self.compat_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        set_style(self.compat_toggle, lambda: f"color: {accent_color()}; text-align: left; padding: 2px;")
        self.compat_toggle.clicked.connect(self._toggle_compat_detail)
        compat_layout.addWidget(self.compat_summary)
        compat_layout.addWidget(self.compat_detail)
        compat_layout.addWidget(self.compat_toggle)
        self.compat_box.setVisible(False)
        # 「在 MC百科查看」链接:仅选中时显示,点击用系统浏览器打开 mcmod 按名搜索页。
        self.mcmod_link = QLabel()
        self.mcmod_link.setTextFormat(Qt.TextFormat.RichText)
        self.mcmod_link.setOpenExternalLinks(False)   # 点击走 QDesktopServices,统一 URL 构造
        self.mcmod_link.linkActivated.connect(self._open_mcmod_link)
        set_style(self.mcmod_link, lambda: f"color: {accent_color()}; font-size: 12px;")
        self.mcmod_link.setVisible(False)
        # ---- 全局版本/加载器(方案一:搜索筛选 + 下载默认合一,底部卡显示) ----
        # 游戏版本用版本树(按大版本分组,点大版本自动选推荐版),不再是可编辑下拉。
        self.gv_combo = GameVersionFilter()
        self.gv_combo.setToolTip(t("按资源声明的游戏版本筛选", "Filter by declared game version"))
        self._gv_none_label = t("ANY_VERSION")
        self.loader_combo = QComboBox()
        self.loader_combo.setObjectName("filter_loader")
        self.loader_combo.addItem(t("任意", "Any"), None)
        for label, value in [("Fabric", "fabric"), ("Forge", "forge"),
                             ("NeoForge", "neoforge"), ("Quilt", "quilt")]:
            self.loader_combo.addItem(label, value)
        self.ver_combo = QComboBox()
        # 使用受高度限制的列表弹层；Windows 原生下拉会忽略最大可见项数。
        self.ver_combo.setView(QListView(self.ver_combo))
        self.ver_combo.setMaxVisibleItems(8)
        self.ver_combo.setStyleSheet("QComboBox { combobox-popup: 0; }")
        self.ver_combo.view().setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.file_loader_filter = QComboBox()
        self.file_mc_filter = QComboBox()
        self.file_loader_filter.setObjectName('file_loader_filter')
        self.file_mc_filter.setObjectName('file_mc_filter')
        for combo in (self.file_loader_filter, self.file_mc_filter):
            combo.addItem(t('全部', 'All'), None)
            combo.currentIndexChanged.connect(lambda: self._render_versions(preserve_selection=True))
        for combo in (self.ver_combo, self.gv_combo, self.loader_combo,
                      self.file_loader_filter, self.file_mc_filter):
            combo.setView(QListView(combo))
            combo.setMaxVisibleItems(8)
            combo.view().setMaximumHeight(8 * max(28, combo.fontMetrics().height() + 10))
            combo.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.dl_btn = QPushButton(t("DOWNLOAD"))
        set_style(self.dl_btn, resource_control_style, True)
        self.dl_btn.clicked.connect(self._download)
        self.gv_combo.version_changed.connect(self._on_search_filter_changed)
        self.loader_combo.currentIndexChanged.connect(self._on_search_filter_changed)
        self.ver_combo.currentIndexChanged.connect(self._update_fav_btn)
        self.ver_combo.currentIndexChanged.connect(self._refresh_compatibility_report)
        self.ver_combo.currentIndexChanged.connect(self._refresh_download_warning)

        # 顶部筛选项目，详情面板选择具体文件并执行下载。
        p = QVBoxLayout(self.panel)
        p.setContentsMargins(0, 0, 0, 0)
        p.setSpacing(8)
        p.addWidget(self.title_label)
        p.addWidget(self.meta_label)
        p.addWidget(self.compat_range_label)
        p.addWidget(self.desc_label)
        p.insertWidget(p.indexOf(self.desc_label), self.desc_original_heading)
        p.addWidget(self.desc_translation_heading)
        p.addWidget(self.desc_translation_label)
        p.addWidget(self.desc_note_label)
        p.addWidget(self.desc_translate_btn, 0, Qt.AlignLeft)
        p.addWidget(self.compat_box)
        p.addWidget(self.mcmod_link)
        self.empty_label = QLabel(t("SELECT_A_PROJECT_ON_THE_LEFT"))
        set_style(self.empty_label, hint_style)
        self.empty_label.setWordWrap(True)
        p.addWidget(self.empty_label)
        p.addStretch()
        for w in (self.title_label, self.meta_label, self.desc_label):
            w.setVisible(False)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(self.result_list)
        self.detail_column = QWidget()
        self.detail_column.setObjectName('resource_detail')
        self.detail_column.setMinimumWidth(260)
        self.detail_column.setMaximumWidth(500)
        set_style(self.detail_column, lambda: f"QWidget#resource_detail {{ border: 1px solid {current_color('panel_border')};"
                  f" border-radius: 12px; background: transparent; }}")
        detail_layout = QVBoxLayout(self.detail_column)
        detail_layout.setContentsMargins(14, 14, 14, 14)
        detail_layout.setSpacing(0)
        panel_scroll = QScrollArea(self.detail_column)
        self.detail_scroll = panel_scroll
        panel_scroll.setObjectName('resource_description_scroll')
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # QScrollArea viewport 默认不透明会遮住透明面板,这里设透明让壁纸透出
        panel_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        panel_scroll.setWidget(self.panel)
        detail_layout.addWidget(panel_scroll, 1)
        self.split.addWidget(self.detail_column)
        self.split.setChildrenCollapsible(False)
        self.split.setSizes([440, 280])   # 列表更宽,右窄条更窄

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        if self.is_modpack:
            # 整合包=一键全集:下载后作为「新实例」导入,无需选目标实例/目录
            self.modpack_hint = QLabel(
                t("选择整合包，在详情中选择文件版本并下载为新实例", "Choose a modpack and file version to install as a new instance"))
            set_style(self.modpack_hint, hint_style)
            self.modpack_hint.setWordWrap(True)
            layout.addWidget(self.modpack_hint)
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_row.addWidget(self.search_edit, 1)
        self.search_btn = QPushButton(t('搜索', 'Search'))
        self.search_btn.setFixedSize(96, self.search_edit.height())
        set_style(self.search_btn, resource_control_style)
        self.search_btn.clicked.connect(self.do_search)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)
        filters = QWidget()
        filters.setObjectName('resource_filters')
        set_style(filters, lambda: 'QWidget#resource_filters {' + panel_style() +
                  '} QLabel { background: transparent; border: none; color: ' + text_color() + '; }')
        grid = QGridLayout(filters)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for column, (label, control) in enumerate(((t('来源', 'Source'), self.source_combo),
                (t('标签', 'Tags'), self.tag_btn), (t('排序', 'Sort'), self.sort_combo))):
            control.setMinimumWidth(0)
            control.setMaximumWidth(16777215)
            control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            grid.addWidget(QLabel(label), 0, column * 2)
            grid.addWidget(control, 0, column * 2 + 1)
            grid.setColumnStretch(column * 2 + 1, 1)
        for column, (label, control) in enumerate(((t('版本', 'Version'), self.gv_combo),
                                                  (t('加载器', 'Loader'), self.loader_combo))):
            control.setFixedHeight(self.search_edit.height())
            set_style(control, resource_control_style)
            grid.addWidget(QLabel(label), 1, column * 2)
            grid.addWidget(control, 1, column * 2 + 1)
        self.loader_combo.setEnabled(self.project_type in ('mod', 'modpack'))
        self.clear_filters_btn.setMinimumWidth(0)
        self.clear_filters_btn.setMaximumWidth(16777215)
        grid.addWidget(self.clear_filters_btn, 1, 5)
        layout.addWidget(filters)
        status_row = QHBoxLayout()
        self.search_status = QLabel(t('选择目标实例后，将自动更新兼容资源'))
        self.search_status.setWordWrap(True)
        set_style(self.search_status, hint_style)
        self.search_progress = QProgressBar()
        self.search_progress.setRange(0, 0)
        self.search_progress.setFixedSize(72, 6)
        self.search_progress.setTextVisible(False)
        self.search_progress.hide()
        self.search_retry = QPushButton(t('重试'))
        self.search_retry.clicked.connect(self.do_search)
        self.search_retry.hide()
        status_row.addWidget(self.search_status, 1)
        status_row.addWidget(self.search_progress)
        status_row.addWidget(self.search_retry)
        layout.addLayout(status_row)
        layout.addWidget(self.split, 1)
        self._build_detail_downloads()

        # 切换排序时,若处于默认浏览(空关键词)则重新拉取
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)

    def _build_detail_downloads(self):
        self.download_section = QWidget(self.detail_column)
        self.download_section.setObjectName('resource_download_section')
        set_style(self.download_section, lambda: f'QWidget#resource_download_section {{ border: none;'
                  f' border-top: 1px solid {current_color("panel_border")}; background: transparent; }}'
                  f'QLabel {{ color: {text_color()}; border: none; background: transparent; }}')
        self.download_section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        section = QVBoxLayout(self.download_section)
        section.setContentsMargins(0, 12, 0, 0)
        section.setSpacing(8)
        for title, combo in ((t('加载器', 'Loader'), self.file_loader_filter),
                             (t('版本', 'Version'), self.file_mc_filter)):
            row = QHBoxLayout()
            row.addWidget(QLabel(title))
            row.addWidget(combo, 1)
            section.addLayout(row)
        section.addWidget(self.ver_combo)
        self.inst_cards_toggle.setCheckable(True)
        set_style(self.inst_cards_toggle, resource_control_style)
        section.addWidget(self.inst_cards_toggle)
        self.inst_cards_toggle.setVisible(not self.is_modpack)
        self.inst_popup = PopupCard(self)
        self.inst_popup.setObjectName('inst_popup')
        set_style(self.inst_popup, popup_panel_style)
        popup = QVBoxLayout(self.inst_popup)
        popup.setContentsMargins(14, 12, 14, 12)
        popup.addWidget(self.cards_scroll)
        popup.addWidget(self.custom_label)
        self.inst_popup.setMinimumWidth(320)
        self.inst_popup.setMaximumWidth(600)
        self.inst_popup.hide()
        self.inst_popup.closed.connect(self._on_popup_closed_autoclose)
        self.fav_btn = QToolButton()
        self.fav_btn.setText('☆')
        self.fav_btn.setToolTip(t('收藏资源', 'Favorite resource'))
        self.fav_btn.setAccessibleName(t('收藏资源', 'Favorite resource'))
        self.fav_btn.clicked.connect(self._fav_current)
        self.fav_menu = QMenu(self.fav_btn)
        set_style(self.fav_menu, popup_menu_style)
        self.fav_version_action = self.fav_menu.addAction(t('＋ 收藏当前版本'))
        self.fav_version_action.triggered.connect(self._fav_selected_version)
        self.fav_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.fav_btn.customContextMenuRequested.connect(lambda pos: self.fav_menu.exec(self.fav_btn.mapToGlobal(pos)))
        set_style(self.fav_btn, resource_control_style)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.fav_btn)
        actions.addWidget(self.dl_btn, 1)
        section.addLayout(actions)
        height = max(36, self.search_edit.fontMetrics().height() + 16)
        for control in (self.ver_combo, self.file_loader_filter, self.file_mc_filter, self.inst_cards_toggle, self.fav_btn, self.dl_btn):
            control.setFixedHeight(height)
            control.setFont(self.search_edit.font())
        self.fav_btn.setFixedWidth(height)
        set_style(self.fav_btn, lambda: resource_control_style() + 'QToolButton { padding: 0; font-size: 20px; }')
        set_style(self.ver_combo, resource_control_style)
        set_style(self.file_loader_filter, resource_control_style)
        set_style(self.file_mc_filter, resource_control_style)
        self.download_warning = QLabel()
        self.download_warning.setWordWrap(True)
        set_style(self.download_warning, lambda: f'color: {warning_color()}; border: none; background: transparent;')
        self.download_warning.hide()
        section.addWidget(self.download_warning)
        self.detail_column.layout().addWidget(self.download_section)
        self.download_section.hide()
        self._sync_target_ui()

    def _toggle_cards(self):
        """点目标实例按钮:打开/收起悬浮层。"""
        if self.inst_popup.isVisible():
            self._close_inst_popup()
            return
        if time.time() - getattr(self, "_cards_last_closed", 0) < 0.3:
            return   # 刚被点外部自动关闭:这次点击不重复打开
        self.inst_cards_toggle.setText("▾ " + self.inst_cards_toggle.text()[2:])
        self.cards_scroll.setVisible(True)
        self.cards_scroll.updateGeometry()
        self.inst_popup.layout().activate()
        hint = self.inst_popup.layout().sizeHint()
        self.inst_popup.resize(max(380, hint.width()), max(60, hint.height()))
        self._popup_above(self.inst_popup, self.inst_cards_toggle)
        self._apply_shared_wallpaper(self.inst_popup)
        self.inst_popup.show()
        self.inst_popup.raise_()

    def _popup_above(self, popup, anchor):
        """把浮窗放在 anchor 附近,并限制在当前屏幕可用区域内。"""
        g = anchor.mapToGlobal(anchor.rect().topLeft())
        screen = QGuiApplication.screenAt(g) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else self.window().geometry()
        popup.setMaximumWidth(max(280, available.width() - 24))
        if popup.width() > available.width() - 24:
            popup.resize(available.width() - 24, popup.height())
        # 优先放在按钮上方；若上方空间不足，则放在下方，并让列表区滚动。
        above = g.y() - available.top() - 12
        below = available.bottom() - (g.y() + anchor.height()) - 12
        room = max(above, below)
        max_height = max(120, min(420, room))
        if popup.height() > max_height:
            popup.resize(popup.width(), max_height)
        top = self.window().mapToGlobal(self.window().rect().topLeft())
        x = max(available.left() + 12, min(g.x(), available.right() - popup.width() - 12))
        if above >= popup.height() or above >= below:
            y = g.y() - popup.height()
        else:
            y = g.y() + anchor.height()
        y = max(available.top() + 12, min(y, available.bottom() - popup.height() - 12))
        popup.move(x, y)

    def _apply_shared_wallpaper(self, popup):
        """把主窗共享壁纸片段同步给弹层(按相对中央区位置),壁纸透出。"""
        if not hasattr(popup, "set_shared_view"):
            return
        win = self.window()
        cg = getattr(win, "_background", None)
        scaled = getattr(win, "_wallpaper_scaled", None)
        if popup is None or cg is None or scaled is None:
            popup.set_shared_view(None, 0, 0, 0.6)
            return
        ox = getattr(win, "_wallpaper_ox", 0)
        oy = getattr(win, "_wallpaper_oy", 0)
        mask = getattr(win, "_wallpaper_mask", 0.6)
        dg = popup.mapToGlobal(popup.rect().topLeft())
        cgt = cg.mapToGlobal(cg.rect().topLeft())
        popup.set_shared_view(scaled, ox + dg.x() - cgt.x(), oy + dg.y() - cgt.y(), mask)

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
        self.tag_btn.setText(t('已选 {v0} 项').format(v0=(n)) if n else t('全部'))

    def _clear_tags(self):
        if self._selected_tags:
            self._selected_tags.clear()
            self._build_tag_menu()   # 重建,取消所有勾选 + 清空项禁用
            self.do_search()

    def _clear_search_filters(self):
        """清除本页的搜索条件，并只发起一次刷新。"""
        self.search_edit.clear()
        self._selected_tags.clear()
        self._build_tag_menu()
        previous_gv = self.gv_combo.blockSignals(True)
        previous_loader = self.loader_combo.blockSignals(True)
        try:
            self.gv_combo.select_version("")
            self.loader_combo.setCurrentIndex(0)
        finally:
            self.gv_combo.blockSignals(previous_gv)
            self.loader_combo.blockSignals(previous_loader)
        self.do_search()

    # ---- 目标实例(全局共享) ----
    def _set_target_hooks(self, getter, setter):
        self._target_getter = getter
        self._target_setter = setter

    def populate_game_versions(self, manifest: dict):
        """填充实际游戏版本，不推断推荐版本。"""
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
            snapshot = self._instance_pin_snapshot(inst)
            card.ai_pin_provider = lambda pos, data=snapshot: dict(data)
            card.setCheckable(True)
            card.setMinimumHeight(48)
            set_style(card, card_btn_style)
            card.clicked.connect(lambda _c, i=inst: self._select_inst(i))
            self.instance_cards_layout.addWidget(card)
            self._inst_cards.append((inst, card))
        none_card = QPushButton(t("NONE_PICK_FOLDER"))
        none_card.setCheckable(True)
        none_card.setMinimumHeight(48)
        set_style(none_card, card_btn_style)
        none_card.clicked.connect(self._select_none)
        self.instance_cards_layout.insertWidget(0, none_card)
        self._none_card = none_card
        # 内容区最小高度 = 卡片数×(卡片高48 + 间距8):widgetResizable 不会把 box 压到低于该值,
        # 内容超出视口(210)时滚动区才真正滚动,而不是把卡片压扁/互相重叠
        n = len(self._inst_cards) + (1 if self._none_card else 0)
        self.instance_cards_box.setMinimumHeight(n * 56)
        self.cards_scroll.updateGeometry()

        self._sync_target_ui()

    @staticmethod
    def _instance_pin_snapshot(inst):
        import paths
        directory = os.path.join(paths.GAME_DIR, "versions", inst["id"])
        return {"id": directory, "kind": "instance", "instance": inst["id"],
                "name": inst.get("name") or inst["id"], "directory": directory,
                "minecraft": inst.get("base") or inst["id"],
                "loader": inst.get("loader") or "vanilla"}

    def _apply_inst_cards(self, inst_id):
        """把卡片勾选状态对齐到某个实例(inst_id 为 None 时勾"无")。"""
        for i, card in self._inst_cards:
            card.setChecked(i["id"] == inst_id)
        if self._none_card:
            self._none_card.setChecked(inst_id is None)

    def _sync_target_ui(self):
        """把全局目标反映到本浏览器的文案/勾选状态。不触发 setter,避免递归。"""
        inst, dir_ = self._target_getter()
        previous_target = getattr(self, '_filter_target', None)
        target = (inst.get('id'), inst.get('base'), inst.get('loader')) if inst else None
        self._filter_target = target
        self.selected_inst = inst
        self.custom_dir = dir_
        filters_changed = previous_target != target and self.project_type == 'mod'
        if filters_changed:
            for combo in (self.gv_combo, self.loader_combo):
                combo.blockSignals(True)
            try:
                version = (inst or {}).get('base') or ''
                if version and self.gv_combo.findData(version) < 0:
                    self.gv_combo.addItem(version, version)
                self.gv_combo.select_version(version)
                loader = str((inst or {}).get('loader') or '').lower()
                self.loader_combo.setCurrentIndex(max(0, self.loader_combo.findData(loader or None)))
            finally:
                for combo in (self.gv_combo, self.loader_combo):
                    combo.blockSignals(False)
        if inst is not None:
            self.inst_cards_toggle.setText(t('▸ 目标实例: {v0}').format(v0=(inst['id'])))
            self._apply_inst_cards(inst["id"])
            self.custom_label.setText("")
        elif dir_:
            self.inst_cards_toggle.setText(t('▸ 目标实例: 自定义目录'))
            self._apply_inst_cards(None)
            self.custom_label.setText(f"{t("INSTALL_TO")}: {dir_}")
            self.custom_label.setVisible(True)
        else:
            self.inst_cards_toggle.setText(t('▸ 目标实例: 未选择'))
            self._apply_inst_cards(None)
        if (self.project_type in ('datapack', 'resourcepack')
                and getattr(self, '_current', None) and self._loaded_versions is not None):
            self._fill_versions(self._loaded_versions, preserve_selection=True)
        self._refresh_compatibility_report()
        self._refresh_download_warning()
        if filters_changed:
            if self._loaded_versions is not None:
                self._fill_versions(self._loaded_versions)
            if self._search_params is not None:
                self.do_search()

    def _select_inst(self, inst):
        """选中某实例:更新本地卡片+筛选,并广播到全局(其他分类页一并生效)。"""
        self._apply_inst_cards(inst["id"])
        # 选中后收起悬浮层,标题箭头复位
        self._close_inst_popup()
        self._target_setter(inst, None)
        self._refresh_download_warning()

    def _select_none(self):
        """选择“无”实例时立即打开文件夹选择器，设置自定义安装目录。"""
        self._close_inst_popup()
        import paths
        start_dir = self.custom_dir or paths.GAME_DIR
        self.pick_custom_dir(start_dir)

    def _close_inst_popup(self):
        """收起目标实例悬浮层并复位标题箭头。"""
        self.inst_popup.hide()
        self._cards_last_closed = time.time()
        self.inst_cards_toggle.setText(
            "▸ " + self.inst_cards_toggle.text()[2:])

    def _on_popup_closed_autoclose(self):
        """浮窗被点外面/其他途径关闭时,记录时刻(供按钮防重开守卫),并复位箭头。"""
        if self.inst_popup.isVisible():
            return
        self._cards_last_closed = time.time()
        if self.inst_cards_toggle.text().startswith("▾"):
            self.inst_cards_toggle.setText(
                "▸ " + self.inst_cards_toggle.text()[2:])

    def pick_custom_dir(self, game_dir: str):
        """用户用文件管理器选安装位置(装到其他启动器的目录)。"""
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self.window(), t("PICK_FOLDER"), game_dir)
        if d:
            self._target_setter(None, d)

    # ---- 异步基础设施 ----
    def _async(self, cache_key, fetch, on_done, cache: bool = True):
        """后台线程跑网络请求 fetch(),完成后回主线程调 on_done(结果)。
        cache=True 时按 cache_key 缓存,第二次直接同步回调;False 则总是重新请求。"""
        if cache and cache_key in self._async_cache:
            on_done(self._async_cache[cache_key])
            return
        if cache and cache_key in self._async_inflight:
            self._async_inflight[cache_key].append(on_done)
            return
        if cache:
            self._async_inflight[cache_key] = [on_done]

        task = BackgroundTask(lambda _task: fetch(), self)
        self._async_tasks.add(task)

        def apply_result(result):
            if cache:
                self._async_cache[cache_key] = result
                callbacks = self._async_inflight.pop(cache_key, [])
            else:
                callbacks = [on_done]
            for callback in callbacks:
                try:
                    callback(result)
                except Exception:
                    pass

        task.succeeded.connect(apply_result)
        task.failed.connect(lambda _error: apply_result(None))
        task.finished.connect(lambda: self._async_tasks.discard(task))
        task.start()

    # ---- 搜索 ----
    def _current_gv(self):
        """返回当前全局游戏版本值;「无(全部版本)」或空 → None(不按版本过滤)。"""
        v = self.gv_combo.current_version() or ""
        if v == self._gv_none_label or v == "":
            return None
        return v

    def _source(self):
        return self.source_combo.currentData() or "all"

    def _on_source_changed(self):
        # 分类标签是 Modrinth 专有字段，切换来源时不要留下看似仍有效的标签筛选。
        if self._source() == "curseforge":
            self._selected_tags.clear()
            self.tag_btn.setEnabled(False)
            self.tag_btn.setText(t('不支持', 'Unavailable'))
            self.tag_btn.setToolTip(t('CurseForge 暂不支持此标签筛选'))
            self.loader_combo.setEnabled(self.project_type in ('mod', 'modpack'))
            self.loader_combo.setToolTip("")
        else:
            self._build_tag_menu()
            self.tag_btn.setToolTip(t('分类标签仅筛选 Modrinth 结果') if self._source() == 'all' else t('按分类标签筛选'))
            self.loader_combo.setEnabled(self.project_type in ('mod', 'modpack'))
            self.loader_combo.setToolTip("")
        if self.search_edit.text().strip() or self._auto_loaded:
            self.do_search()

    def do_search(self):
        self._search_generation += 1
        generation = self._search_generation
        query = self.search_edit.text().strip()
        # 允许空关键词:打开资源页即「默认浏览」(空 query → 按 sort_combo 排序,默认 downloads)。
        # 顶部条件筛选资源项目；具体文件在右侧详情中选择。
        order = self.sort_combo.currentData() or "downloads"
        tags = ",".join(sorted(self._selected_tags))
        self._last_query = query
        self._offset = 0
        self._no_more = False
        source = self._source()
        gv, loader = self._current_gv(), self.loader_combo.currentData()
        loader = loader if self.project_type in ('mod', 'modpack') else None
        self._search_params = (source, query, order, tags, gv, loader)
        self._search_pending = True
        selected = self.result_list.currentItem()
        self._search_previous_hit = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        self._search_scroll = self.result_list.verticalScrollBar().value()
        context = ' / '.join(str(v) for v in (gv, loader) if v) or '全部版本'
        name = (self.selected_inst or {}).get('id')
        self.search_status.setText(t('正在更新{v0} · {v1}… 原列表暂供参考').format(v0=(f"「{name}」的兼容资源" if name else "资源列表"), v1=(context)))
        self.search_progress.show()
        self.search_retry.hide()
        self.result_list.setEnabled(False)
        self._more_loading = False
        self._selection_generation += 1
        self._version_generation += 1
        self._current = None
        self.ver_combo.clear()
        self.dl_btn.setEnabled(False)
        self._refresh_download_warning()
        self._source_offsets = {}
        self._source_exhausted = {}

        def fetch():
            from launcher_app.resources.resource_catalog import search_page
            return search_page(source, self.project_type, query, order, tags, game_version=gv, loader=loader)

        def done(result):
            if generation != self._search_generation:
                return
            self._search_pending = False
            self.search_progress.hide()
            if result is None or (not result.get('hits') and result.get('errors')):
                self.search_status.setText(t('更新失败，保留原列表供参考。请重试，或调整筛选条件。'))
                self.search_retry.show()
                self._no_more = True
                self._auto_loaded = False
                return
            self.result_list.setEnabled(True)
            self._apply_search_page(result)
            count = len(result['hits'])
            self.search_status.setText(
                t('已更新 · {v0} · {v1} 项资源').format(v0=(context), v1=(count)) +
                (t('（部分来源暂不可用）') if result.get('errors') else '') if count else
                t('没有匹配 {v0} 的资源，可调整筛选或切换实例').format(v0=(context)))
            previous = self._search_previous_hit or {}
            restored = False
            for row in range(self.result_list.count()):
                item = self.result_list.item(row)
                hit = item.data(Qt.ItemDataRole.UserRole) or {}
                if previous and (hit.get('source'), hit.get('slug')) == (previous.get('source'), previous.get('slug')):
                    self.result_list.setCurrentItem(item)
                    self.result_list.verticalScrollBar().setValue(self._search_scroll)
                    restored = True
                    break
            if not restored:
                self._on_selected(None, None)

        self._async(("search", source, query, self.project_type, order, tags, gv, loader),
                    fetch, done, cache=False)

    def _apply_search_page(self, result, append=False):
        if result is None:
            self._fill_results(None, append=append)
            return
        self._source_offsets = result['offsets']
        self._source_exhausted = result['exhausted']
        self._fill_results(result['hits'], append=append)
        self._no_more = result['no_more']
        for source, error in result['errors'].items():
            label = 'CurseForge' if source == 'curseforge' else 'Modrinth'
            item = QListWidgetItem(f'{label}：{error}')
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.result_list.addItem(item)

    def maybe_auto_load(self):
        """打开/切到本资源页时,若搜索框为空,自动触发一次「默认浏览」。
        已加载过默认浏览(或正在显示)则不再重复拉取;不覆盖用户已输入的关键词。"""
        if self.search_edit.text().strip():
            return
        if getattr(self, "_auto_loaded", False):
            return
        self.do_search()

    def _on_sort_changed(self):
        """排序变化对当前关键词和筛选条件立即生效。"""
        self.do_search()

    def _on_search_filter_changed(self, *_args):
        if self._search_params is not None:
            self.do_search()

    def _refresh_versions_global(self):
        """游戏版本/加载器变化只刷新当前资源的文件版本列表。"""
        if self.project_type in FLEXIBLE_VERSION_TYPES:
            return
        if getattr(self, "_current", None):
            self._refresh_versions()

    def _fill_results(self, hits, append=False):
        if not append:
            self._icon_generation += 1
            self.result_list.clear()
            # 清掉旧的行索引懒加载状态:新列表行索引从 0 重新开始,不清会误跳过新前几行
            # (旧索引 0..8 已标"加载过" → 新前几行不拉图,只拉下方 9+ 的行 → 观感"只加载下面")
            self._icon_loaded = {}
            self._icon_queue = collections.deque()
        if hits is None:
            if not append:
                self._auto_loaded = False
                QListWidgetItem(t("SEARCH_FAILED_CHECK_NETWORK"), self.result_list)
            self._more_loading = False
            return
        for h in hits:
            author = h.get("author", "")
            dl = f"⬇{h.get('downloads', 0):,}" if h.get("downloads") else ""
            meta = "  ".join(x for x in (author, dl) if x)
            text = f"{h['title']}\n{h.get('description', '')[:60]}" + (f"\n{meta}" if meta else "")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, h)
            # 左侧先占一个固定大小的框:文本从它右侧开始,真图标到了才替换(不重排)
            item.setIcon(self._initial_icon(h))
            self.result_list.addItem(item)
        if not hits and not append and not self.result_list.count():
            QListWidgetItem(t("NO_RESULTS"), self.result_list)
        # 记录默认浏览是否已加载(空关键词的结果),供 maybe_auto_load 判断是否重复拉取
        if not append:
            self._auto_loaded = (getattr(self, "_last_query", "") == "")
        # 分页游标 + 是否还有更多(不足一页 = 到底了)
        self._offset += len(hits)
        self._no_more = len(hits) < 30
        self._more_loading = False
        # 只给当前可见的条目按顺序懒加载图标(用户没看到的先不拉不存)
        self._icon_visibility_timer.start(80)

    def _pin_resource(self, pos):
        item = self.result_list.itemAt(self.result_list.viewport().mapFromGlobal(pos))
        hit = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(hit, dict):
            return None
        source = hit.get("source") or "modrinth"
        project_id = hit.get("curseforge_id") if source == "curseforge" else hit.get("project_id") or hit.get("slug")
        if project_id is None:
            return None
        return {"id": f"resource:{source}:{project_id}", "kind": "resource",
                "name": hit.get("title") or hit.get("slug") or str(project_id),
                "source": source, "project_id": str(project_id),
                "resource_type": self.project_type, "description": hit.get("description") or "",
                "url": hit.get("website_url") or (f"https://modrinth.com/project/{project_id}" if source == "modrinth" else ""),
                "target_instance": (self.selected_inst or {}).get("id") or "未选择",
                "version_selection": ("未固定具体版本；文件标签供参考，可选择其他版本"
                                      if self.project_type in FLEXIBLE_VERSION_TYPES else
                                      "未固定具体版本，下载前需确认与目标实例兼容")}

    def _maybe_load_more(self, value: int = 0):
        """滚动到底附近 → 加载下一页(分页)。"""
        if getattr(self, '_search_pending', False) or not self.result_list.isEnabled():
            return
        if getattr(self, "_more_loading", False) or getattr(self, "_no_more", False):
            return
        if getattr(self, "_search_params", None) is None:
            return
        sb = self.result_list.verticalScrollBar()
        if sb.maximum() <= 0 or value < sb.maximum() - 40:
            return
        self._load_more()

    def _load_more(self):
        """加载下一页结果并追加到列表。"""
        self._more_loading = True
        source, query, order, tags, gv, loader = self._search_params
        generation = self._search_generation
        expected_params = self._search_params
        offset = self._offset

        offsets = dict(self._source_offsets)
        exhausted = dict(self._source_exhausted)

        def fetch():
            from launcher_app.resources.resource_catalog import search_page
            return search_page(source, self.project_type, query, order, tags, offsets, exhausted, game_version=gv, loader=loader)

        def on_done(result):
            if generation != self._search_generation or self._search_params != expected_params:
                return
            self._apply_search_page(result, append=True)

        self._async(("more", source, query, self.project_type, order, tags, gv, loader, offset),
                    fetch, on_done, cache=False)

    # ---- 详情面板 ----
    def _mcmod_url(self, display_name: str) -> str:
        """构造在 MC百科(mcmod.cn)按名搜索该 Mod 的链接;用 quote 编码中文/特殊字符。
        mcmod 用自己的 class id,与 Modrinth slug 非 1:1,故用「按名搜索」最稳。"""
        return "https://search.mcmod.cn/s?key=" + urllib.parse.quote(display_name)

    def _resource_links(self, hit, name):
        from html import escape
        source = hit.get('source', 'modrinth')
        query = urllib.parse.quote(name)
        kind = self.project_type
        routes = {'mod': 'mods', 'modpack': 'modpacks', 'shader': 'shaders',
                  'datapack': 'datapacks', 'resourcepack': 'resourcepacks'}
        classes = {'mod': 'mc-mods', 'modpack': 'modpacks', 'shader': 'shaders',
                   'datapack': 'data-packs', 'resourcepack': 'texture-packs'}
        if source == 'curseforge':
            cf_url = hit.get('website_url') or f'https://www.curseforge.com/projects/{hit["curseforge_id"]}'
            mr_url = hit.get('modrinth_url') or f'https://modrinth.com/{routes.get(kind, "mods")}?q={query}'
            mr_label = 'Modrinth' if hit.get('modrinth_url') else 'Modrinth 搜索'
            cf_label = 'CurseForge'
        else:
            project = urllib.parse.quote(str(hit.get('project_id') or hit.get('slug')), safe='')
            mr_url = f'https://modrinth.com/project/{project}'
            cf_url = hit.get('curseforge_url') or f'https://www.curseforge.com/minecraft/search?class={classes.get(kind, "mc-mods")}&search={query}'
            mr_label = 'Modrinth'
            cf_label = 'CurseForge' if hit.get('curseforge_url') else 'CurseForge 搜索'
        links = [('MC百科', self._mcmod_url(name)), (mr_label, mr_url), (cf_label, cf_url)]
        return ' · '.join(f'<a style="color: {accent_color()}; text-decoration: underline;" '
                         f'href="{escape(url, quote=True)}">{escape(label)}</a>' for label, url in links)

    def _open_mcmod_link(self, url: str):
        """点击链接 → 系统浏览器打开 mcmod 搜索页。仅用户主动打开,无爬取/缓存/入库。"""
        QDesktopServices.openUrl(QUrl(url))

    def _on_selected(self, current, _prev):
        self._selection_generation += 1
        if current is None:
            self._current = None
            self.dl_btn.setEnabled(False)
            self._refresh_download_warning()
            self.mcmod_link.setVisible(False)
            self.compat_range_label.setVisible(False)
            self.download_section.hide()
            return
        h = current.data(Qt.ItemDataRole.UserRole)
        if not h:
            self.mcmod_link.setVisible(False)
            self.compat_range_label.setVisible(False)
            self.download_section.hide()
            return
        self._current = h
        self.download_section.show()
        self.compat_box.setVisible(False)
        self.compat_detail.setVisible(False)
        self.compat_toggle.setText(t('查看依赖详情'))
        for w in (self.title_label, self.meta_label,
                  self.desc_label, self.ver_combo, self.dl_btn, self.fav_btn):
            w.setVisible(True)
        if self.project_type not in FLEXIBLE_VERSION_TYPES:
            self.gv_combo.setVisible(True)
            self.loader_combo.setVisible(True)
        # 收藏保存定位信息，详情和文件列表仍由平台实时提供。
        self.fav_btn.setEnabled(True)
        self.empty_label.setVisible(False)
        self.title_label.setText(h["title"])
        # 「在 MC百科查看」链接:用显示名(优先已替换的中文名)按名搜索,中文最准;
        # 标题为空 → 退回 slug/描述(纯英文标题即 Modrinth 原名,也直接可用)。
        name = (h.get("title") or "").strip()
        if not name:
            name = (h.get("slug") or "").strip()
        if not name:
            name = (h.get("description") or "").strip()[:80]
        self.mcmod_link.setText(self._resource_links(h, name))
        self.mcmod_link.setVisible(bool(name))
        meta = []
        if h.get("author"):
            meta.append(f"作者:{h['author']}")
        if h.get("downloads"):
            meta.append(f"⬇{h['downloads']:,}")
        meta.append("来源: CurseForge" if h.get("source") == "curseforge" else "来源: Modrinth")
        if h.get("categories"):
            meta.append("·".join(h["categories"][:6]))
        self.meta_label.setText("  ".join(meta))
        self.compat_range_label.setText(t('正在读取兼容范围…'))
        self.compat_range_label.setToolTip("")
        self.compat_range_label.setVisible(True)
        self.desc_label.setText(h.get("description", ""))
        self.desc_note_label.setText("")
        self.desc_note_label.setVisible(False)
        self._update_fav_btn()
        # 直接加载当前项目的文件版本；无需额外请求项目详情。
        self._loaded_versions = None
        self.ver_combo.clear()
        self.dl_btn.setEnabled(False)
        self._refresh_versions()
        self._load_compatibility_range(h, self._selection_generation)
        # 后台线程翻译 Mod 描述(不卡 UI);若关闭开关则保持原文
        self._start_desc_translation(h)

    def _load_compatibility_range(self, hit: dict, generation: int):
        """Summarize all declared file versions, independent of download filters."""
        source = hit.get('source', 'modrinth')
        slug = hit.get('slug')

        def fetch():
            if source == 'curseforge':
                import launcher_app.resources.curseforge as curseforge
                return curseforge.list_mod_file_compatibility(hit['curseforge_id'])
            import launcher_app.resources.modrinth as modrinth
            return modrinth.list_mod_versions(slug, None, None, detailed=True)

        def done(result):
            current = getattr(self, '_current', None) or {}
            if generation != self._selection_generation or current.get('slug') != slug:
                return
            if result is None:
                self.compat_range_label.setText(t('兼容范围暂时无法读取'))
                return
            if source == 'curseforge':
                records = result.get('versions') or []
                partial = bool(result.get('partial'))
            else:
                records, partial = result, False
            summary, full = format_compatibility(records, partial=partial, source=source)
            self.compat_range_label.setText(summary)
            self.compat_range_label.setToolTip(full)

        key = ('ver', source, slug, None, None) if source != 'curseforge' else ('compat-range', slug)
        self._async(key, fetch, done, cache=source != 'curseforge')

    def _favorite_folder(self):
        import launcher_app.core.favorites as favs
        provider = getattr(self, 'favorite_folder', None)
        return (provider() if provider else None) or favs.DEFAULT_FOLDER

    def _fav_current(self):
        """收藏当前资源本体到默认收藏夹，不绑定任何指定版本。"""
        import launcher_app.core.favorites as favs
        folder = self._favorite_folder()
        h = getattr(self, "_current", None)
        if not h or not h.get("slug"):
            return
        slug = h["slug"]
        name = h.get("title") or slug
        d = favs.load()
        was_saved = favs.is_favorited(d, folder, slug)
        if was_saved:
            favs.remove(d, folder, slug)
        else:
            favs.add_reference(d, folder, h, self.project_type)
        favs.save(d)
        self._update_fav_btn()
        from PySide6.QtWidgets import QToolTip
        QToolTip.showText(self.fav_btn.mapToGlobal(self.fav_btn.rect().center()),
                          f"已取消收藏 {name}" if was_saved else f"已收藏 {name} → {folder}")
        self.favorite_changed.emit()

    def _fav_selected_version(self):
        """收藏当前下拉框选择的指定版本；它归属在同一个泛用收藏下。"""
        import launcher_app.core.favorites as favs
        folder = self._favorite_folder()
        h = getattr(self, "_current", None)
        if not h or not h.get("slug"):
            return
        version = (self.ver_combo.currentText() or "").strip()
        if not version:
            from PySide6.QtWidgets import QToolTip
            QToolTip.showText(self.fav_btn.mapToGlobal(self.fav_btn.rect().center()),
                              "请先在详情中选择一个具体文件版本")
            return
        slug = h["slug"]
        name = h.get("title") or slug
        data = favs.load()
        favs.add_reference(data, folder, h, self.project_type)
        added = favs.add_version(data, folder, slug, name, version)
        favs.save(data)
        self._update_fav_btn()
        from PySide6.QtWidgets import QToolTip
        QToolTip.showText(self.fav_btn.mapToGlobal(self.fav_btn.rect().center()),
                          "已收藏指定版本" if added else "该指定版本已经收藏")
        self.favorite_changed.emit()

    def _update_fav_btn(self):
        if not hasattr(self, "fav_btn"):
            return
        import launcher_app.core.favorites as favs
        folder = self._favorite_folder()
        h = getattr(self, "_current", None)
        slug = h.get("slug", "") if h else ""
        data = favs.load()
        if slug and favs.is_favorited(data, folder, slug):
            self.fav_btn.setText("★")
            self.fav_btn.setToolTip(t('取消收藏'))
        else:
            self.fav_btn.setText("☆")
            self.fav_btn.setToolTip(t('收藏资源'))
        version = (self.ver_combo.currentText() or "").strip()
        saved_versions = favs.versions(data, folder, slug) if slug else []
        self.fav_version_action.setText(t('✓ 已收藏该版本') if version and version in saved_versions else t('＋ 收藏当前版本'))

    def _start_desc_translation(self, h, *, manual=False):
        """自动显示缓存；用户点击后才后台生成当前资源的翻译。

        遵守 mod_translate 规则:
        - `ai_mod_translate` 关 → 直接显示原文(无翻译调用);
        - 本身已中文 / 空文本 → 原样;
        - 命中缓存 → 秒回(二次打开不再触发推理);
        - 引擎不可用 → 优雅显示原文 + 失败标注,不报错。
        结果只在当前选中的项目没变时才应用(避免快速切换时旧结果覆盖新选择)。"""
        self._desc_translation_generation = getattr(self, "_desc_translation_generation", 0) + 1
        self.desc_label.setText(h.get('description') or '')
        self.desc_original_heading.hide()
        self.desc_translation_heading.hide()
        self.desc_translation_label.clear()
        self.desc_translation_label.hide()
        generation = self._desc_translation_generation
        self.desc_translate_btn.setVisible(False)
        self.desc_translate_btn.setEnabled(True)
        self.desc_translate_btn.setText(t('生成翻译'))
        desc = (h.get("description") or "").strip()
        requested_slug = h.get("slug", "")
        if not desc:
            self.desc_note_label.setVisible(False)
            return
        if h.get("source") == "curseforge":
            # CurseForge 条款禁止缓存 API 数据；描述送去翻译会形成外部处理与
            # 本地翻译缓存，因此该来源只展示 API 返回的原文摘要。
            self.desc_note_label.setVisible(False)
            return
        try:
            import launcher_app.resources.mod_translate as mod_translate
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

        # 先查描述缓存(按 slug 键,跨版本复用;命中直接显示,不再推理)
        import launcher_app.ui.image_cache as image_cache
        self._desc_translation_cache_key = mod_translate.description_cache_key(requested_slug, desc)
        cached = image_cache.get_cached_desc(self._desc_translation_cache_key)
        if cached:
            cur0 = getattr(self, "_current", None)
            if cur0 and cur0.get("slug") == requested_slug:
                self._show_description_translation(cached)
                self.desc_note_label.setText(t("CACHED_TRANSLATION"))
                set_style(self.desc_note_label, lambda: f"color: {muted_color()}; font-size: 11px;")
                self.desc_note_label.setVisible(True)
            return

        # 未缓存的描述由用户主动生成，避免浏览资源时自动加载本地模型。
        self.desc_translate_btn.setVisible(True)
        if not manual:
            self.desc_note_label.setVisible(False)
            return
        self.desc_translate_btn.setEnabled(False)
        self.desc_translate_btn.setText(t('正在生成…'))
        self.desc_note_label.setText(t('正在准备模型并生成翻译，首次加载可能需要一些时间。'))
        set_style(self.desc_note_label, lambda: f"color: {muted_color()}; font-size: 11px;")
        self.desc_note_label.setVisible(True)

        def fetch():
            try:
                import launcher_app.resources.mod_translate as mod_translate
                return mod_translate.translate_text_safe(desc, slug=requested_slug, field="description")
            except Exception:
                return None

        def on_done(result):
            # 结果只在当前选中的项目仍等于本次请求时应用
            cur = getattr(self, "_current", None)
            if (not cur or cur.get("slug") != requested_slug
                    or generation != self._desc_translation_generation):
                return
            self.desc_translate_btn.setEnabled(True)
            self.desc_translate_btn.setText(t('重试翻译'))
            self._apply_translation(result)
            if isinstance(result, dict) and (result.get("translated") or result.get("source") in ("already_cn", "original")):
                self.desc_translate_btn.setVisible(False)
            if not result:
                self.desc_note_label.setText(t('翻译未完成，可以点击重试。'))
                self.desc_note_label.setVisible(True)

        # cache=False:让 mod_translate 每次重新读 enabled()/缓存,避免把"关闭时"的
        # 结果长期缓存到 _async_cache(否则用户之后打开开关也不生效)。
        self._async(("tr", requested_slug), fetch, on_done, cache=False)

    def _show_description_translation(self, text):
        original = (getattr(self, '_current', None) or {}).get('description') or ''
        self.desc_label.setText(original)
        if not text or text.strip() == original.strip():
            return
        self.desc_translation_label.setText(text)
        self.desc_original_heading.show()
        self.desc_translation_heading.show()
        self.desc_translation_label.show()

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
        if result.get("translated") and text and slug:
            try:
                import launcher_app.ui.image_cache as image_cache
                image_cache.set_cached_desc(getattr(self, '_desc_translation_cache_key', slug), text)
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
            from launcher_app.resources.mod_translate import translation_error_message
            reason = translation_error_message(result.get("error"))
            self.desc_note_label.setText(
                t("TRANSLATION_FAILED_SHOWING_ORIGINAL") + (t('\n原因：{v0}').format(v0=(reason)) if reason else ""))
            set_style(self.desc_note_label, lambda: f"color: {warning_color()}; font-size: 11px;")
            self.desc_note_label.setVisible(True)
            return
        if result.get("machine"):
            self._show_description_translation(text)
            note = t("MACHINE_TRANSLATION_SEE_ORIGINAL_FOR_ACCURACY")
            if result.get("confidence") == "low":
                note = t("MACHINE_TRANSLATION_LOW_CONFIDENCE_SEE_ORIGINAL")
            self.desc_note_label.setText(note)
            set_style(self.desc_note_label, lambda: f"color: {warning_color()}; font-size: 11px;")
            self.desc_note_label.setVisible(True)
            return
        # 兜底:显示原文
        self.desc_label.setText(text)
        self.desc_note_label.setVisible(False)

    # ---- 图标懒加载：可见行优先，限制并发，不积压离屏下载 ----
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
        """按当前视口重建待处理队列；离屏且未启动的请求直接丢弃。"""
        try:
            self._icon_queue.clear()
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
                self._icon_queue.append((item, slug, icon_url))
            self._pump_icon_queue()
        except Exception:
            pass

    def _pump_icon_queue(self):
        """有限并行下载；网络在线程中执行，图片只在 GUI 线程创建。"""
        visible = set(self._visible_rows())
        while self._icon_queue and self._icon_active < self._icon_concurrency:
            item, slug, url = self._icon_queue.popleft()
            row = self.result_list.row(item)
            if row not in visible or row in self._icon_loaded:
                continue
            h = item.data(Qt.ItemDataRole.UserRole) or {}
            self._icon_loaded[row] = True
            self._icon_active += 1
            generation = self._icon_generation

            def worker(hit=h, icon_url=url, icon_slug=slug):
                if hit.get("source") == "curseforge":
                    # 仅加载到当前卡片，不写入图标缓存。
                    import requests
                    response = requests.get(icon_url, timeout=12)
                    return response.content if response.status_code == 200 else None
                import launcher_app.ui.image_cache as image_cache
                return image_cache.load_icon(icon_slug, icon_url, size=48)

            self._async(("__icon__", generation, id(item), slug), worker,
                        lambda data, target=item, gen=generation:
                            self._end_icon((target, data, gen)), cache=False)

    def _end_icon(self, payload):
        """主线程:给条目设图标(成功才设),然后继续拉下一张。"""
        item, data, generation = payload
        self._icon_active -= 1
        if generation != self._icon_generation:
            self._pump_icon_queue()
            return
        icon = None
        if data:
            from PySide6.QtGui import QIcon, QPixmap
            pix = QPixmap()
            if pix.loadFromData(data):
                icon = QIcon(pix.scaled(
                    48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
        if icon is not None and item is not None:
            try:
                if item.listWidget() is not None:   # 条目可能已被清空/重建
                    item.setIcon(icon)
            except Exception:
                pass
        self._pump_icon_queue()

    def _refresh_versions(self):
        if not getattr(self, "_current", None):
            return
        self._version_generation += 1
        version_generation = self._version_generation
        current = dict(self._current)
        slug = current["slug"]
        generation = self._selection_generation
        # Detail filters are built from this resource's actual file declarations.
        gv, loader = None, None
        self.ver_combo.clear()
        self.ver_combo.addItem(t("LOADING"), None)
        self.ver_combo.setEnabled(False)
        self.dl_btn.setEnabled(False)
        self._refresh_download_warning()

        def fetch():
            if current.get("source") == "curseforge":
                import launcher_app.resources.curseforge as curseforge
                return curseforge.list_mod_files(current["curseforge_id"], gv or None,
                                                max_files=500, loader=None)
            import launcher_app.resources.modrinth as modrinth
            # Pack tags are useful guidance, but exact Minecraft and mod-loader
            # filters hide files that may work across several game versions.
            if self.project_type in FLEXIBLE_VERSION_TYPES:
                return modrinth.list_mod_versions(slug, None, None, detailed=True)
            # gv 为空 → 不按版本过滤,列该 mod 全部可用版本
            return modrinth.list_mod_versions(slug, gv or None, loader, detailed=True)

        def done(versions):
            selected = getattr(self, "_current", None) or {}
            if (generation != self._selection_generation
                    or version_generation != self._version_generation
                    or selected.get("slug") != slug):
                return
            self._fill_versions(versions)

        cache_gv = gv
        cache_loader = loader
        self._async(("ver", current.get("source", "modrinth"), slug, cache_gv, cache_loader), fetch,
                    done, cache=current.get("source") != "curseforge")

    def _fill_versions(self, versions, *, preserve_selection=False):
        self._loaded_versions = list(versions or [])
        records = [v for v in self._loaded_versions if isinstance(v, dict)]
        loaders = sorted({str(value).lower() for v in records for value in v.get('loaders', [])})
        mc_versions = {str(value) for v in records for value in v.get('game_versions', [])}
        import re
        def version_key(value):
            return tuple(int(part) for part in re.findall(r'\d+', value)), value
        mc_versions = sorted(mc_versions, key=version_key, reverse=True)
        for combo, values, preferred in (
                (self.file_loader_filter, loaders, self.loader_combo.currentData()),
                (self.file_mc_filter, mc_versions, self._current_gv())):
            previous = combo.currentData() if preserve_selection else preferred
            blocked = combo.blockSignals(True)
            combo.clear()
            combo.addItem(t('全部', 'All'), None)
            if (self.project_type == 'mod' and previous and previous not in values):
                # Keep a missing compatibility constraint: no files is safer than
                # silently falling back to every incompatible file.
                combo.addItem(str(previous), previous)
            for value in values:
                label = {'neoforge': 'NeoForge', 'liteloader': 'LiteLoader'}.get(value, value.title()) if combo is self.file_loader_filter else value
                combo.addItem(label, value)
            combo.setCurrentIndex(max(0, combo.findData(previous)))
            combo.blockSignals(blocked)
        self.file_loader_filter.setEnabled(bool(loaders))
        self._render_versions(preserve_selection=preserve_selection)

    def _render_versions(self, *, preserve_selection=False):
        """Filter actual file objects by declared loader and compatible MC version."""
        previous = self.ver_combo.currentData() if preserve_selection else None
        versions = list(self._loaded_versions or [])
        loader = self.file_loader_filter.currentData()
        mc_version = self.file_mc_filter.currentData()
        if loader:
            versions = [v for v in versions if isinstance(v, dict) and
                        loader in [str(value).lower() for value in v.get('loaders', [])]]
        if mc_version:
            versions = [v for v in versions if isinstance(v, dict) and mc_version in v.get('game_versions', [])]
        self.ver_combo.clear()
        if not versions:
            self.ver_combo.addItem(t("没有匹配的文件版本", "No matching file versions"), None)
            self.ver_combo.setEnabled(False)
            self.dl_btn.setEnabled(False)
            self._refresh_download_warning()
            return
        target_gv = ((self.selected_inst or {}).get('base')
                     if self.project_type in ('datapack', 'resourcepack') else None)
        if target_gv:
            # Exact declarations are convenient defaults, but every file stays
            # selectable because packs can work across undeclared game versions.
            versions = sorted(versions, key=lambda v: target_gv in (v.get('game_versions') or [])
                              if isinstance(v, dict) else False, reverse=True)
        for v in versions:
            if isinstance(v, dict):
                label = v.get("label") or v.get("filename") or "?"
                declared = bool(target_gv and target_gv in (v.get('game_versions') or []))
                if declared:
                    label = f"✓ {label} · 标注适配 {target_gv}"
                self.ver_combo.addItem(label, v)
                if v.get("game_versions") or v.get("loaders"):
                    support = " · ".join(filter(None, [
                        ", ".join(v.get("game_versions") or []),
                        ", ".join(v.get("loaders") or [])]))
                    if target_gv and not declared:
                        support += f"\n未标注 {target_gv}，仍可手动下载；请在游戏中确认效果。"
                    self.ver_combo.setItemData(self.ver_combo.count() - 1, support,
                                               Qt.ItemDataRole.ToolTipRole)
            else:
                self.ver_combo.addItem(v, v)
        self.ver_combo.setEnabled(True)
        selected_index = 0
        if previous is not None:
            for index in range(self.ver_combo.count()):
                if self.ver_combo.itemData(index) == previous:
                    selected_index = index
                    break
        self.ver_combo.setCurrentIndex(selected_index)
        self.dl_btn.setEnabled(True)
        self._refresh_compatibility_report()
        self._refresh_download_warning()

    def _refresh_download_warning(self, *_args):
        """Warn about a manually selected file without preventing its download."""
        if not hasattr(self, 'download_warning'):
            return
        version = self.ver_combo.currentData()
        inst = getattr(self, 'selected_inst', None)
        if not isinstance(version, dict):
            self.download_warning.hide()
            return
        show_all = (getattr(self, 'show_all_versions_btn', None) is not None and
                    self.show_all_versions_btn.isChecked())
        reasons = []
        game_versions = version.get('game_versions') or []
        loaders = [str(value).lower() for value in version.get('loaders') or []]
        base = (inst or {}).get('base') or (self._current_gv() if self.project_type == 'modpack' else None)
        loader = ((inst or {}).get('loader') or
                  (self.loader_combo.currentData() if self.project_type == 'modpack' else '') or '').lower()
        if base and game_versions and base not in game_versions:
            reasons.append(f"未标注适配 MC {base}")
        if self.project_type in ('mod', 'modpack') and loader and loader != 'vanilla' and loaders and loader not in loaders:
            reasons.append(f"未标注支持 {loader.title()}")
        if reasons:
            self.download_warning.setText(t('⚠ 可能不兼容：') + "，".join(reasons) + t('。仍可下载。'))
            self.download_warning.show()
        elif show_all and inst and self.project_type == 'mod' and (not game_versions or not loaders):
            self.download_warning.setText(t('⚠ 文件兼容标签不完整，可能不兼容；仍可下载。'))
            self.download_warning.show()
        elif show_all and not inst and self.project_type != 'modpack':
            self.download_warning.setText(t('⚠ 未选择目标实例，无法确认文件兼容性；仍可下载。'))
            self.download_warning.show()
        else:
            self.download_warning.hide()

    def _toggle_compat_detail(self):
        shown = not self.compat_detail.isVisible()
        self.compat_detail.setVisible(shown)
        self.compat_toggle.setText(t('收起依赖详情') if shown else t('查看依赖详情'))

    def _refresh_compatibility_report(self, *_args):
        """异步生成详情卡上的 Mod 兼容报告，不阻塞浏览或下载。"""
        if self.project_type != "mod" or not getattr(self, "_current", None):
            self.compat_box.setVisible(False)
            return
        if self._current.get("source") == "curseforge":
            self.compat_box.setVisible(True)
            self.compat_toggle.setVisible(False)
            self.compat_detail.setVisible(False)
            self.compat_summary.setText(
                t('CurseForge 文件兼容标签仅供参考；可在详情中调整加载器和兼容 MC 条件后选择下载。该来源暂不提供依赖图和自动前置下载。'))
            return
        version = self.ver_combo.currentData()
        gv = self._current_gv()
        loader = self.loader_combo.currentData()
        if not version:
            self.compat_box.setVisible(True)
            self.compat_summary.setText(t('选择一个具体 Mod 版本后，显示依赖与兼容报告。'))
            self.compat_detail.setVisible(False)
            self.compat_toggle.setVisible(False)
            return
        self.compat_box.setVisible(True)
        self.compat_toggle.setVisible(False)
        self.compat_detail.setVisible(False)
        self.compat_summary.setText(t('正在检查 Minecraft 版本、加载器与依赖…'))
        slug = self._current["slug"]
        target_dir = (os.path.join(self.get_instance_dir(self.selected_inst['id']), 'mods')
                      if self.selected_inst else self.custom_dir)
        version_label = version.get("version_number", "?") if isinstance(version, dict) else version
        version_key = (version.get("id") or version_label) if isinstance(version, dict) else version

        def fetch():
            import launcher_app.resources.modrinth as modrinth
            deps = modrinth.resolve_dependencies(slug, gv or None, loader or None, version)
            installed = modrinth.installed_mod_identifiers(target_dir) if target_dir else set()
            return deps, installed

        def done(result):
            cur = getattr(self, "_current", None)
            active_target = (os.path.join(self.get_instance_dir(self.selected_inst['id']), 'mods')
                             if self.selected_inst else self.custom_dir)
            if (not cur or cur.get("slug") != slug or self.ver_combo.currentData() != version
                    or active_target != target_dir):
                return
            from launcher_app.resources.modrinth import dependency_is_installed
            deps, installed = result
            deps = deps or {"required": [], "optional": [], "incompatible": []}
            required = [dep for dep in deps.get("required", [])
                        if not dependency_is_installed(dep, installed)]
            present = [dep for dep in deps.get("required", [])
                       if dependency_is_installed(dep, installed)]
            optional = deps.get("optional", [])
            incompatible = deps.get("incompatible", [])
            status = f"已选 Mod {version_label}；下方是该文件声明的依赖。"
            if incompatible:
                status += f"\n不建议同装 {len(incompatible)} 个已声明冲突项。"
            elif required:
                status += f"\n将自动加入 {len(required)} 个必需前置到同一下载任务。"
            elif present:
                status += "\n必需前置均已安装，可直接下载。"
            else:
                status += "\n未声明必需前置，可直接下载。"
            if optional:
                status += f"\n另有 {len(optional)} 个可选联动 Mod（不会自动下载）。"
            if present:
                status += f"\n已有 {len(present)} 个必需前置，将跳过下载。"
            self.compat_summary.setText(status)
            lines = []
            if required:
                lines.append("必需前置（确认下载后自动加入）：\n" + "\n".join("· " + d["title"] for d in required))
            if present:
                lines.append("已安装的必需前置（跳过）：\n" + "\n".join("· " + d["title"] for d in present))
            if optional:
                lines.append("可选联动（仅介绍，不自动下载）：\n" + "\n".join("· " + d["title"] for d in optional))
            if incompatible:
                lines.append("声明冲突：\n" + "\n".join("· " + d["title"] for d in incompatible))
            self.compat_detail.setText("\n\n".join(lines) or t('Modrinth 未为这个版本声明额外依赖或冲突。'))
            self.compat_toggle.setVisible(True)

        self._async(("compat", slug, gv, loader, version_key, target_dir), fetch, done)

    # ---- 下载 ----
    def _download(self):
        if getattr(self, '_search_pending', False) or not self.result_list.isEnabled():
            return
        if not getattr(self, "_current", None):
            return
        if self.is_modpack:
            # 整合包:下载 .mrpack → 导入成新实例(无需目标实例)
            if self.on_modpack_download:
                self.on_modpack_download(self._current, self.ver_combo.currentData())
            else:
                self.inst_cards_toggle.setChecked(True)
                self._toggle_cards()
                self.inst_cards_toggle.setText(t('▾ 整合包下载未接好(请联系开发者)'))
            return
        inst = self.selected_inst
        if inst is None and not self.custom_dir:
            self.inst_cards_toggle.setChecked(True)
            self._toggle_cards()
            self.inst_cards_toggle.setText(t('▾ 请先选目标实例(或选"无"手动选目录)'))
            return
        target = None
        if inst:
            instance_dir = self.get_instance_dir(inst["id"])
            if self.project_type == 'datapack':
                saves_dir = os.path.join(instance_dir, 'saves')
                try:
                    worlds = (sorted(name for name in os.listdir(saves_dir)
                                     if os.path.isfile(os.path.join(saves_dir, name, 'level.dat')))
                              if os.path.isdir(saves_dir) else [])
                except OSError:
                    worlds = []
                if not worlds:
                    self.inst_cards_toggle.setText(t('▾ 此实例还没有存档；先创建世界或选择手动目录'))
                    return
                world, accepted = QInputDialog.getItem(
                    self, t('选择数据包目标存档'), t('安装到哪个世界？'), worlds, 0, False)
                if not accepted or not world:
                    return
                target = os.path.join(saves_dir, world, 'datapacks')
            else:
                target = os.path.join(instance_dir, self.sub_dir)
        elif self.custom_dir:
            target = self.custom_dir
        self.on_download(self._current, self.ver_combo.currentData(),
                         inst, target, self.sub_dir)

    def get_instance_dir(self, instance_id: str) -> str:
        """实例游戏目录(由外层注入)"""
        return self._instance_dir(instance_id)

    def set_instance_dir_fn(self, fn):
        self._instance_dir = fn


class FavoriteBrowser(ResourceBrowser):
    """Reuse the resource list/detail/download layout; hydrate bookmarks on selection."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        layout = self.layout()
        def hide_item(item):
            if item.widget():
                item.widget().hide()
            elif item.layout():
                nested = item.layout()
                for index in range(nested.count()):
                    hide_item(nested.itemAt(index))
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not self.split:
                hide_item(item)
        layout.addWidget(self.split, 1)
        self._bookmark_generation = 0

    @staticmethod
    def resolve_bookmark(bookmark):
        reference = bookmark.get('_favorite_ref', {})
        source = reference.get('source') or bookmark.get('source', 'modrinth')
        if source == 'curseforge':
            import launcher_app.resources.curseforge as curseforge
            project_id = reference.get('project_id') or bookmark['slug'].removeprefix('curseforge-')
            hit = curseforge.get_mod(int(project_id))
        else:
            import launcher_app.resources.modrinth as modrinth
            hit = dict(modrinth.get_project(reference.get('project_id') or bookmark['slug']), source='modrinth')
        return dict(hit, _favorite_ref=reference, _favorite_loaded=True)

    def _on_selected(self, current, previous):
        self._bookmark_generation = getattr(self, '_bookmark_generation', 0) + 1
        generation = self._bookmark_generation
        if current is None:
            return super()._on_selected(current, previous)
        bookmark = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(bookmark, dict):
            return super()._on_selected(None, previous)
        reference = bookmark.get('_favorite_ref', {})
        source = reference.get('source') or bookmark.get('source', 'modrinth')
        slug = bookmark['slug']
        self._current = None
        self.download_section.hide()
        self.title_label.setText(bookmark.get('title', slug))
        self.title_label.show()
        for widget in (self.meta_label, self.desc_label, self.compat_range_label, self.compat_box,
                       self.mcmod_link, self.desc_translation_label, self.desc_translate_btn):
            widget.hide()
        self.empty_label.setText(t('正在从来源平台读取资源…'))
        self.empty_label.show()
        def fetch():
            return self.resolve_bookmark(bookmark)
        def done(hit):
            if generation != self._bookmark_generation or self.result_list.currentItem() is not current:
                return
            if not hit:
                self.empty_label.setText(t('暂时无法读取资源。检查网络或 API 设置后重新选择；收藏标记仍保留。'))
                url = reference.get('url')
                if url and urllib.parse.urlparse(url).scheme in ('http', 'https'):
                    from html import escape
                    self.mcmod_link.setText(t('<a href="{v0}">打开收藏的资源页面</a>').format(v0=(escape(url, quote=True))))
                    self.mcmod_link.show()
                return
            kind = hit.get('project_type') or reference.get('resource_type') or 'mod'
            if kind not in ('mod', 'modpack', 'shader', 'datapack', 'resourcepack'):
                self.empty_label.setText(t('此收藏的资源类型暂不支持下载。'))
                return
            self.project_type = kind
            self.sub_dir = {'mod': 'mods', 'shader': 'shaderpacks', 'datapack': 'datapacks',
                            'resourcepack': 'resourcepacks', 'modpack': ''}[kind]
            self.is_modpack = kind == 'modpack'
            self.inst_cards_toggle.setVisible(not self.is_modpack)
            hit['_favorite_ref'] = reference
            current.setData(Qt.ItemDataRole.UserRole, hit)
            current.setText(hit.get('title', slug) + '\n' + hit.get('description', '')[:60])
            self._icon_loaded.pop(self.result_list.row(current), None)
            self._icon_visibility_timer.start(80)
            super(FavoriteBrowser, self)._on_selected(current, previous)
        if bookmark.get('_favorite_loaded'):
            done(bookmark)
        else:
            self._async(('favorite-project', source, slug, generation), fetch, done, cache=False)


class _FavFolderList(QListWidget):
    """收藏夹列表:接受从收藏卡片拖来的内容,落到哪个文件夹就复制到哪。"""

    def __init__(self, owner):
        super().__init__()
        self._owner = owner
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat("application/x-amcl-favorite"):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat("application/x-amcl-favorite"):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasFormat("application/x-amcl-favorite"):
            slug = bytes(e.mimeData().data("application/x-amcl-favorite")).decode()
            folder = self.itemAt(e.position().toPoint())
            if folder is not None and self._owner is not None:
                self._owner._on_fav_dropped(slug, folder.text())
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


class _FavCard(QPushButton):
    """收藏卡片:按住可拖出,拖到其它收藏夹 = 复制。"""

    def __init__(self, text: str, slug: str):
        super().__init__(text)
        self._slug = slug
        self._press = None
        self.setMinimumSize(160, 72)
        from launcher_app.ui.ui_style import card_btn_style, set_style
        set_style(self, card_btn_style)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.pos()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            if (e.pos() - self._press).manhattanLength() > 8:
                from PySide6.QtCore import QMimeData
                from PySide6.QtGui import QDrag
                drag = QDrag(self)
                mime = QMimeData()
                mime.setData("application/x-amcl-favorite", self._slug.encode())
                drag.setMimeData(mime)
                drag.exec_(Qt.DropAction.CopyAction)
                self._press = None
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press = None
        super().mouseReleaseEvent(e)


class _FavGroupCard(QWidget):
    """一个泛用收藏及其可展开的指定版本；版本不再伪装成独立 Mod 收藏。"""

    def __init__(self, name: str, slug: str, versions: list[str], on_menu, on_remove_version):
        super().__init__()
        self.setMinimumWidth(180)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.card = _FavCard(name, slug)
        self.card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.card.customContextMenuRequested.connect(lambda _p: on_menu(slug))
        layout.addWidget(self.card)

        self.versions_box = QWidget()
        versions_layout = QVBoxLayout(self.versions_box)
        versions_layout.setContentsMargins(8, 0, 0, 0)
        versions_layout.setSpacing(3)
        self.toggle = QToolButton()
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setText(t('指定版本（{v0}）').format(v0=(len(versions))))
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self._toggle_versions)
        if versions:
            layout.addWidget(self.toggle)
            for version in versions:
                version_btn = QPushButton(version)
                version_btn.setMinimumHeight(28)
                set_style(version_btn, card_btn_style)
                version_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                version_btn.customContextMenuRequested.connect(
                    lambda _p, v=version: on_remove_version(slug, v))
                version_btn.setToolTip(t('右键可取消收藏这个指定版本'))
                versions_layout.addWidget(version_btn)
            self.versions_box.setVisible(False)
            layout.addWidget(self.versions_box)

    def _toggle_versions(self, open_: bool):
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow)
        self.versions_box.setVisible(open_)
        self.updateGeometry()


class ResourceCenter(QWidget):
    """下载新资源:左侧可折叠菜单 + 右侧分类面板(首页/实例/Mod/光影/数据包/资源包)。"""

    def __init__(self, parent=None, *, auto_load_versions: bool = True):
        super().__init__(parent)
        self._instance_dir = lambda iid: iid
        self._on_download_cb = None
        self._get_inst_loader = lambda inst: inst.get("loader")

        # 全局目标实例(四个分类页共享)
        self._shared_inst = None
        self._shared_dir = None

        # ---- 左侧菜单(独立模块 LeftMenu,无折叠) ----
        # 图标用内置单色 SVG + 主题色(theme_icon),跟随深浅色/自定义主题;不再是 emoji。
        from launcher_app.ui.left_menu import LeftMenu
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
        from launcher_app.resources.download_tab import DownloadTab
        self.download_tab = DownloadTab(auto_load_versions=auto_load_versions)
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

        # 收藏只保存书签，项目详情按需从原平台读取。
        self.stack.addWidget(self._build_favorites())   # 7
        for browser in self.browsers.values():
            browser.favorite_changed.connect(self._reload_favorites)

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
        for br in [*self.browsers.values(), self.favorite_browser]:
            br._sync_target_ui()

    # ---- 菜单 ----
    def switch_to(self, idx: int):
        previous = self.stack.currentIndex()
        self.stack.setCurrentIndex(idx)
        if previous != idx:
            from launcher_app.ui.ui_anim import reveal
            reveal(self.stack.currentWidget())
        if idx == 7 and previous != idx:
            self._reload_favorites()
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
        set_style(self.home_latest, lambda: f"font-weight: bold; font-size: 15px; color: {text_color()};")
        self.home_hint = QLabel(
            t("TIP_THE_NEWEST_MC_VERSION_USUALLY_HAS_POOR_MOD_SUPPORT_PREFER_ACTIVE_VERSIONS_LIKE_1_21_1_1_20_1"))
        self.home_hint.setWordWrap(True)
        set_style(self.home_hint, hint_style)
        layout.addWidget(self.home_latest)
        layout.addWidget(self.home_hint)
        layout.addSpacing(14)
        cards = FlowLayout(hspacing=12, vspacing=12)
        from launcher_app.ui.theme_icon import theme_icon
        from PySide6.QtCore import QSize
        entries = [
            (t("CREATE_INSTANCE"), 1, "instances"),
            (t("MODPACKS"), 2, "modpack"),
            (t("MODS"), 3, "mod"),
            (t("SHADERS"), 4, "shader"),
            (t("DATAPACKS"), 5, "datapack"),
            (t("RESOURCEPACKS"), 6, "resourcepack"),
            (t("LAUNCHER_PLUGINS"), 7, "utility"),
        ]
        for text, idx, icon in entries:
            desc = _CATEGORY_DESC.get(icon, "")
            label = f"{text}\n{desc}" if desc else text
            b = QPushButton(label)
            b.setMinimumSize(150, 96)   # 高一点的分类卡片;放不下时自动换行
            b.setIcon(theme_icon(icon, 30))
            b.setIconSize(QSize(30, 30))
            set_style(b, card_btn_style)
            b.clicked.connect(lambda _c, i=idx: self.switch_to(i))
            cards.addWidget(b)
        layout.addLayout(cards)
        layout.addStretch()
        return home

    def _build_favorites(self) -> QWidget:
        import launcher_app.core.favorites as favs
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(QLabel(t('收藏夹')))
        self._fav_folder_combo = QComboBox()
        set_style(self._fav_folder_combo, resource_control_style)
        self._fav_folder_combo.setFixedHeight(36)
        toolbar.addWidget(self._fav_folder_combo, 1)
        self._fav_type_combo = QComboBox()
        for label, kind in [('全部资源', None), ('Mod', 'mod'), ('整合包', 'modpack'),
                            ('光影', 'shader'), ('数据包', 'datapack'), ('资源包', 'resourcepack'), ('未分类', 'unknown')]:
            self._fav_type_combo.addItem(label, kind)
        self._fav_type_combo.setFixedHeight(36)
        set_style(self._fav_type_combo, resource_control_style)
        self._fav_type_combo.currentIndexChanged.connect(self._filter_favorite_items)
        toolbar.addWidget(self._fav_type_combo)
        self._favorite_metadata = {}
        self._favorite_load_generation = 0
        self._fav_folder_list = _FavFolderList(self)
        self._fav_folder_list.hide()
        self._fav_folder_list.currentRowChanged.connect(self._on_fav_folder_changed)
        self._fav_folder_combo.currentIndexChanged.connect(self._fav_folder_list.setCurrentRow)
        for text, callback in (('新建', self._on_fav_add_folder), ('删除收藏夹', self._on_fav_del_folder)):
            button = QPushButton(text)
            button.setFixedHeight(36)
            set_style(button, resource_control_style)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        outer.addLayout(toolbar)
        self.favorite_browser = FavoriteBrowser('mod', '收藏', 'mods',
                on_download=self._browser_download, get_instance_loader=self._get_inst_loader)
        self.favorite_browser.on_modpack_download = self._on_modpack_download
        self.favorite_browser.set_instance_dir_fn(self._instance_dir)
        self.favorite_browser._set_target_hooks(self._get_shared_target, self._set_shared_target)
        self.favorite_browser.favorite_folder = self._current_fav_folder
        self.favorite_browser.favorite_changed.connect(self._reload_favorites)
        self.favorite_browser.result_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        def menu_at(position):
            item = self.favorite_browser.result_list.itemAt(position)
            hit = item.data(Qt.ItemDataRole.UserRole) if item else None
            if isinstance(hit, dict):
                self._fav_card_menu(hit['slug'])
        self.favorite_browser.result_list.customContextMenuRequested.connect(menu_at)
        outer.addWidget(self.favorite_browser, 1)
        self._fav_data = favs.load()
        self._refresh_fav_folders()
        return page

    # ---- 收藏页操作 ----
    def _refresh_fav_folders(self, preferred=None):
        self._fav_folder_list.blockSignals(True)
        self._fav_folder_combo.blockSignals(True)
        self._fav_folder_combo.clear()
        self._fav_folder_list.clear()
        import launcher_app.core.favorites as favs
        for f in favs.folders(self._fav_data):
            self._fav_folder_list.addItem(f)
            self._fav_folder_combo.addItem(f)
        self._fav_folder_list.blockSignals(False)
        self._fav_folder_combo.blockSignals(False)
        if self._fav_folder_list.count():
            row = self._fav_folder_combo.findText(preferred) if preferred else 0
            self._fav_folder_list.setCurrentRow(max(0, row))
        else:
            self._on_fav_folder_changed()

    def _reload_favorites(self):
        """从磁盘重读收藏；资源详情刚收藏后和切回收藏页时都会刷新。"""
        import launcher_app.core.favorites as favs
        self._favorite_metadata.clear()
        current = self._current_fav_folder() if hasattr(self, "_fav_folder_list") else None
        self._fav_data = favs.load()
        self._refresh_fav_folders(current)

    def _on_fav_folder_changed(self, _row=-1):
        row = self._fav_folder_list.currentRow()
        self._fav_folder_combo.setCurrentIndex(row)
        folder = self._fav_folder_list.item(row).text() if row >= 0 else None
        self._refresh_fav_cards(folder)

    def _refresh_fav_cards(self, folder):
        import launcher_app.core.favorites as favs
        hits = []
        for slug, entry in favs.items(self._fav_data, folder).items() if folder else []:
            source = entry.get('source') or ('curseforge' if slug.startswith('curseforge-') else 'modrinth')
            hits.append({'slug': slug, 'source': source, 'title': entry.get('name') or slug,
                         'description': '选择后从来源平台读取详情', '_favorite_ref': dict(entry, source=source)})
        self._favorite_hits = hits
        self._filter_favorite_items()
        self._favorite_load_generation += 1
        generation = self._favorite_load_generation
        if self.stack.currentIndex() != 7:
            return
        pending = [hit for hit in hits if hit['slug'] not in self._favorite_metadata]
        if not pending:
            return
        def fetch():
            from concurrent.futures import ThreadPoolExecutor
            from launcher_app.core.task_context import submit
            def one(bookmark):
                try:
                    return bookmark['slug'], FavoriteBrowser.resolve_bookmark(bookmark)
                except Exception:
                    return bookmark['slug'], None
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [submit(pool, one, hit) for hit in pending]
                return dict(future.result() for future in futures)
        def done(results):
            if generation != self._favorite_load_generation or self._current_fav_folder() != folder:
                return
            self._favorite_metadata.update({slug: hit for slug, hit in (results or {}).items() if hit})
            self._filter_favorite_items()
        self.favorite_browser._async(('favorite-list', generation, folder), fetch, done, cache=False)

    def _filter_favorite_items(self, *_args):
        kind = self._fav_type_combo.currentData()
        hits = []
        for bookmark in getattr(self, '_favorite_hits', []):
            hit = dict(self._favorite_metadata.get(bookmark['slug']) or bookmark)
            # Folder-specific saved versions/labels remain separate from live project metadata.
            hit['_favorite_ref'] = bookmark['_favorite_ref']
            actual_type = hit.get('project_type') or hit['_favorite_ref'].get('resource_type') or 'unknown'
            if kind is None or kind == actual_type:
                hits.append(hit)
        current = self.favorite_browser.result_list.currentItem()
        selected = (current.data(Qt.ItemDataRole.UserRole) or {}).get('slug') if current else None
        self.favorite_browser._fill_results(hits)
        self.favorite_browser._no_more = True
        for row, hit in enumerate(hits):
            if hit['slug'] == selected:
                self.favorite_browser.result_list.setCurrentRow(row)
                break

    def _fav_card_menu(self, slug):
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QCursor
        menu = QMenu(self)
        menu.setStyleSheet(popup_menu_style())
        act_remove = menu.addAction(t('从收藏夹移除'))
        cur = self._fav_folder_list.currentItem().text() if self._fav_folder_list.currentItem() else None
        reference = (self._fav_data.get(cur) or {}).get(slug) or {}
        if reference.get('versions'):
            version_menu = menu.addMenu('移除指定版本收藏')
            for version in reference['versions']:
                version_menu.addAction(version, lambda checked=False, value=version: self._remove_fav_version(slug, value))
        copy_menu = menu.addMenu("复制到 →")
        import launcher_app.core.favorites as favs
        for f in favs.folders(self._fav_data):
            if f == cur:
                continue
            copy_menu.addAction(f, lambda _c=False, ff=f: self._copy_fav(slug, ff))
        chosen = menu.exec_(QCursor.pos())
        if chosen == act_remove:
            self._remove_fav(slug)

    def _current_fav_folder(self):
        return self._fav_folder_list.currentItem().text() if self._fav_folder_list.currentItem() else None

    def _copy_fav(self, slug, to_folder):
        import launcher_app.core.favorites as favs
        cur = self._current_fav_folder()
        if cur and favs.copy(self._fav_data, cur, to_folder, slug):
            favs.save(self._fav_data)
            self._refresh_fav_cards(cur)

    def _remove_fav(self, slug):
        import launcher_app.core.favorites as favs
        cur = self._current_fav_folder()
        if cur:
            favs.remove(self._fav_data, cur, slug)
            favs.save(self._fav_data)
            self._refresh_fav_cards(cur)

    def _remove_fav_version(self, slug, version):
        """右键指定版本 → 只移除该版本，泛用收藏本体继续保留。"""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QCursor
        menu = QMenu(self)
        menu.setStyleSheet(popup_menu_style())
        remove_action = menu.addAction(t('取消收藏版本「{v0}」').format(v0=(version)))
        if menu.exec_(QCursor.pos()) != remove_action:
            return
        import launcher_app.core.favorites as favs
        folder = self._current_fav_folder()
        entry = favs.get(self._fav_data, folder, slug) if folder else None
        if entry and version in entry.get("versions", []):
            entry["versions"].remove(version)
            favs.save(self._fav_data)
            self._refresh_fav_cards(folder)

    def _on_fav_dropped(self, slug, to_folder):
        """收藏卡片拖到某文件夹 → 跨夹复制。"""
        import launcher_app.core.favorites as favs
        cur = self._current_fav_folder()
        if cur and cur != to_folder and favs.copy(self._fav_data, cur, to_folder, slug):
            favs.save(self._fav_data)
            self._refresh_fav_cards(cur)

    def _on_fav_add_folder(self):
        from PySide6.QtWidgets import QInputDialog
        import launcher_app.core.favorites as favs
        text, ok = QInputDialog.getText(self, t('新建收藏夹'), t('收藏夹名称:'))
        text = text.strip()
        if ok and text and text not in self._fav_data:
            self._fav_data[text] = {}
            favs.save(self._fav_data)
            self._refresh_fav_folders()

    def _on_fav_del_folder(self):
        import launcher_app.core.favorites as favs
        cur = self._fav_folder_list.currentItem()
        if cur is None:
            return
        folder = cur.text()
        if folder == favs.DEFAULT_FOLDER:
            inline_notice(self, t('删除收藏夹'), t('默认收藏夹不能删除'))
            return
        if action_question(self, t('删除收藏夹'), t('删除收藏夹「{v0}」?').format(v0=(folder)), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes) == QMessageBox.StandardButton.Yes:
            self._fav_data.pop(folder, None)
            favs.save(self._fav_data)
            self._refresh_fav_folders()

    def _build_plugins_placeholder(self) -> QWidget:
        """启动器插件商店:手动注册仓库源 → 列出仓库里的插件 → 一键安装单文件。
        参考 DSH「仓库即商店」:你的官方插件放你项目仓库(如 GitHub),用户添加该仓库 URL 即可装。"""
        import launcher_app.extensions.plugin_manager as plugin_manager
        page = QWidget()
        page.setObjectName("plugins_page")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(8)

        title = QLabel(t('🧩 启动器插件商店'))
        set_style(title, lambda: f"font-weight: bold; font-size: 16px; color: {text_color()};")
        outer.addWidget(title)
        note = QLabel(t('浏览官方插件，或粘贴分享码查找插件。安装后到设置 → 插件启用。'))
        note.setWordWrap(True); set_style(note, hint_style)
        outer.addWidget(note)
        share_row = QHBoxLayout()
        self._plugin_share_edit = QLineEdit()
        self._plugin_share_edit.setPlaceholderText(t('粘贴 AMCL 插件分享码'))
        share_row.addWidget(self._plugin_share_edit, 1)
        share_import = QPushButton(t('解析分享码'))
        set_style(share_import, card_btn_style)
        share_import.clicked.connect(self._import_plugin_share)
        share_row.addWidget(share_import)
        outer.addLayout(share_row)
        advanced = QWidget()
        registry_layout = QVBoxLayout(advanced)
        registry_layout.setContentsMargins(0, 0, 0, 0)
        advanced.hide()

        # ---- 仓库源管理 ----
        reg_title = QLabel(t('仓库源:'))
        set_style(reg_title, lambda: f"font-weight: bold; color: {muted_color()};")
        registry_layout.addWidget(reg_title)
        self._registry_list = QListWidget(); self._registry_list.setMaximumHeight(80)
        registry_layout.addWidget(self._registry_list)
        reg_row = QHBoxLayout()
        self._registry_edit = QLineEdit()
        self._registry_edit.setPlaceholderText(t('仓库 plugins.json 地址,如 https://raw.githubusercontent.com/…/plugins.json'))
        reg_row.addWidget(self._registry_edit, 1)
        add_reg = QPushButton(t('添加仓库')); set_style(add_reg, card_btn_style); add_reg.setMinimumHeight(30)
        add_reg.clicked.connect(self._add_registry)
        del_reg = QPushButton(t('删除选中')); set_style(del_reg, card_btn_style); del_reg.setMinimumHeight(30)
        del_reg.clicked.connect(self._del_registry)
        reg_row.addWidget(add_reg); reg_row.addWidget(del_reg)
        registry_layout.addLayout(reg_row)
        outer.addWidget(advanced)

        # ---- 仓库里的插件(汇总) ----
        remote_title = QLabel(t('仓库里的插件:'))
        set_style(remote_title, lambda: f"font-weight: bold; color: {muted_color()};")
        outer.addWidget(remote_title)
        self._plugin_store_list = QListWidget()
        self._plugin_store_list.setWordWrap(True)
        set_style(self._plugin_store_list, list_style)
        outer.addWidget(self._plugin_store_list, 1)
        btn_row = QHBoxLayout()
        refresh_btn = QPushButton(t('刷新插件列表')); set_style(refresh_btn, card_btn_style); refresh_btn.setMinimumHeight(32)
        refresh_btn.clicked.connect(self._refresh_store)
        install_btn = QPushButton(t('安装选中插件')); set_style(install_btn, card_btn_style); install_btn.setMinimumHeight(32)
        install_btn.clicked.connect(self._install_store_plugin)
        self._plugin_install_button = install_btn
        btn_row.addWidget(refresh_btn); btn_row.addWidget(install_btn)
        copy_share = QPushButton(t('复制分享码'))
        self._plugin_copy_share_button = copy_share
        set_style(copy_share, card_btn_style)
        copy_share.clicked.connect(self._copy_plugin_share)
        btn_row.addWidget(copy_share)
        outer.addLayout(btn_row)

        open_btn = QPushButton(t("OPEN_PLUGIN_MANAGER"))
        set_style(open_btn, card_btn_style); open_btn.setMinimumHeight(34)
        open_btn.clicked.connect(self._open_plugin_settings)
        outer.addWidget(open_btn)
        advanced_row = QHBoxLayout()
        advanced_row.addStretch()
        advanced_toggle = QPushButton(t('高级：仓库源'))
        advanced_toggle.setCheckable(True)
        set_style(advanced_toggle, card_btn_style)
        advanced_toggle.toggled.connect(advanced.setVisible)
        advanced_row.addWidget(advanced_toggle)
        outer.addLayout(advanced_row)
        self._refresh_store()
        return page

    def _copy_plugin_share(self):
        import launcher_app.extensions.plugin_manager as plugin_manager
        selected = self._plugin_store_list.currentItem()
        entry = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        if not entry:
            inline_notice(self, t('分享插件'), t('请先选择一个插件。'))
            return
        registry = entry.get('_registry_url')
        if not registry:
            inline_warning(self, t('分享插件'), t('没有找到该插件的清单来源，请刷新列表。'))
            return
        from launcher_app.ui.ui_feedback import copy_with_feedback
        copy_with_feedback(self._plugin_copy_share_button, plugin_manager.make_plugin_share_code(
            registry, entry['name'], entry.get('category')))
        self._plugin_share_edit.setPlaceholderText(t('分享码已复制'))

    def _import_plugin_share(self):
        import launcher_app.extensions.plugin_manager as plugin_manager
        try:
            locator = plugin_manager.parse_plugin_share_code(self._plugin_share_edit.text())
        except ValueError as error:
            task_warning(self, t('插件分享码'), str(error))
            return
        previous = getattr(self, '_plugin_share_task', None)
        if previous is not None and previous.is_running:
            return
        self._plugin_share_edit.setEnabled(False)
        task = BackgroundTask(lambda current: plugin_manager.load_registry(locator['registry']), self)
        self._plugin_share_task = task

        def loaded(rows):
            self._plugin_share_edit.setEnabled(True)
            entry = next((row for row in rows if row['name'] == locator['plugin']), None)
            if entry is None:
                task_warning(self, t('插件分享码'), t('清单不可访问，或没有找到这个插件。'))
                return
            entry = dict(entry, _registry_url=locator['registry'])
            category = plugin_manager.plugin_category(entry['name'], entry.get('category') or locator['category'])
            self._plugin_store_list.clear()
            item = QListWidgetItem(f"{entry.get('title') or entry['name']} · {category}\n来源：{locator['registry']}\n{entry.get('description', '')}")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._plugin_store_list.addItem(item)
            self._plugin_store_list.setCurrentItem(item)

        def failed(error):
            self._plugin_share_edit.setEnabled(True)
            task_warning(self, t('插件分享码'), str(error))

        task.succeeded.connect(loaded)
        task.failed.connect(failed)
        task.start()

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
        import launcher_app.extensions.plugin_manager as plugin_manager
        regs = self._registries()
        self._registry_list.clear()
        for r in regs:
            self._registry_list.addItem(r.get("url", ""))
        # 拉取汇总
        merged = plugin_manager.list_remote_plugins(regs) if regs else {}
        self._plugin_store_list.clear()
        if not regs:
            self._plugin_store_list.addItem(t('还没有仓库源,请先在上面添加一个仓库 URL。'))
            return
        for name, e in sorted(merged.items()):
            title = e.get("title") or name
            ver = e.get("version") or ""
            desc = (e.get("description") or "")[:60]
            repo = (e.get("repo") or "").split("/")[-1]
            category = plugin_manager.plugin_category(name, e.get('category'))
            item = QListWidgetItem(f"{title} ({ver}) · {category}   [{repo}]\n{desc}")
            item.setData(Qt.ItemDataRole.UserRole, e)
            self._plugin_store_list.addItem(item)
        if not merged:
            self._plugin_store_list.addItem(t('(仓库里没有可安装的插件,或拉取失败)'))

    def _install_store_plugin(self):
        """安装选中的仓库插件(单文件下载+落盘)。"""
        import launcher_app.extensions.plugin_manager as plugin_manager
        cur = self._plugin_store_list.currentItem()
        if cur is None:
            task_notice(self, t('安装插件'), t('请先选择一个插件。'))
            return
        entry = cur.data(Qt.ItemDataRole.UserRole) or {}
        if not entry.get('name'):
            task_notice(self, t('安装插件'), t('当前条目不是可安装的插件，请刷新列表后选择插件。'))
            return
        current_task = getattr(self, '_plugin_install_task', None)
        if current_task is not None and current_task.is_running:
            return
        from launcher_app.core.background_tasks import BackgroundTask
        button = self._plugin_install_button
        button.setEnabled(False)
        button.setText(t('正在下载安装…'))
        owner = self.window()
        while owner is not None and not hasattr(owner, 'report_download_done'):
            owner = owner.parentWidget()
        title = '插件：' + str(entry.get('title') or entry['name'])
        if owner is not None:
            owner.report_download_progress(title, f"正在下载插件 {entry.get('title') or entry['name']}…", 0, 1)
        task = BackgroundTask(lambda current: plugin_manager.install_remote_plugin(dict(entry)), self)
        self._plugin_install_task = task

        def finish(result):
            button.setEnabled(True)
            button.setText(t('安装选中插件'))
            if result.get('ok'):
                message = f"已安装插件 {result.get('name', '')}：{result.get('path', '')}\n重启启动器后生效，可到设置 → 插件启用。"
            else:
                message = f"插件安装失败：{result.get('error', '未知')}"
            if owner is not None:
                owner.report_download_done(title, bool(result.get('ok')), message)
                owner.statusBar().showMessage('插件安装完成，重启后生效' if result.get('ok') else '插件安装失败，点击下载指示器查看日志', 8000)
            elif result.get('ok'):
                task_notice(self, t('安装插件'), message)
            else:
                task_warning(self, t('安装插件'), message)

        task.succeeded.connect(finish)
        task.failed.connect(lambda error: finish({'ok': False, 'error': error}))
        task.start()

    def _open_plugin_settings(self):
        """打开 设置(切到插件页)。"""
        win = self.window()
        while win is not None and not callable(getattr(win, 'open_settings', None)):
            win = win.parentWidget()
        if win is not None:
            win.open_settings()
            win.settings_center.shell.switch_by_label(t('PLUGINS'))
        else:
            inline_warning(self, t('插件管理'), t('无法打开设置，请从标题栏进入设置 → 插件。'))

    def set_ui_mode(self, mode: str):
        """界面模式(对外叫「全面 / 摘要」,内部 beginner/expert 兼容旧配置):
        全面(beginner)= 显示科普/提示;摘要(expert)= 隐藏科普、精简提示。
        ⚠️ 规范:以后新增界面提示/科普,都要来这里按模式做显隐(见 docs/archive/项目规划.md 界面规范)。
        """
        self._ui_mode = "expert" if str(mode or "") in ("expert", "summary") else "beginner"
        full = self._ui_mode != "expert"
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
        for br in [*self.browsers.values(), self.favorite_browser]:
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
        for br in [*self.browsers.values(), self.favorite_browser]:
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


# ===================== Merged from resource_compatibility.py =====================
"""Display declared Minecraft versions per loader from resource file records."""

import re


LOADER_NAMES = {
    'forge': 'Forge', 'neoforge': 'NeoForge', 'fabric': 'Fabric',
    'quilt': 'Quilt', 'iris': 'Iris', 'optifine': 'OptiFine',
    'minecraft': '原版', 'vanilla': '原版', 'datapack': '数据包',
    'resourcepack': '资源包',
}
_PREFERRED = ('forge', 'neoforge', 'fabric')


def _version_key(version: str):
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.split(r'(\d+)', version))


def format_compatibility(versions: list[dict], *, partial: bool = False,
                         source: str = 'modrinth') -> tuple[str, str]:
    """Return compact detail text and a tooltip with all declared versions.

    Endpoints are shown only with a count; they never imply all intermediate
    Minecraft versions work. Source data is the version/file record, not the
    project's independent loader and game-version unions.
    """
    groups: dict[str, set[str]] = {}
    for item in versions or []:
        if not isinstance(item, dict):
            continue
        game_versions = {str(value).strip() for value in item.get('game_versions') or []
                         if str(value).strip()}
        if not game_versions:
            continue
        loaders = item.get('loaders') or ['未注明加载器']
        for loader in loaders:
            key = str(loader).strip().lower() or '未注明加载器'
            groups.setdefault(key, set()).update(game_versions)

    if not groups:
        return '兼容范围：没有找到文件级版本声明', ''

    keys = [key for key in _PREFERRED if key in groups]
    keys.extend(sorted(key for key in groups if key not in _PREFERRED))
    lines = ['兼容范围 · 部分可能不支持']
    full = ['各文件声明的游戏版本（不是连续区间）：']
    for key in keys:
        label = LOADER_NAMES.get(key, key if key == '未注明加载器' else key.title())
        values = sorted(groups[key], key=_version_key, reverse=True)
        if len(values) <= 7:
            display = '、'.join(values)
        else:
            display = f'{values[0]} ～ {values[-1]}（共 {len(values)} 个）'
        lines.append(f'{label}：{display}')
        full.append(f'{label}：' + '、'.join(values))
    if partial:
        note = 'CurseForge 文件较多，仅统计已读取的最近文件；更早版本可能未显示。'
        lines.append(note)
        full.append(note)
    elif source == 'curseforge':
        lines.append('依据 CurseForge 文件标签，未标注的兼容性不作推断。')
    return '\n'.join(lines), '\n'.join(full)


# ===================== Merged from resource_compatibility.py =====================
"""Display declared Minecraft versions per loader from resource file records."""

import re


LOADER_NAMES = {
    'forge': 'Forge', 'neoforge': 'NeoForge', 'fabric': 'Fabric',
    'quilt': 'Quilt', 'iris': 'Iris', 'optifine': 'OptiFine',
    'minecraft': '原版', 'vanilla': '原版', 'datapack': '数据包',
    'resourcepack': '资源包',
}
_PREFERRED = ('forge', 'neoforge', 'fabric')


def _version_key(version: str):
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.split(r'(\d+)', version))


def format_compatibility(versions: list[dict], *, partial: bool = False,
                         source: str = 'modrinth') -> tuple[str, str]:
    """Return compact detail text and a tooltip with all declared versions.

    Endpoints are shown only with a count; they never imply all intermediate
    Minecraft versions work. Source data is the version/file record, not the
    project's independent loader and game-version unions.
    """
    groups: dict[str, set[str]] = {}
    for item in versions or []:
        if not isinstance(item, dict):
            continue
        game_versions = {str(value).strip() for value in item.get('game_versions') or []
                         if str(value).strip()}
        if not game_versions:
            continue
        loaders = item.get('loaders') or ['未注明加载器']
        for loader in loaders:
            key = str(loader).strip().lower() or '未注明加载器'
            groups.setdefault(key, set()).update(game_versions)

    if not groups:
        return '兼容范围：没有找到文件级版本声明', ''

    keys = [key for key in _PREFERRED if key in groups]
    keys.extend(sorted(key for key in groups if key not in _PREFERRED))
    lines = ['兼容范围 · 部分可能不支持']
    full = ['各文件声明的游戏版本（不是连续区间）：']
    for key in keys:
        label = LOADER_NAMES.get(key, key if key == '未注明加载器' else key.title())
        values = sorted(groups[key], key=_version_key, reverse=True)
        if len(values) <= 7:
            display = '、'.join(values)
        else:
            display = f'{values[0]} ～ {values[-1]}（共 {len(values)} 个）'
        lines.append(f'{label}：{display}')
        full.append(f'{label}：' + '、'.join(values))
    if partial:
        note = 'CurseForge 文件较多，仅统计已读取的最近文件；更早版本可能未显示。'
        lines.append(note)
        full.append(note)
    elif source == 'curseforge':
        lines.append('依据 CurseForge 文件标签，未标注的兼容性不作推断。')
    return '\n'.join(lines), '\n'.join(full)
