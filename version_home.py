# -*- coding: utf-8 -*-
"""
「我的版本」首页 —— 仿 PCL2 布局。

整体分左右两列:
- 左列(约 1/3):登录卡片(头像/昵称/登录方式 + 更改登录方式入口)、
  当前实例卡片(纯展示)、启动游戏大按钮,以及其下方的「启动器设置」与
  「管理 ▾」两个按钮(设置核心入口合并于此)。
- 右列(约 2/3):顶部标签页 —— 版本选择 / 启动器更新日志 / (未来)MC 社区动态。

本模块只做界面与「前端可自洽」的状态(如离线昵称修改),凡是需要启动器
能力(启动/实例管理/整体设置)的,统一通过信号抛给 MainWindow 处理,
避免这个面板反向依赖启动器内部状态。

对外暴露用于保持旧代码兼容的成员:
- .instance_list   —— 右列「版本」标签里的实例列表(QListWidget)
- .launch_btn      —— 左列「启动游戏」大按钮(QPushButton)
- .refresh_btn     —— 右列「版本」标签里的刷新按钮(QPushButton)
"""
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMenu,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from changelog import changelog_html, load_changelog
from i18n import t
from settings import load_settings, save_settings
from ui_style import (card_btn_style, hover_bg, launch_btn_style, list_style,
                      muted_color, panel_style, tab_style, text_color)

# 登录方式:目前仅支持离线(昵称可改);正版/外置为规划占位,不伪造后端能力
LOGIN_OFFLINE = "offline"
_LOGIN_METHODS = [
    (LOGIN_OFFLINE, "离线模式", "正在使用:离线昵称,无需正版账号即可游玩"),
]
# 规划中的登录方式(仅展示,禁用,标注需后端支持)
_PLANNED_LOGIN = [
    ("microsoft", "微软正版登录", "正版登录需要后端支持(规划 v1.0)。"),
    ("yggdrasil", "外置登录(皮肤站)", "外置登录 / 皮肤站支持规划中。"),
]

# 头像占位用色板(沿用启动器现有封面色)
_AVATAR_PALETTE = ["#5B8DEF", "#6BCB77", "#FF6B6B", "#FFD93D", "#B980F0",
                   "#4ECDC4", "#F78FB3", "#82B74B", "#E07B54", "#3E7CB1"]

# 头像尺寸:默认 64,窗口/卡片很小时主动缩小,避免与昵称/登录方式重叠
_AVATAR_BASE = 64
_AVATAR_MIN = 28


def _avatar_pixmap(name: str, size: int = _AVATAR_BASE) -> QPixmap:
    """按昵称生成一个圆形占位头像。

    后期接入真实皮肤/头像系统:只要换成按玩家皮肤生成 pixmap(签名同 `(name, size)`),
    这里即可无缝替换为皮肤头像,无需改动调用方。
    """
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    idx = sum(ord(c) for c in (name or "?")) % len(_AVATAR_PALETTE)
    painter.setBrush(QBrush(QColor(_AVATAR_PALETTE[idx])))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.setPen(QColor("white"))
    font = painter.font()
    font.setPointSizeF(size * 0.42)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, (name or "?")[:1].upper())
    painter.end()
    return pix


