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
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import (QBrush, QColor, QDesktopServices, QImageReader,
                           QPainter, QPixmap)
from PySide6.QtWidgets import (
    QApplication,
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
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from i18n import t
from settings import load_settings, save_settings
from ui_style import (card_btn_style, hover_bg, launch_btn_style, list_style,
                      accent_color, is_dark_mode, muted_color, panel_style,
                      success_color, tab_style, text_color, set_style)

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


def _server_fallback_pixmap(size: int = _AVATAR_BASE) -> QPixmap:
    """Theme-aware pixel server/community node used when no server icon exists."""
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    asset = root / 'icons' / (
        'server_cabinet_dark.png' if is_dark_mode() else 'server_cabinet_light.png')
    image = QPixmap(str(asset))
    if not image.isNull():
        return image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.FastTransformation)
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    unit = max(1, size // 8)
    offset = (size - unit * 8) // 2
    accent = QColor(accent_color())
    panel = QColor(muted_color())
    edge = QColor(text_color())
    light = QColor(success_color())

    # Two compact server units. Their hard 8×8 grid keeps a Minecraft-like
    # silhouette while the colors come from AMCL's active theme.
    for y in (0, 5):
        painter.fillRect(offset + unit, offset + unit * y, unit * 6, unit * 3, edge)
        painter.fillRect(offset + unit * 2, offset + unit * (y + 1), unit * 4, unit, panel)
        painter.fillRect(offset + unit * 5, offset + unit * (y + 1), unit, unit, light)
        painter.fillRect(offset + unit, offset + unit * (y + 2), unit * 6, unit, accent)

    # A hub and two peers: generic enough for any server, but visibly conveys
    # multiplayer/community rather than a Mojang-owned block texture.
    painter.fillRect(offset + unit * 3, offset + unit * 3, unit * 2, unit * 2, accent)
    painter.fillRect(offset, offset + unit * 3, unit, unit * 2, edge)
    painter.fillRect(offset + unit * 7, offset + unit * 3, unit, unit * 2, edge)
    painter.fillRect(offset + unit, offset + unit * 3, unit * 2, unit, accent)
    painter.fillRect(offset + unit * 5, offset + unit * 3, unit * 2, unit, accent)
    painter.end()
    return pix


def _server_avatar_pixmap(server, size: int = _AVATAR_BASE) -> QPixmap:
    """Use the standard 64×64 server icon, with a safe local fallback."""
    try:
        root = (server or {}).get('path')
        if not root:
            raise ValueError('no selected server')
        icon = Path(root, 'server-icon.png')
        if (not icon.is_file() or icon.is_symlink()
                or icon.stat().st_size > 1024 * 1024):
            raise ValueError('missing or unusually large server icon')
        reader = QImageReader(str(icon))
        reader.setDecideFormatFromContent(True)
        dimensions = reader.size()
        if dimensions.width() != 64 or dimensions.height() != 64:
            raise ValueError('server-icon.png must be 64×64')
        image = reader.read()
        if image.isNull():
            raise ValueError('invalid server icon')
        return QPixmap.fromImage(image).scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
    except (OSError, TypeError, ValueError):
        return _server_fallback_pixmap(size)


class LoginCard(QWidget):
    """登录卡片:头像 + 昵称 + 登录方式 + 「更改登录方式」入口。

    目前只有离线模式可操作(修改昵称);正版/外置入口用禁用占位,点开有说明。
    """

    changed = Signal()          # 昵称/登录方式变化 → 让启动器重读设置
    open_settings_requested = Signal()
    _avatar_ready = Signal(bytes)   # 后台线程拉到头像后,把字节送回主线程(queued 到 GUI 线程)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._avatar_size = _AVATAR_BASE   # 当前头像尺寸(随窗口自适应)
        self._name = ""
        self._server_mode = False
        self._server = None
        self._avatar_ready.connect(self._apply_avatar_bytes)
        self._build_ui()
        self.refresh()

    def _build_login_menu(self):
        """按当前设置动态构建登录菜单(每次打开前重建,保证状态与菜单一致)。"""
        menu = self.login_btn.menu()
        menu.clear()
        s = load_settings()
        cur_method = s.get("login_method", LOGIN_OFFLINE)
        force_online = s.get("microsoft_login", True)        # 强制正版(默认 true)
        has_creds = bool((s.get("ms_credentials") or {}).get("uuid"))
        # 是否允许离线昵称:
        #  - 强制正版且【无正版凭证】:完全禁止离线,必须先登录正版
        #  - 正版玩家(有凭证)或非强制:都可自由切离线昵称(凭证保留)
        allow_offline = (not force_online) or has_creds

        if not allow_offline:
            act = menu.addAction(("✓ " if cur_method == LOGIN_MICROSOFT else "") + "微软正版登录")
            act.setToolTip("强制正版(microsoft_login=true)且本机无正版账号,请先登录正版。"
                           "想纯离线请把开关改为 false。")
            if cur_method != LOGIN_MICROSOFT:
                act.triggered.connect(self._do_microsoft_login)
        else:
            # 正版/离线昵称 切换(正版玩家可自由选离线昵称,凭证保留)
            if cur_method == LOGIN_MICROSOFT:
                menu.addAction("✓ 正版身份(Microsoft)", lambda: None)
                menu.addAction("以离线昵称游玩(保留正版凭证)", self._play_offline_keep_creds)
            else:
                menu.addAction("切换回正版(Microsoft,免重登)", self._use_microsoft_account)
                menu.addAction("✓ 离线昵称(保留正版凭证)", lambda: None)
        menu.addSeparator()

        # 二级操作
        if allow_offline:
            menu.addAction("🌐 换皮肤 / 我的账号", self._open_minecraft_account)
            menu.addAction("✏️ 设置离线昵称…", self._change_offline_name)
            menu.addAction("退出登录并清除凭证", self._logout_microsoft)
            menu.addSeparator()
        for _key, label, tip in _PLANNED_LOGIN:
            act = menu.addAction(label)
            act.setEnabled(False)
            act.setToolTip(tip)
        menu.addSeparator()

    def _build_ui(self):
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("loginCard")
        self.setMinimumHeight(164)
        set_style(self, lambda: f"#loginCard {{ {panel_style()} }}")

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
        self.login_btn.setText(t("VERSION_HOME_CHANGE_LOGIN"))
        self.login_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.login_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.setStyleSheet(
            f"QToolButton {{ color: {text_color()}; border: none; background: transparent;"
            f" padding: 2px 6px; border-radius: 6px; }}"
            f"QToolButton:hover {{ background: {hover_bg()}; }}")
        menu = QMenu(self.login_btn)
        self.login_btn.setMenu(menu)
        # 每次打开菜单前按当前状态重建,保证状态与菜单一致(切离线/正版后能正确反映)。
        menu.aboutToShow.connect(self._build_login_menu)
        self._build_login_menu()

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
            self.avatar_label.setPixmap(
                _server_avatar_pixmap(self._server, size) if self._server_mode
                else _avatar_pixmap(self._name or "Steve", size))
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
        if self._server_mode:
            return
        self._settings = load_settings()
        method = self._settings.get("login_method", LOGIN_OFFLINE)
        force_online = self._settings.get("microsoft_login", True)
        cred = self._settings.get("ms_credentials") or {}
        has_creds = bool(cred.get("uuid"))
        logged_in = (method == LOGIN_MICROSOFT) and has_creds
        if logged_in:
            name = cred.get("username", "Minecraft")
        elif has_creds:
            name = self._settings.get("username", "Steve") or "Steve"   # 离线昵称
        elif force_online:
            name = "未登录正版"
        else:
            name = self._settings.get("username", "Steve") or "Steve"
        self._name = name
        self.avatar_label.setPixmap(_avatar_pixmap(name, self._avatar_size))
        self.name_label.setText(name)
        # 状态文案
        if logged_in:
            self.status_label.setText(t("VERSION_HOME_MS_SIGNED_IN"))
        elif has_creds:
            self.status_label.setText("离线昵称(正版已保留,可切回)")
        elif force_online:
            self.status_label.setText("未登录正版 · 点上方登录")
        elif method == LOGIN_OFFLINE:
            self.status_label.setText(t("VERSION_HOME_OFFLINE_NAME_EDITABLE"))
        else:
            label = next((lbl for key, lbl, _tp in _LOGIN_METHODS if key == method),
                         "离线模式")
            self.status_label.setText(label)
        # 只要有正版 uuid 就尝试拉真实皮肤头像(异步,失败回退占位);
        # 离线保留凭证时也能显示皮肤头。
        if has_creds:
            self._fetch_avatar_async(cred.get("uuid", ""))

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
                    # 用 Signal 把字节送回主线程(Qt 自动 queued 到 GUI 线程);
                    # 不要在此线程直接建 QPixmap,会在 GUI 线程外失效。
                    self._avatar_ready.emit(data)
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _apply_avatar_bytes(self, data: bytes):
        """主线程根据字节构建/缩放 QPixmap 并设置到头像。"""
        if self._server_mode:
            return
        try:
            from PySide6.QtGui import QPixmap as _QPixmap
            from PySide6.QtCore import QByteArray as _QBA
            pm = _QPixmap()
            if pm.loadFromData(_QBA(data)) and not pm.isNull():
                self.avatar_label.setPixmap(
                    pm.scaled(self._avatar_size, self._avatar_size,
                              Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation))
        except Exception:
            pass

    def set_server_mode(self, server=None):
        self._server_mode = True
        self._server = server
        self.avatar_label.setPixmap(_server_avatar_pixmap(server, self._avatar_size))
        self.name_label.hide()
        self.status_label.hide()
        self.login_btn.hide()

    def set_player_mode(self):
        if not self._server_mode:
            return
        self._server_mode = False
        self._server = None
        self.name_label.show()
        self.status_label.show()
        self.login_btn.show()
        self.refresh()

    def refresh_visual(self):
        if self._server_mode:
            self.avatar_label.setPixmap(
                _server_avatar_pixmap(self._server, self._avatar_size))

    def _change_offline_name(self):
        """修改离线昵称(前端可自洽:写到 config.json 并通知启动器)。"""
        # 读取最新配置再改昵称,避免用启动时的旧快照覆盖用户改过的其他设置(如内存)
        cur = load_settings().get("username", "Steve")
        new, ok = QInputDialog.getText(self, t("VERSION_HOME_EDIT_OFFLINE_NAME_TITLE"),
                                       t("VERSION_HOME_OFFLINE_IN_GAME_NAME"),
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
        # 始终置顶:避免打开浏览器(常被设为全屏)后把本弹窗完全盖住,复制按钮点不到。
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dlg.setMinimumSize(520, 300)
        dl = QVBoxLayout(dlg)
        dl.addWidget(QLabel("<b>请在浏览器里打开下面的网址,并输入设备代码:</b>"))
        code_lbl = QLabel(f"<span style='font-size:28px;font-weight:bold;'>{user_code}</span>")
        code_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        code_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        url_lbl = QLabel(f"<span style='font-size:16px;'>{uri}</span>")
        url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        url_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        open_btn = QPushButton("▶ 打开浏览器授权")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(uri)))
        copy_btn = QPushButton("📋 复制代码到剪贴板")
        copy_btn.setToolTip("一键复制设备代码,在微软页面里粘贴即可")

        def _copy_code():
            try:
                QApplication.clipboard().setText(user_code)
                old = copy_btn.text()
                copy_btn.setText("已复制 ✓")
                QTimer.singleShot(1500, lambda: copy_btn.setText(old))
            except Exception:
                pass

        copy_btn.clicked.connect(_copy_code)
        dl.addWidget(code_lbl)
        dl.addWidget(url_lbl)
        btn_row = QHBoxLayout()
        btn_row.addWidget(copy_btn)
        btn_row.addWidget(open_btn)
        dl.addLayout(btn_row)
        wait = QLabel("登录过程中请保持此窗口打开;成功后自动关闭。")
        wait.setWordWrap(True); wait.setStyleSheet(f"color: {muted_color()};")
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

    def _open_minecraft_account(self):
        """打开官方 Minecraft 账号/换皮肤页面(正版皮肤只能在官网改)。"""
        QDesktopServices.openUrl(QUrl("https://www.minecraft.net/ms/account/profile"))

    def _logout_microsoft(self):
        """彻底退出登录:清除正版凭证并回离线。
        注意:这个会清掉凭证,之后想用正版需重新登录;
        只想过把离线瘾而不丢凭证,用 _play_offline_keep_creds。"""
        settings = load_settings()
        settings["login_method"] = LOGIN_OFFLINE
        settings["ms_credentials"] = {}
        save_settings(settings)
        self.refresh()
        self.changed.emit()

    def _play_offline_keep_creds(self):
        """以离线昵称游玩:切离线但他【保留】正版凭证,可一键切回免重登。"""
        settings = load_settings()
        if settings.get("login_method") != LOGIN_OFFLINE:
            settings["login_method"] = LOGIN_OFFLINE
            save_settings(settings)          # 注意:不清 ms_credentials
            self.refresh()
            self.changed.emit()

    def _use_microsoft_account(self):
        """用保留的正版凭证切回正版(免重登;启动时若 token 过期会自动刷新)。"""
        settings = load_settings()
        if settings.get("login_method") != LOGIN_MICROSOFT:
            settings["login_method"] = LOGIN_MICROSOFT
            save_settings(settings)
            self.refresh()
            self.changed.emit()

    def _set_offline(self):
        """切到离线昵称(正版玩家可选;保留正版凭证,便于切回)。

        保留此方法以防外部调用;等价于 _play_offline_keep_creds。"""
        settings = load_settings()
        if settings.get("login_method") != LOGIN_OFFLINE:
            settings["login_method"] = LOGIN_OFFLINE
            save_settings(settings)          # 注意:不清 ms_credentials
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
        set_style(self, lambda: f"#instCard {{ {panel_style()} }}")

        self.title = QLabel(t("VERSION_HOME_CURRENT_SELECTION"))
        self.title.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {muted_color()};")
        self.inst_label = QLabel(t("VERSION_HOME_NO_INSTANCE_SELECTED"))
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
            self.inst_label.setText(t("VERSION_HOME_NO_INSTANCE_SELECTED"))
        else:
            self.inst_label.setText(inst.get("name") or inst.get("id", "?"))

    def set_server(self, server: dict | None):
        self._inst = None
        self.title.setText('当前服务端')
        if not server:
            self.inst_label.setText('请选择一个服务端')
            return
        report = server.get('report') or {}
        entry = server.get('launchJar') or '自动识别启动入口'
        self.inst_label.setText(
            f"{server.get('name') or server.get('id', '?')}\n"
            f"{report.get('loader', 'unknown')} · MC {report.get('minecraftVersion') or '版本待确认'}\n"
            f"入口：{entry}")

    def set_client_mode(self, inst: dict | None):
        self.title.setText(t("VERSION_HOME_CURRENT_SELECTION"))
        self.set_instance(inst)


