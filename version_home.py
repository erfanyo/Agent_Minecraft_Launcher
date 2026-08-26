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

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
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
                      muted_color, panel_style, tab_style, text_color, set_style)

# 登录方式:offline(离线昵称)/ microsoft(微软正版,设备码流)
LOGIN_OFFLINE = "offline"
LOGIN_MICROSOFT = "microsoft"
_LOGIN_METHODS = [
    (LOGIN_OFFLINE, "离线模式", "正在使用:离线昵称,无需正版账号即可游玩"),
    (LOGIN_MICROSOFT, "微软正版登录", "用微软 Minecraft 账号登录,启动时用正版凭证"),
]
# 规划中的登录方式(仅展示,禁用,标注需后端支持)
_PLANNED_LOGIN = [
    ("yggdrasil", "外置登录(皮肤站)", "外置登录 / 皮肤站支持规划中。"),
]

# 头像占位用色板(沿用启动器现有封面色)
_AVATAR_PALETTE = ["#5B8DEF", "#6BCB77", "#FF6B6B", "#FFD93D", "#B980F0",
                   "#4ECDC4", "#F78FB3", "#82B74B", "#E07B54", "#3E7CB1"]

# 头像尺寸:默认 64,窗口/卡片很小时主动缩小,避免与昵称/登录方式重叠
_AVATAR_BASE = 64
_AVATAR_MIN = 28
# 头像随卡片实际高度缩放:高度越紧,头像越小(避免卡在内容最小高度上不缩)
_AVATAR_SCALE = 0.5


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
        cur_method = load_settings().get("login_method", LOGIN_OFFLINE)
        # 当前模式置 ✓
        for key, label, tip in _LOGIN_METHODS:
            act = menu.addAction(("✓ " if key == cur_method else "") + label)
            act.setToolTip(tip)
            if key == LOGIN_OFFLINE:
                act.triggered.connect(lambda: self._set_offline())
            elif key == LOGIN_MICROSOFT:
                act.triggered.connect(self._do_microsoft_login)
        menu.addSeparator()
        # 当前是微软正版 → 提供退出(回离线)
        if cur_method == LOGIN_MICROSOFT:
            menu.addAction("退出正版登录(回离线)", self._logout_microsoft)
            menu.addSeparator()
        elif cur_method == LOGIN_OFFLINE:
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
        """按卡片实际高度计算头像尺寸(高度越紧越小),并同步昵称字号。

        之前按"可用空间"算,但卡片有 ~156px 内容最小高度,空间一直够,头像不缩;
        且卡片被布局压到 ~142px 时头像仍 64,昵称会叠到头像上。
        这里改为:高度宽裕(≥150)用默认 64;高度不足时用「卡片高 − 下方信息固定高」,
        保证昵称/登录方式始终有空间,不再重叠。"""
        h = self.height()
        if h >= 150:
            size = _AVATAR_BASE
        else:
            # 下方昵称/状态/登录按钮 + 内边距约需 92px,头像只占剩余
            size = int(round(max(_AVATAR_MIN, min(_AVATAR_BASE, h - 92))))
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
        method = self._settings.get("login_method", LOGIN_OFFLINE)
        if method == LOGIN_MICROSOFT:
            name = (self._settings.get("ms_credentials") or {}).get("username", "Minecraft")
        else:
            name = self._settings.get("username", "Steve") or "Steve"
        self._name = name
        self.avatar_label.setPixmap(_avatar_pixmap(name, self._avatar_size))
        self.name_label.setText(name)
        if method == LOGIN_MICROSOFT:
            self.status_label.setText(t("微软正版 · 已登录", "Microsoft · signed in"))
        elif method == LOGIN_OFFLINE:
            self.status_label.setText(t("离线模式 · 昵称可改", "Offline · name editable"))
        else:
            label = next((lbl for key, lbl, _tp in _LOGIN_METHODS if key == method),
                         "离线模式")
            self.status_label.setText(label)
        # 正版登录:尝试拉真实皮肤头像(异步,失败回退占位)
        if method == LOGIN_MICROSOFT:
            uuid_str = (self._settings.get("ms_credentials") or {}).get("uuid", "")
            self._fetch_avatar_async(uuid_str)

    def _fetch_avatar_async(self, uuid_str: str):
        """后台拉正版头像(不卡 UI);成功后换掉占位头像。"""
        if not uuid_str:
            return
        size = max(28, self._avatar_size)
        def worker():
            try:
                from microsoft_auth import download_player_avatar
                data = download_player_avatar(uuid_str, size)
                if data:
                    from PySide6.QtGui import Qt as _Qt, QPixmap as _QPixmap
                    from PySide6.QtCore import QByteArray as _QBA
                    pm = _QPixmap()
                    if pm.loadFromData(_QBA(data)):
                        from PySide6.QtCore import QTimer
                        QTimer.singleShot(0, lambda p=pm: self._apply_avatar_pixmap(p))
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _apply_avatar_pixmap(self, pm):
        if pm is not None and not pm.isNull():
            self.avatar_label.setPixmap(pm.scaled(self._avatar_size, self._avatar_size,
                                                  Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                  Qt.TransformationMode.SmoothTransformation))

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

    # ---- 微软正版登录 ----
    def _do_microsoft_login(self):
        """设备码流登录:先在弹窗里给用户 device code + 网址,后台线程轮询授权,成功后存凭证。"""
        from microsoft_auth import MsAuth
        # 用信号把线程结果搬回主线程(跨线程碰 Qt 会崩)
        from PySide6.QtCore import QObject, Signal as _Sig, QTimer
        class _Bridge(QObject):
            done = _Sig(object)
            fail = _Sig(str)
        bridge = _Bridge()

        auth = MsAuth()
        try:
            info = auth.start_device_code()
        except Exception as e:
            QMessageBox.warning(self, "微软登录", f"无法发起登录(网络/接口问题):\n{e}")
            return

        user_code = info.get("user_code", "")
        uri = info.get("verification_uri", "")
        # 提示弹窗:给用户 device code + 网址,并自动打开浏览器
        dlg = QDialog(self)
        dlg.setWindowTitle("微软登录 · 请在浏览器完成授权")
        dlg.setMinimumSize(520, 300)
        dl = QVBoxLayout(dlg)
        dl.addWidget(QLabel("<b>请在浏览器里打开下面的网址,并输入设备代码:</b>"))
        code_lbl = QLabel(f"<span style='font-size:28px;font-weight:bold;'>{user_code}</span>")
        code_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        url_lbl = QLabel(f"<span style='font-size:16px;'>{uri}</span>")
        url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        url_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        open_btn = QPushButton("▶ 打开浏览器授权")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(uri)))
        dl.addWidget(code_lbl)
        dl.addWidget(url_lbl)
        dl.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        wait = QLabel("登录过程中请保持此窗口打开;成功后自动关闭。")
        wait.setWordWrap(True); wait.setStyleSheet("color:#888888;")
        dl.addWidget(wait)
        close_btn = QPushButton("取消")
        close_btn.clicked.connect(dlg.reject)
        dl.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)

        bridge.done.connect(lambda result: (dlg.accept(), self._finish_ms_login(result)))
        bridge.fail.connect(lambda msg: (dlg.reject(), QMessageBox.warning(self, "微软登录", msg)))
        QDesktopServices.openUrl(QUrl(uri))   # 自动打开浏览器

        def worker():
            try:
                result = auth.await_token()
                bridge.done.emit(result)
            except Exception as e:
                bridge.fail.emit(f"{type(e).__name__}: {e}")
        threading.Thread(target=worker, daemon=True).start()
        dlg.exec()

    def _finish_ms_login(self, result: dict):
        """登录成功:存凭证 + 切到 microsoft 模式。"""
        settings = load_settings()
        settings["login_method"] = LOGIN_MICROSOFT
        settings["ms_credentials"] = {
            "username": result.get("username", ""),
            "uuid": result.get("uuid", ""),
            "access_token": result.get("access_token", ""),
            "refresh_token": result.get("refresh_token", ""),
        }
        save_settings(settings)
        self.refresh()
        self.changed.emit()
        # 让主窗口也能用上(刷新标题栏/当前实例等)
        try:
            from PySide6.QtWidgets import QApplication
            mw = QApplication.activeWindow()
            if mw is not None and hasattr(mw, "_on_login_changed"):
                mw._on_login_changed()
        except Exception:
            pass

    def _logout_microsoft(self):
        """退出微软正版,回离线。"""
        settings = load_settings()
        settings["login_method"] = LOGIN_OFFLINE
        settings["ms_credentials"] = {}
        save_settings(settings)
        self.refresh()
        self.changed.emit()

    def _set_offline(self):
        """切回离线(若当前非离线)。"""
        settings = load_settings()
        if settings.get("login_method") != LOGIN_OFFLINE:
            settings["login_method"] = LOGIN_OFFLINE
            settings["ms_credentials"] = {}
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

        self.title = QLabel(t("当前选择", "Current selection"))
        self.title.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {muted_color()};")
        self.inst_label = QLabel(t("未选择实例", "No instance selected"))
        self.inst_label.setWordWrap(True)
        self.inst_label.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {text_color()};")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(6)
        lay.addWidget(self.title)
        lay.addWidget(self.inst_label)

    def set_instance(self, inst: dict | None):
        """更新「当前选择」信息。inst 为 None 表示未选择。"""
        self._inst = inst
        if inst is None:
            self.inst_label.setText(t("未选择实例", "No instance selected"))
        else:
            self.inst_label.setText(inst.get("id", "?"))