class LoginCard(QWidget):
    """登录卡片:头像 + 昵称 + 登录方式 + 「更改登录方式」入口。

    目前只有离线模式可操作(修改昵称);正版/外置入口用禁用占位,点开有说明。
    """

    changed = Signal()          # 昵称/登录方式变化 → 让启动器重读设置
    open_settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._avatar_size = _AVATAR_BASE   # 当前头像尺寸(随窗口自适应)
        self._name = ""
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("loginCard")
        self.setStyleSheet(f"#loginCard {{ {panel_style()} }}")

        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(self._avatar_size, self._avatar_size)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.name_label = QLabel()
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setStyleSheet(f"font-weight: bold; font-size: 17px; color: {text_color()};")

        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet(f"color: {muted_color()};")

        # 更改登录方式入口
        self.login_btn = QToolButton()
        self.login_btn.setText(t("更改登录方式 ▾", "Change login ▾"))
        self.login_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.login_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.setStyleSheet(
            f"QToolButton {{ color: {text_color()}; border: none; background: transparent;"
            f" padding: 2px 6px; border-radius: 6px; }}"
            f"QToolButton:hover {{ background: {hover_bg()}; }}")
        menu = QMenu(self.login_btn)
        for key, label, tip in _LOGIN_METHODS:
            act = menu.addAction(f"✓ {label}")
            act.setEnabled(False)          # 当前方式:仅展示
            act.setToolTip(tip)
        menu.addSeparator()
        menu.addAction(t("修改离线昵称…", "Edit offline name…"),
                       self._change_offline_name)
        menu.addSeparator()
        for _key, label, tip in _PLANNED_LOGIN:
            act = menu.addAction(label)
            act.setEnabled(False)
            act.setToolTip(tip)
        self.login_btn.setMenu(menu)
        # 登录方式入口也提供「启动器设置…」二级入口,方便直接改内存/目录等
        menu.addSeparator()
        menu.addAction(t("打开启动器设置…", "Open launcher settings…"),
                       lambda: self.open_settings_requested.emit())

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 14, 12, 12)
        lay.setSpacing(6)
        lay.addWidget(self.avatar_label, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.name_label)
        lay.addWidget(self.status_label)
        lay.addWidget(self.login_btn, 0, Qt.AlignmentFlag.AlignCenter)

    def resizeEvent(self, event):
        """窗口/卡片变小时主动缩小头像与昵称字号,避免与下方信息重叠。"""
        super().resizeEvent(event)
        self._apply_avatar_size()

    def _apply_avatar_size(self):
        """按卡片可用空间计算合适头像尺寸(太小则缩小),并同步昵称字号。

        头像随卡片宽度/高度成比例缩放:空间宽裕 → 回到 64;空间紧张 → 主动缩小,
        避免头像与昵称/登录方式在小窗口里重叠。"""
        avail = max(36, min(self.width(), self.height()) - 40)
        # 0.55 系数:卡片可用空间约 116px 时头像降到 64 以下并继续随空间缩小
        size = int(round(max(_AVATAR_MIN, min(_AVATAR_BASE, avail * 0.55))))
        if size != self._avatar_size:
            self._avatar_size = size
            self.avatar_label.setFixedSize(size, size)
            self.avatar_label.setPixmap(_avatar_pixmap(self._name or "Steve", size))
        # 昵称字号跟随空间:头像很小(空间紧张)时缩小文字,恢复时回到默认
        if size <= 40:
            fs = max(12, int(size * 0.36))
            self.name_label.setStyleSheet(
                f"font-weight: bold; font-size: {fs}px; color: {text_color()};")
        else:
            self.name_label.setStyleSheet(
                f"font-weight: bold; font-size: 17px; color: {text_color()};")

    def refresh(self):
        """根据最新设置刷新:头像/昵称/登录方式。"""
        self._settings = load_settings()
        name = self._settings.get("username", "Steve") or "Steve"
        self._name = name
        self.avatar_label.setPixmap(_avatar_pixmap(name, self._avatar_size))
        self.name_label.setText(name)
        method = self._settings.get("login_method", LOGIN_OFFLINE)
        if method == LOGIN_OFFLINE:
            # 目前仅离线模式:如实显示,不伪装成「正版验证」
            self.status_label.setText(t("离线模式 · 昵称可改", "Offline · name editable"))
        else:
            label = next((lbl for key, lbl, _tp in _LOGIN_METHODS if key == method),
                         "离线模式")
            self.status_label.setText(label)

    def _change_offline_name(self):
        """修改离线昵称(前端可自洽:写到 config.json 并通知启动器)。"""
        # 读取最新配置再改昵称,避免用启动时的旧快照覆盖用户改过的其他设置(如内存)
        cur = load_settings().get("username", "Steve")
        new, ok = QInputDialog.getText(self, t("修改离线昵称", "Edit offline name"),
                                       t("离线模式显示的游戏名:", "Offline in-game name:"),
                                       text=cur)
        if not ok:
            return
        new = new.strip() or "Steve"
        settings = load_settings()
        settings["username"] = new
        save_settings(settings)
        self.refresh()
        self.changed.emit()