class VersionHome(QWidget):
    """「我的版本」首页(仿 PCL2)。"""

    open_instance_manager_requested = Signal(object)  # inst dict 或 None
    open_settings_requested = Signal()
    login_changed = Signal()
    one_click_config_requested = Signal(str)  # "bridge"/"rcon"/"auto" → 主窗口处理
    import_modpack_requested = Signal()       # 导入整合包
    open_resources_requested = Signal(int)    # 资源中心页:1新建游戏 / 3下载 Mod
    tutorial_requested = Signal()            # 打开新手教程
    instance_selected = Signal(object)       # 选中实例(或 None)→ 主窗口 显示/隐藏「实例详情」标签页
    refresh_requested = Signal()             # 切回「实例」标签页请求刷新(无刷新按钮,自动刷)
    launch_requested = Signal(object)        # 键盘回车启动选中实例(遥控器式导航)
    instance_details_requested = Signal()    # 左侧「实例详情」→ 主窗口切到详情页
    smart_import_requested = Signal(str)     # 指定路径的智能导入

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server_mode = False
        self._smart_import_enabled = False
        self._build_ui()
        self._on_selection_changed(None, None)
        # 更新日志已搬到「设置 → 系统 → 更新日志」按需打开(见 changelog_dialog),
        # 因此这里不再启动时预拉取:省一次网络请求,也少一个后台线程。

    # ---------- UI 搭建 ----------
    def _build_ui(self):
        main = QHBoxLayout(self)
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(14)
        self._left_panel = self._build_left()
        self._right_panel = self._build_right()
        # Ignore changing text size hints (for example “服务端管理”) so both
        # modes reuse the exact same 1:2 geometry without a one-frame jump.
        self._left_panel.setMinimumWidth(0)
        self._right_panel.setMinimumWidth(0)
        self._left_panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._right_panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        main.addWidget(self._left_panel, 1)
        main.addWidget(self._right_panel, 2)
        main.setStretch(0, 1)
        main.setStretch(1, 2)

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

        # 「实例详情」大入口:紧贴启动按钮上方。
        # 原先详情藏在主标签页里(选中实例才冒出来),用户根本找不到;这里改成
        # 与「启动」同一视觉层级的主入口。它占据原来第一行两个按钮的位置
        # (客户端原为 新建游戏/下载Mod,服务端原为 导入服务端/打开目录),
        # 因此按钮总数不变、也不需要新加按钮。
        self.details_btn = QPushButton("实例详情")
        self.details_btn.setToolTip("查看当前实例/服务端的详细信息、Mod、配置与日志")
        self.details_btn.setMinimumHeight(44)
        self.details_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_style(self.details_btn, card_btn_style)
        self.details_btn.clicked.connect(self.instance_details_requested.emit)
        lay.addWidget(self.details_btn)

        # 高频入口始终可见：不依赖 AI，也不用到多层菜单里找。
        quick_row = QHBoxLayout()
        quick_row.setSpacing(10)
        self.new_game_btn = QPushButton("新建游戏")
        self.new_game_btn.setToolTip("选择 Minecraft 版本和加载器，创建一个新游戏")
        self.find_mod_btn = QPushButton("下载 Mod")
        self.find_mod_btn.setToolTip("浏览、搜索并下载 Mod；也可进入整合包、光影和资源包页面")
        for btn in (self.new_game_btn, self.find_mod_btn):
            btn.setMinimumHeight(40)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            set_style(btn, card_btn_style)
            quick_row.addWidget(btn, 1)
        self.new_game_btn.clicked.connect(lambda: self._run_left_action('first'))
        self.find_mod_btn.clicked.connect(lambda: self._run_left_action('second'))
        lay.addLayout(quick_row)

        # 「导入整合包」(左)+「一键配置」(右)并排，属于次高频操作。
        tool_row = QHBoxLayout()
        tool_row.setSpacing(10)
        self.import_btn = QPushButton(t("VERSION_HOME_IMPORT_MODPACK"))
        self.import_btn.setMinimumHeight(44)
        self.import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_style(self.import_btn, card_btn_style)
        self.import_btn.clicked.connect(lambda: self._run_left_action('third'))
        tool_row.addWidget(self.import_btn, 1)
        self.config_btn = QToolButton()
        self.config_btn.setText(t("VERSION_HOME_ONE_CLICK"))
        self.config_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.config_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.config_btn.setMinimumHeight(44)
        self.config_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_style(self.config_btn, card_btn_style)
        cfg_menu = QMenu(self.config_btn)
        bridge_item = cfg_menu.addAction(
            t("VERSION_HOME_ONE_CLICK_BRIDGE"),
            lambda: self.one_click_config_requested.emit("bridge"))
        bridge_item.setToolTip("下载并安装 bridge-mod(游戏内指令口 / 数据导出),需加载器")
        rcon_item = cfg_menu.addAction(
            t("VERSION_HOME_ONE_CLICK_RCON"),
            lambda: self.one_click_config_requested.emit("rcon"))
        rcon_item.setToolTip("临时方案:需要 Lan Server Properties,进世界后按 ESC → 对局域网开放")
        # 联机 mod(Essential/e4mc):点击时由主窗口判断实例版本是否支持
        for sslug, sname in [("essential", "Essential(联机 mod)"), ("e4mc", "e4mc(局域网联机 mod)")]:
            it = cfg_menu.addAction(
                t(f"一键配置 {sname}", f"One-click {sname}"),
                lambda _c=False, s=sslug: self.one_click_config_requested.emit(s))
            it.setToolTip(f"{sname}:按所选实例的版本+加载器判断是否支持,支持才安装")
        self.config_btn.setMenu(cfg_menu)
        self._client_config_menu = cfg_menu
        tool_row.addWidget(self.config_btn, 1)
        lay.addLayout(tool_row)

        # 启动游戏大按钮
        self.launch_btn = QPushButton(t("VERSION_HOME_LAUNCH_GAME"))
        self.launch_btn.setMinimumHeight(56)
        self.launch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_style(self.launch_btn, launch_btn_style)
        self.launch_btn.clicked.connect(self._on_primary_launch)
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
        previous = self.game_dir_combo.blockSignals(True)
        try:
            self.game_dir_combo.clear()
            self.game_dir_combo.addItem(f"当前:{cur or '(默认)'}", cur)     # 0 当前
            for p in self._game_dirs():
                if p and p != cur:
                    self.game_dir_combo.addItem(p, p)
            self.game_dir_combo.insertSeparator(self.game_dir_combo.count())
            self.game_dir_combo.addItem("＋ 添加新路径…", "__add__")          # 最后一项 = 添加
        finally:
            # Rebuilding selects row 0. Without blocking, currentIndexChanged calls
            # _set_game_dir(), which rebuilds the combo again until the UI freezes.
            self.game_dir_combo.blockSignals(previous)

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
        d = QFileDialog.getExistingDirectory(
            self, "选择 MC 存储路径(.minecraft 目录)", start,
            QFileDialog.Option.DontUseNativeDialog)
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

    def _build_right(self) -> QWidget:
        """右列:标签页(版本 / 服务端 / 启动器日志)。

        更新日志已挪到「设置 → 系统 → 更新日志」(与「检查更新」相邻);MC 动态
        不再做(原先就是占位页,没有实际内容)。
        """
        right = QWidget()
        lay = QVBoxLayout(right)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        set_style(self.tabs, tab_style)

        self._version_tab_index = self.tabs.addTab(self._build_version_tab(), t("VERSION_HOME_INSTANCES"))
        from server_center import ServerCenter
        self.server_center = ServerCenter(self)
        self._server_tab_index = self.tabs.addTab(self.server_center, "服务端(共0个)")
        self.server_center.count_changed.connect(
            lambda count: self.tabs.setTabText(self._server_tab_index, f"服务端(共{count}个)"))
        self.server_center.selection_changed.connect(self._on_server_selection_changed)
        self.server_center.running_changed.connect(lambda _: self._update_server_launch_button())
        # 启动器日志:游戏运行输出/命令(与「版本」同级)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.tabs.addTab(self.log_view, t("VERSION_HOME_LAUNCHER_LOG"))
        # 切回「实例」标签页时自动刷新(不再有刷新按钮)
        self.tabs.currentChanged.connect(self._on_home_tab_changed)

        lay.addWidget(self.tabs)
        return right

    def set_instance_count(self, n: int):
        """把右列「实例」标签页文本更新为「实例(共x个)」。"""
        if hasattr(self, "tabs") and hasattr(self, "_version_tab_index"):
            self.tabs.setTabText(self._version_tab_index, t(f"实例(共{n}个)", f"Instances ({n})"))

    def _on_home_tab_changed(self, index: int):
        if index == self._server_tab_index:
            self._set_server_mode(self.server_center.selected())
        else:
            self._set_client_mode()
        if index == self._version_tab_index:
            self.refresh_requested.emit()

    def _server_manage_menu(self):
        menu = getattr(self, '_server_config_menu', None)
        if menu is not None:
            return menu
        menu = QMenu(self.config_btn)
        menu.addAction('手动指定启动 JAR（识别失败时）…', self.server_center.choose_launch_jar)
        menu.addAction('恢复自动识别启动入口', self.server_center.use_automatic_launch_entry)
        menu.addSeparator()
        menu.addAction('补全运行库…', self.server_center.install_runtime)
        menu.addAction('查看候选审核报告…', self.server_center.show_candidate_report)
        menu.addAction('导出可启动运行包（含运行库）…', self.server_center.export_runtime)
        menu.addAction('刷新服务端列表', self.server_center.refresh)
        self._server_config_menu = menu
        return menu

    def _set_server_mode(self, server=None):
        self._server_mode = True
        self.login_card.set_server_mode(server)
        self.inst_card.set_server(server)
        # 行2:打开目录 / 查看 Mod(与客户端「新建游戏 / 下载 Mod」同一位置)
        self.new_game_btn.setText('打开目录')
        self.new_game_btn.setToolTip('打开当前服务端目录')
        self.find_mod_btn.setText('查看 Mod')
        self.find_mod_btn.setToolTip('查看服务端 Mod 及适用端信息')
        # 行3:服务端管理(下拉) / 导入服务端 —— 即「查看 Mod」腾出来的位置
        self.import_btn.setText('服务端管理')
        self.import_btn.setToolTip('启动入口 / 运行库 / 审核报告 / 导出')
        self.import_btn.setMenu(self._server_manage_menu())
        self.config_btn.setText('导入服务端')
        self.config_btn.setMenu(self._import_menu())
        has_server = server is not None
        self.find_mod_btn.setEnabled(has_server)
        self.import_btn.setEnabled(has_server)
        self.config_btn.setEnabled(True)
        self.launch_btn.setEnabled(has_server)
        self._update_server_launch_button()

    def _import_menu(self):
        """「导入服务端」的下拉:严格扫描 / 智能导入。"""
        menu = getattr(self, '_import_menu_obj', None)
        if menu is not None:
            return menu
        menu = QMenu(self.config_btn)
        menu.addAction('导入服务端压缩包…', self._import_server)
        menu.addAction('智能导入(识别作者资料与服务端)…',
                       lambda: self._import_server(smart=True))
        self._import_menu_obj = menu
        return menu

    def _import_server(self, smart: bool = False):
        """选择服务端压缩包并交给服务端中心导入。"""
        import os
        from PySide6.QtWidgets import QFileDialog
        start = ''
        try:
            from paths import GAME_DIR
            candidate = os.path.join(GAME_DIR, 'downloads')
            if os.path.isdir(candidate):
                start = candidate
        except Exception:
            pass
        path, _f = QFileDialog.getOpenFileName(
            self, '选择服务端压缩包', start,
            '压缩包 (*.zip *.tar.gz);;所有文件 (*)')
        if not path:
            return
        if smart:
            self.smart_import_requested.emit(path)
            return
        self.server_center.scan_import(path)

    def _set_client_mode(self):
        self._server_mode = False
        self.login_card.set_player_mode()
        self.inst_card.set_client_mode(self.current_instance())
        self.new_game_btn.setText('新建游戏')
        self.new_game_btn.setToolTip('选择 Minecraft 版本和加载器，创建一个新游戏')
        self.find_mod_btn.setText('下载 Mod')
        self.find_mod_btn.setToolTip('浏览、搜索并下载 Mod；也可进入整合包、光影和资源包页面')
        self.import_btn.setText('智能导入' if self._smart_import_enabled
                                else t("VERSION_HOME_IMPORT_MODPACK"))
        self.import_btn.setToolTip(
            '智能识别客户端、服务端和作者资料；严格扫描仍然生效。'
            if self._smart_import_enabled else '')
        self.import_btn.setMenu(None)
        self.config_btn.setText(t("VERSION_HOME_ONE_CLICK"))
        self.config_btn.setMenu(self._client_config_menu)
        for button in (self.new_game_btn, self.find_mod_btn, self.import_btn, self.config_btn):
            button.setEnabled(True)
        self.launch_btn.setText(t("VERSION_HOME_LAUNCH_GAME"))
        self.launch_btn.setEnabled(self.current_instance() is not None)

    def set_smart_import_enabled(self, enabled):
        self._smart_import_enabled = bool(enabled)
        if not self._server_mode:
            self.import_btn.setText('智能导入' if enabled else t("VERSION_HOME_IMPORT_MODPACK"))
            self.import_btn.setToolTip(
                '智能识别客户端、服务端和作者资料；严格扫描仍然生效。' if enabled else '')

    def _on_server_selection_changed(self, server):
        if self.tabs.currentIndex() == self._server_tab_index:
            self._set_server_mode(server)

    def _update_server_launch_button(self):
        if not self._server_mode:
            return
        running = self.server_center.is_running()
        self.launch_btn.setText('停止服务端' if running else '启动服务端')
        server = self.server_center.selected()
        self.launch_btn.setToolTip(
            ('安全停止并保存世界' if running else
             ((server or {}).get('name') or '请先选择一个服务端')))

    def _run_left_action(self, slot):
        """左侧按钮动作。

        每个按钮有**固定职责**(不再按模式互换语义),这样信号槽不会串:
        - first  : 客户端=新建游戏  / 服务端=打开目录
        - second : 客户端=下载 Mod / 服务端=查看 Mod
        - third  : 导入整合包(客户端)
        - fourth : 导入服务端(两种模式都是同一个导入入口)
        """
        if self._server_mode:
            if slot == 'first':
                self.server_center.open_folder()
            elif slot == 'second':
                self.server_center.show_mods()
            # 'third'/'fourth' 在服务端模式是下拉菜单(服务端管理 / 导入服务端),
            # 由 QMenu 自己处理,不走这里。
            return
        if slot == 'first':
            self.open_resources_requested.emit(1)
        elif slot == 'second':
            self.open_resources_requested.emit(3)
        elif slot == 'third':
            self.import_modpack_requested.emit()
        elif slot == 'fourth':
            self._import_server()

    def _on_primary_launch(self):
        if self._server_mode:
            if self.server_center.is_running():
                self.server_center.stop()
            else:
                self.server_center.launch()
            return
        inst = self.current_instance()
        if inst is not None:
            self.launch_requested.emit(inst)

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

        from instance_drop_list import InstanceDropList
        self.instance_list = InstanceDropList()
        self.instance_list.ai_pin_provider = self._pin_instance
        self.instance_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)   # 逐像素滚动,触控板更顺
        set_style(self.instance_list, list_style)
        self.instance_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.instance_list.currentItemChanged.connect(self._on_selection_changed)
        # 键盘导航:上下方向键已在选择实例;回车(itemActivated)= 启动选中实例(遥控器式)
        self.instance_list.itemActivated.connect(self._launch_current_via_key)
        lay.addWidget(self.instance_list, 1)
        return w

    def _build_changelog_tab(self) -> QWidget:
        """已废弃:更新日志搬到「设置 → 系统 → 更新日志」(:mod:`changelog_dialog`)。

        保留这个空实现是为了兼容可能仍在调用它的旧代码/插件;新代码请直接用
        ``changelog_dialog.ChangelogDialog``。
        """
        w = QWidget()
        lay = QVBoxLayout(w)
        hint = QLabel('更新日志已移到「设置 → 系统 → 更新日志」。')
        hint.setWordWrap(True)
        hint.setStyleSheet(f'color:{muted_color()};')
        lay.addWidget(hint)
        return w    # ---------- 对外接口 ----------
    def refresh_login(self):
        """重新读取设置刷新登录卡片(昵称/头像)。"""
        self.login_card.refresh()

    def refresh_visual(self):
        """Refresh theme-dependent artwork without reloading account data."""
        self.login_card.refresh_visual()

    def set_current_instances(self, instances: list):
        """刷新实例数量(由 MainWindow.refresh_instances 调用)→ 更新「实例(共x个)」标签文本。"""
        self.set_instance_count(len(instances))
        self.server_center.refresh()

    def current_instance(self):
        """当前在「版本」列表里选中的实例 dict(没选返回 None)。"""
        item = self.instance_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _pin_instance(self, pos):
        """Capture the hovered instance, not whichever row is currently selected."""
        import os
        import paths
        item = self.instance_list.itemAt(self.instance_list.viewport().mapFromGlobal(pos))
        inst = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(inst, dict) or not inst.get("id"):
            return None
        directory = os.path.join(paths.GAME_DIR, "versions", inst["id"])
        return {"id": directory, "kind": "instance", "instance": inst["id"],
                "name": inst.get("name") or inst["id"], "directory": directory,
                "minecraft": inst.get("base") or inst["id"],
                "loader": inst.get("loader") or "vanilla"}

    # ---------- 内部逻辑 ----------
    def _on_selection_changed(self, current, _previous):
        """选中实例变化 → 更新「当前选择」卡片,并通知主窗口(显示/隐藏「实例详情」标签页)。"""
        inst = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        if not self._server_mode:
            self.inst_card.set_client_mode(inst)
            self.launch_btn.setToolTip(
                (inst.get("name") or inst.get("id", "")) if inst is not None else t("VERSION_HOME_SELECT_INSTANCE_FIRST"))
            self.launch_btn.setEnabled(inst is not None)
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