class VersionHome(QWidget):
    """「我的版本」首页(仿 PCL2)。"""

    open_instance_manager_requested = Signal(object)  # inst dict 或 None
    open_settings_requested = Signal()
    login_changed = Signal()
    one_click_config_requested = Signal(str)  # "bridge"/"rcon"/"auto" → 主窗口处理
    import_modpack_requested = Signal()       # 导入整合包
    tutorial_requested = Signal()            # 打开新手教程
    instance_selected = Signal(object)       # 选中实例(或 None)→ 主窗口 显示/隐藏「实例详情」标签页
    refresh_requested = Signal()             # 切回「实例」标签页请求刷新(无刷新按钮,自动刷)
    launch_requested = Signal(object)        # 键盘回车启动选中实例(遥控器式导航)
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

        # 「导入整合包」(左)+「一键配置」(右)并排,放在「启动游戏」上方
        tool_row = QHBoxLayout()
        tool_row.setSpacing(10)
        self.import_btn = QPushButton(t("导入整合包", "Import Modpack"))
        self.import_btn.setMinimumHeight(44)
        self.import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_style(self.import_btn, card_btn_style)
        self.import_btn.clicked.connect(self.import_modpack_requested.emit)
        tool_row.addWidget(self.import_btn, 1)

        self.config_btn = QToolButton()
        self.config_btn.setText(t("一键配置 ▾", "One-click ▾"))
        self.config_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.config_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.config_btn.setMinimumHeight(44)
        self.config_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_style(self.config_btn, card_btn_style)
        cfg_menu = QMenu(self.config_btn)
        bridge_item = cfg_menu.addAction(
            t("一键配置 bridge-mod(本地指令口,推荐)",
              "One-click bridge-mod (local command port, recommended)"),
            lambda: self.one_click_config_requested.emit("bridge"))
        bridge_item.setToolTip("下载并安装 bridge-mod(游戏内指令口 / 数据导出),需加载器")
        rcon_item = cfg_menu.addAction(
            t("一键配置 RCON(临时方案)", "One-click RCON (temporary)"),
            lambda: self.one_click_config_requested.emit("rcon"))
        rcon_item.setToolTip("临时方案:需要 Lan Server Properties,进世界后按 ESC → 对局域网开放")
        self.config_btn.setMenu(cfg_menu)
        tool_row.addWidget(self.config_btn, 1)
        lay.addLayout(tool_row)

        # 启动游戏大按钮
        self.launch_btn = QPushButton(t("启动游戏", "Launch Game"))
        self.launch_btn.setMinimumHeight(56)
        self.launch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_style(self.launch_btn, launch_btn_style)
        lay.addWidget(self.launch_btn)

        return left

    # ---- MC 存储路径(游戏目录)下拉 ----
    def _game_dirs(self) -> list:
        """历史上的游戏目录列表(不含当前默认)。"""
        from settings import load_settings
        s = load_settings()
        return [p for p in (s.get("game_dirs_history") or []) if p.strip()]

    def _fill_game_dir_combo(self):
        from settings import load_settings
        from paths import GAME_DIR as _cur_game_dir
        s = load_settings()
        cur = (s.get("game_dir") or _cur_game_dir or "").strip()
        self.game_dir_combo.clear()
        self.game_dir_combo.addItem(f"当前:{cur or '(默认)'}", cur)     # 0 当前
        for p in self._game_dirs():
            if p and p != cur:
                self.game_dir_combo.addItem(p, p)
        self.game_dir_combo.insertSeparator(self.game_dir_combo.count())
        self.game_dir_combo.addItem("＋ 添加新路径…", "__add__")          # 最后一项 = 添加

    def _on_game_dir_changed(self, idx: int):
        data = self.game_dir_combo.itemData(idx)
        if data == "__add__":
            self._add_new_game_dir()
            return
        if data:
            self._set_game_dir(data)

    def _add_new_game_dir(self):
        """弹目录选择,把新路径加入历史并切换。"""
        import paths
        start = paths.GAME_DIR or paths.DEFAULT_GAME_DIR
        d = QFileDialog.getExistingDirectory(self, "选择 MC 存储路径(.minecraft 目录)", start)
        if not d:
            self._fill_game_dir_combo()   # 取消 → 恢复选择
            return
        self._set_game_dir(d, remember=True)

    def _set_game_dir(self, path: str, remember: bool = True):
        """切换全局游戏目录:set_game_dir + 存设置 + 记录历史 + 刷新实例。"""
        from settings import load_settings, save_settings
        import paths
        path = (path or "").strip()
        if not path:
            return
        paths.set_game_dir(path)
        s = load_settings()
        s["game_dir"] = path
        if remember:
            hist = [p for p in (s.get("game_dirs_history") or []) if p.strip()]
            if path in hist:
                hist.remove(path)
            hist.insert(0, path)
            s["game_dirs_history"] = hist[:20]
        save_settings(s)
        self._fill_game_dir_combo()
        # 刷新实例列表 / 状态栏
        try:
            self.refresh_requested.emit()
        except Exception:
            pass
        try:
            win = self.window()
            if win is not None and hasattr(win, "refresh_instances"):
                win.refresh_instances()
        except Exception:
            pass

    def _build_right(self) -> QWidget:
        """右列:标签页(版本 / 更新日志 / MC 动态)。"""
        right = QWidget()
        lay = QVBoxLayout(right)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        set_style(self.tabs, tab_style)

        self._version_tab_index = self.tabs.addTab(self._build_version_tab(), t("实例", "Instances"))
        self.tabs.addTab(self._build_changelog_tab(), t("更新日志", "Changelog"))
        self.tabs.addTab(self._build_community_tab(), t("MC 动态", "Community"))
        # 启动器日志:作为「MC 动态」同级的子标签页(游戏运行输出/命令)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.tabs.addTab(self.log_view, t("启动器日志", "Launcher Log"))
        # 切回「实例」标签页时自动刷新(不再有刷新按钮)
        self.tabs.currentChanged.connect(self._on_home_tab_changed)

        lay.addWidget(self.tabs)
        return right

    def set_instance_count(self, n: int):
        """把右列「实例」标签页文本更新为「实例(共x个)」。"""
        if hasattr(self, "tabs") and hasattr(self, "_version_tab_index"):
            self.tabs.setTabText(self._version_tab_index, t(f"实例(共{n}个)", f"Instances ({n})"))

    def _on_home_tab_changed(self, index: int):
        if index == self._version_tab_index:
            self.refresh_requested.emit()

    def _build_version_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # 「我的实例」标题与「刷新」按钮已移除:标签页文本显示实例数,切回本页自动刷新

        # 「MC 存储路径」下拉:切换不同游戏目录/添加新路径(在「实例(共x个)」标签下方)
        gdir_row = QHBoxLayout(); gdir_row.setSpacing(8)
        gdir_lbl = QLabel("存储路径:")
        gdir_lbl.setStyleSheet(f"color: {muted_color()};")
        self.game_dir_combo = QComboBox()
        self.game_dir_combo.setObjectName("game_dir_combo")
        self.game_dir_combo.setMinimumHeight(34)
        self.game_dir_combo.setToolTip("游戏数据(.minecraft)存储目录。选一个或「添加新路径」。")
        self._fill_game_dir_combo()
        self.game_dir_combo.currentIndexChanged.connect(self._on_game_dir_changed)
        gdir_row.addWidget(gdir_lbl)
        gdir_row.addWidget(self.game_dir_combo, 1)
        lay.addLayout(gdir_row)

        self.instance_list = QListWidget()
        set_style(self.instance_list, list_style)
        self.instance_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.instance_list.currentItemChanged.connect(self._on_selection_changed)
        # 键盘导航:上下方向键已在选择实例;回车(itemActivated)= 启动选中实例(遥控器式)
        self.instance_list.itemActivated.connect(self._launch_current_via_key)
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
        set_style(self.changelog_refresh_btn, card_btn_style)
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
            f"<p style='color:{muted_color()}'>🔄 正在从 GitHub 拉取更新日志…</p>")
        self.changelog_status.setText(
            t("来源:github.com/erfanyo/Agent_Minecraft_Launcher/CHANGELOG.md",
              "Source: github.com/erfanyo/Agent_Minecraft_Launcher/CHANGELOG.md"))
        return w

    def _load_changelog_async(self):
        """后台线程从 GitHub 拉取更新日志,避免卡 UI。"""
        self.changelog_status.setText(
            t("正在从 GitHub 拉取…", "Fetching from GitHub…"))
        self.changelog_view.setHtml(
            f"<p style='color:{muted_color()}'>🔄 正在从 GitHub 拉取更新日志…</p>")

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
            t("来源:github.com/erfanyo/Agent_Minecraft_Launcher/CHANGELOG.md",
              "Source: github.com/erfanyo/Agent_Minecraft_Launcher/CHANGELOG.md"))

    def _on_changelog_failed(self, err: str):
        """从 GitHub 拉取失败 → 显示友好提示 + 重试入口。"""
        self.changelog_view.setHtml(
            f"<p style='color:{muted_color()}'>暂时拉不到更新日志(网络或 GitHub 不可用)。"
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
        """刷新实例数量(由 MainWindow.refresh_instances 调用)→ 更新「实例(共x个)」标签文本。"""
        self.set_instance_count(len(instances))

    def current_instance(self):
        """当前在「版本」列表里选中的实例 dict(没选返回 None)。"""
        item = self.instance_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    # ---------- 内部逻辑 ----------
    def _on_selection_changed(self, current, _previous):
        """选中实例变化 → 更新「当前选择」卡片,并通知主窗口(显示/隐藏「实例详情」标签页)。"""
        inst = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        self.inst_card.set_instance(inst)
        self.launch_btn.setToolTip(
            inst.get("id", "") if inst is not None else t("先选择实例", "Select an instance first"))
        self.instance_selected.emit(inst)

    def _launch_current_via_key(self, item):
        """键盘导航:实例列表里按 Enter → 启动选中实例(遥控器式)。
        itemActivated 在回车/双击时触发。"""
        inst = self.current_instance()
        if inst is not None:
            self.launch_requested.emit(inst)

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