class InstanceSettingsCard(QWidget):
    """当前实例卡片(纯展示):显示选中的实例关键信息。

    具体操作(实例管理/启动器设置/版本选择)已下沉到「启动游戏」下方的
    「启动器设置」与「管理 ▾」按钮,卡片只负责把当前实例说明清楚。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._inst = None
        self._build_ui()

    def _build_ui(self):
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("instCard")
        self.setStyleSheet(f"#instCard {{ {panel_style()} }}")

        self.title = QLabel(t("实例设置", "Instance settings"))
        self.title.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {muted_color()};")
        self.inst_label = QLabel(t("未选择实例", "No instance selected"))
        self.inst_label.setWordWrap(True)
        self.inst_label.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {text_color()};")
        self.inst_detail = QLabel("—")
        self.inst_detail.setWordWrap(True)
        self.inst_detail.setStyleSheet(f"color: {muted_color()};")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(6)
        lay.addWidget(self.title)
        lay.addWidget(self.inst_label)
        lay.addWidget(self.inst_detail)

    def set_instance(self, inst: dict | None):
        """更新「当前实例」信息。inst 为 None 表示未选择。"""
        self._inst = inst
        if inst is None:
            self.inst_label.setText(t("未选择实例", "No instance selected"))
            self.inst_detail.setText(t("在右侧「版本」里选一个,或去「下载新资源」创建",
                                       "Pick one on the right, or create one in Resources"))
        else:
            self.inst_label.setText(inst.get("id", "?"))
            loader = inst.get("loader") or t("原版", "Vanilla")
            self.inst_detail.setText(f"{loader} ← {inst.get('base', '?')}")


class VersionHome(QWidget):
    """「我的版本」首页(仿 PCL2)。"""

    open_instance_manager_requested = Signal(object)  # inst dict 或 None
    open_settings_requested = Signal()
    login_changed = Signal()
    _changelog_loaded = Signal(list)   # 后台拉取完成 → 主线程渲染(跨线程安全)
    _changelog_failed = Signal(str)    # 拉取失败(GitHub + 本地都不可用)→ 主线程提示

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._on_selection_changed(None, None)
        # 更新日志:后台线程拉取 GitHub CHANGELOG.md,完成后主线程渲染
        self._changelog_loaded.connect(self._on_changelog_loaded)
        self._changelog_failed.connect(self._on_changelog_failed)
        self._load_changelog_async()

    # ---------- UI 搭建 ----------
    def _build_ui(self):
        main = QHBoxLayout(self)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(14)
        main.addWidget(self._build_left(), 1)
        main.addWidget(self._build_right(), 2)

    def _build_left(self) -> QWidget:
        """左列:登录 + 当前实例 + 启动按钮 + 启动器设置/管理。"""
        left = QWidget()
        lay = QVBoxLayout(left)
        lay.setSpacing(12)

        # 登录卡片
        self.login_card = LoginCard()
        self.login_card.changed.connect(self.login_changed.emit)
        self.login_card.open_settings_requested.connect(self.open_settings_requested.emit)
        lay.addWidget(self.login_card)

        # 当前实例卡片(纯展示)
        self.inst_card = InstanceSettingsCard()
        lay.addWidget(self.inst_card)

        lay.addStretch(1)

        # 启动游戏大按钮
        self.launch_btn = QPushButton(t("启动游戏", "Launch Game"))
        self.launch_btn.setMinimumHeight(56)
        self.launch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.launch_btn.setStyleSheet(launch_btn_style())
        lay.addWidget(self.launch_btn)

        # 启动按钮下方的小字(当前选中版本,类似 PCL 的 "No Flesh Within Chest")
        self.launch_hint = QLabel(t("选择右侧版本后启动", "Pick a version on the right"))
        self.launch_hint.setStyleSheet(f"color: {muted_color()};")
        self.launch_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.launch_hint.setWordWrap(True)
        lay.addWidget(self.launch_hint)

        # 启动游戏下方:启动器设置(设置核心入口) + 管理 ▾(实例管理/整体设置/版本选择)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.settings_btn = QPushButton(t("启动器设置", "Launcher settings"))
        self.settings_btn.setStyleSheet(card_btn_style())
        self.settings_btn.setMinimumHeight(44)
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.clicked.connect(self.open_settings_requested.emit)
        btn_row.addWidget(self.settings_btn, 1)

        self.manage_btn = QToolButton()
        self.manage_btn.setText(t("管理 ▾", "Manage ▾"))
        self.manage_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.manage_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.manage_btn.setMinimumHeight(44)
        self.manage_btn.setStyleSheet(card_btn_style())
        menu = QMenu(self.manage_btn)
        menu.addAction(t("实例管理(当前实例)…", "Manage current instance…"),
                       self._manage_current)
        menu.addAction(t("整体设置…", "Overall settings…"),
                       self.open_settings_requested.emit)
        menu.addSeparator()
        menu.addAction(t("版本选择", "Choose version"), self._focus_version_tab)
        self.manage_btn.setMenu(menu)
        btn_row.addWidget(self.manage_btn, 1)
        lay.addLayout(btn_row)

        return left

    def _build_right(self) -> QWidget:
        """右列:标签页(版本 / 更新日志 / MC 动态)。"""
        right = QWidget()
        lay = QVBoxLayout(right)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet(tab_style())

        self.tabs.addTab(self._build_version_tab(), t("版本", "Versions"))
        self.tabs.addTab(self._build_changelog_tab(), t("更新日志", "Changelog"))
        self.tabs.addTab(self._build_community_tab(), t("MC 动态", "Community"))

        lay.addWidget(self.tabs)
        return right

    def _build_version_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel(t("我的实例", "My instances"))
        title.setStyleSheet(f"font-weight: bold; font-size: 15px; color: {text_color()};")
        header.addWidget(title)
        header.addStretch(1)
        self.count_label = QLabel("0")
        self.count_label.setStyleSheet(f"color: {muted_color()};")
        header.addWidget(self.count_label)
        self.refresh_btn = QPushButton(t("刷新", "Refresh"))
        self.refresh_btn.setStyleSheet(card_btn_style())
        self.refresh_btn.setMinimumHeight(30)
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        header.addWidget(self.refresh_btn)
        lay.addLayout(header)

        self.instance_list = QListWidget()
        self.instance_list.setStyleSheet(list_style())
        self.instance_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.instance_list.currentItemChanged.connect(self._on_selection_changed)
        lay.addWidget(self.instance_list, 1)
        return w

    def _build_changelog_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        self.changelog_view = QTextBrowser()
        self.changelog_view.setOpenExternalLinks(True)
        self.changelog_view.setStyleSheet(
            f"QTextBrowser {{ background: transparent; border: none; color: {text_color()}; }}")
        self.changelog_status = QLabel()
        self.changelog_status.setStyleSheet(f"color: {muted_color()};")
        self.changelog_status.setWordWrap(True)
        self.changelog_refresh_btn = QPushButton(t("刷新", "Refresh"))
        self.changelog_refresh_btn.setStyleSheet(card_btn_style())
        self.changelog_refresh_btn.setMinimumHeight(30)
        self.changelog_refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.changelog_refresh_btn.clicked.connect(self._load_changelog_async)

        # 标题行:更新日志 + 来源说明 + 刷新按钮
        header = QHBoxLayout()
        title = QLabel(t("更新日志", "Changelog"))
        title.setStyleSheet(f"font-weight: bold; font-size: 15px; color: {text_color()};")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.changelog_refresh_btn)
        lay.addLayout(header)
        lay.addWidget(self.changelog_view, 1)

        # 初始态:显示"正在拉取",加载完成后替换
        self.changelog_view.setHtml(
            "<p style='color:#888888'>🔄 正在从 GitHub 拉取更新日志…</p>")
        self.changelog_status.setText(
            t("来源:github.com/%s/CHANGELOG.md(失败时回退本地)" % "erfanyo/Agent_Minecraft_Launcher",
              "Source: github.com/erfanyo/Agent_Minecraft_Launcher/CHANGELOG.md (falls back to local)"))
        return w

    def _load_changelog_async(self):
        """后台线程拉取更新日志(GitHub 优先,失败回退本地),避免卡 UI。"""
        self.changelog_status.setText(
            t("正在从 GitHub 拉取…", "Fetching from GitHub…"))
        self.changelog_view.setHtml(
            "<p style='color:#888888'>🔄 正在从 GitHub 拉取更新日志…</p>")

        def worker():
            try:
                entries = load_changelog()
                if entries:
                    self._changelog_loaded.emit(entries)
                else:
                    self._changelog_failed.emit("empty")
            except Exception as e:
                self._changelog_failed.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_changelog_loaded(self, entries: list):
        """更新日志拉取成功 → 渲染 HTML。"""
        self.changelog_view.setHtml(changelog_html(entries))
        self.changelog_status.setText(
            t("来源:github.com/erfanyo/Agent_Minecraft_Launcher/CHANGELOG.md(失败时回退本地)",
              "Source: github.com/erfanyo/Agent_Minecraft_Launcher/CHANGELOG.md (falls back to local)"))

    def _on_changelog_failed(self, err: str):
        """GitHub 与本地均无可用更新日志 → 显示友好提示。"""
        self.changelog_view.setHtml(
            "<p style='color:#888888'>暂时拉不到更新日志(GitHub 与本地均不可用)。"
            "<br>可点击右上角「刷新」重试,或检查网络。</p>")
        self.changelog_status.setText(t("拉取失败,请检查网络后点「刷新」",
                                        "Fetch failed, check network and Refresh"))

    def _build_community_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        placeholder = QLabel(
            t("MC 社区动态(规划中)\n\n"
              "未来这里会显示 Minecraft 社区动态、新闻等内容。当前为占位。",
              "MC community feed (planned)\n\nFuture home for community news. Placeholder."))
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setWordWrap(True)
        placeholder.setStyleSheet(f"color: {muted_color()};")
        lay.addWidget(placeholder)
        return w

    # ---------- 对外接口 ----------
    def refresh_login(self):
        """重新读取设置刷新登录卡片(昵称/头像)。"""
        self.login_card.refresh()

    def set_current_instances(self, instances: list):
        """刷新实例数量(由 MainWindow.refresh_instances 调用)。"""
        self.count_label.setText(f"共 {len(instances)} 个")

    def current_instance(self):
        """当前在「版本」列表里选中的实例 dict(没选返回 None)。"""
        item = self.instance_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    # ---------- 内部逻辑 ----------
    def _on_selection_changed(self, current, _previous):
        """选中实例变化 → 更新实例设置卡片 + 启动按钮副标题。"""
        inst = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        self.inst_card.set_instance(inst)
        if inst is not None:
            self.launch_hint.setText(inst.get("label") or inst.get("id", ""))
        else:
            self.launch_hint.setText(t("选择右侧版本后启动", "Pick a version on the right"))
        self.launch_btn.setToolTip(
            inst.get("id", "") if inst is not None else t("先选择实例", "Select an instance first"))

    def _manage_current(self):
        """「管理 ▾」→ 实例管理:打开当前选中实例的管理对话框。"""
        inst = self.current_instance()
        if inst is not None:
            self.open_instance_manager_requested.emit(inst)
        else:
            self.open_instance_manager_requested.emit(None)

    def _focus_version_tab(self):
        """「版本选择」:切到右列「版本」标签并聚焦列表。"""
        self.tabs.setCurrentIndex(0)
        self.instance_list.setFocus()
