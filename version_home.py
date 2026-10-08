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
from __future__ import annotations
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import (QBrush, QColor, QDesktopServices, QImageReader,
                           QPainter, QPixmap)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
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
from ui_style import (card_btn_style, current_color, hover_bg, launch_btn_style, list_style,
                      accent_color, is_dark_mode, muted_color, panel_style,
                      popup_menu_style, success_color, tab_style, text_color, set_style,
                      apply_card_shadow)

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
    """登录卡片：两种身份各有独立的可切换账号列表。"""

    changed = Signal()          # 昵称/登录方式变化 → 让启动器重读设置
    open_settings_requested = Signal()
    _avatar_ready = Signal(str, bytes)   # UUID + 头像，避免切换账号后显示旧头像

    def __init__(self, parent=None):
        super().__init__(parent)
        self._avatar_size = _AVATAR_BASE   # 当前头像尺寸(随窗口自适应)
        self._name = ""
        self._server_mode = False
        self._server = None
        self._avatar_ready.connect(self._apply_avatar_bytes)
        self._build_ui()
        self.refresh()

    def _build_login_menu(self, method):
        """在正版和离线按钮各自的下拉菜单中管理账号。"""
        menu = self.online_btn.menu() if method == LOGIN_MICROSOFT else self.offline_btn.menu()
        menu.clear()
        s = load_settings()
        from accounts import offline_names, microsoft_accounts
        if method == LOGIN_MICROSOFT:
            active = str((s.get('ms_credentials') or {}).get('uuid') or '').replace('-', '').lower()
            accounts = microsoft_accounts(s)
            for account in accounts:
                uuid = account['uuid']
                action = menu.addAction(account.get('username') or 'Minecraft')
                action.setCheckable(True)
                action.setChecked(str(uuid).replace('-', '').lower() == active)
                action.triggered.connect(lambda _checked=False, value=uuid: self._choose_microsoft_account(value))
            if accounts:
                menu.addSeparator()
            menu.addAction("添加正版账号…", self._do_microsoft_login)
            if active:
                menu.addAction("🌐 换皮肤 / 我的账号", self._open_minecraft_account)
                menu.addAction("移除当前正版账号…", self._logout_microsoft)
        else:
            current = str(s.get('username') or '')
            names = offline_names(s)
            for name in names:
                action = menu.addAction(name)
                action.setCheckable(True)
                action.setChecked(name == current)
                action.triggered.connect(lambda _checked=False, value=name: self._choose_offline_account(value))
            if names:
                menu.addSeparator()
            menu.addAction("添加离线账号…", self._add_offline_account)
            menu.addAction("修改当前离线昵称…", self._change_offline_name)
            remove_action = menu.addAction("移除当前离线账号…", self._remove_offline_account)
            remove_action.setEnabled(len(names) > 1)

    def _build_ui(self):
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("loginCard")
        self.setMinimumHeight(182)
        set_style(self, lambda: f"#loginCard {{ {panel_style()} }}")
        apply_card_shadow(self)

        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(self._avatar_size, self._avatar_size)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.name_label = QLabel()
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_style(self.name_label, lambda: f"font-weight: bold; font-size: 17px; color: {text_color()};")

        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_style(self.status_label, lambda: f"color: {muted_color()};")

        # 按钮正文快速切换；右侧箭头展开该方式的账号与管理操作。
        self.login_mode_group = QButtonGroup(self)
        self.login_mode_group.setExclusive(True)
        self.online_btn = QToolButton()
        self.offline_btn = QToolButton()
        self.online_btn.setText("正版")
        self.offline_btn.setText("离线")
        for button in (self.online_btn, self.offline_btn):
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.login_mode_group.addButton(button)
            set_style(button, lambda: (
                f"QToolButton {{ color: {text_color()}; background: {hover_bg()};"
                " border: none; padding: 5px 12px; border-radius: 7px; }"
                f"QToolButton:checked {{ color: {accent_color()}; font-weight: bold;"
                f" border: 1px solid {accent_color()}; }}"))
        for button, method in ((self.online_btn, LOGIN_MICROSOFT),
                               (self.offline_btn, LOGIN_OFFLINE)):
            menu = QMenu(button)
            set_style(menu, popup_menu_style)
            button.setMenu(menu)
            menu.aboutToShow.connect(lambda value=method: self._build_login_menu(value))
        self.online_btn.clicked.connect(self._select_online_mode)
        self.offline_btn.clicked.connect(self._select_offline_mode)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        mode_row.addWidget(self.online_btn, 1)
        mode_row.addWidget(self.offline_btn, 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 14, 12, 12)
        lay.setSpacing(6)
        lay.addWidget(self.avatar_label, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.name_label)
        lay.addWidget(self.status_label)
        lay.addLayout(mode_row)

    def _choose_microsoft_account(self, uuid):
        from accounts import select_microsoft
        select_microsoft(uuid)
        self.refresh()
        self.changed.emit()

    def _choose_offline_account(self, name):
        from accounts import select_offline
        select_offline(name)
        self.refresh()
        self.changed.emit()

    def _select_online_mode(self):
        settings = load_settings()
        if (settings.get('ms_credentials') or {}).get('uuid'):
            self._use_microsoft_account()
        else:
            from accounts import microsoft_accounts
            accounts = microsoft_accounts(settings)
            if accounts:
                self._choose_microsoft_account(accounts[0]['uuid'])
            else:
                self.refresh()
                self._do_microsoft_login()

    def _select_offline_mode(self):
        self._play_offline_keep_creds()

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
        if h >= 220:
            size = _AVATAR_BASE
        else:
            # 下方只保留昵称、状态与两个登录按钮。
            size = int(round(max(_AVATAR_MIN, min(_AVATAR_BASE, h - 115))))
        if size != self._avatar_size:
            self._avatar_size = size
            self.avatar_label.setFixedSize(size, size)
            self.avatar_label.setPixmap(
                _server_avatar_pixmap(self._server, size) if self._server_mode
                else _avatar_pixmap(self._name or "Steve", size))
        # 昵称字号跟随空间:头像很小(空间紧张)时缩小文字,恢复时回到默认
        if size <= 40:
            fs = max(12, int(size * 0.36))
            set_style(self.name_label, lambda fs=fs:
                      f"font-weight: bold; font-size: {fs}px; color: {text_color()};")
        else:
            set_style(self.name_label, lambda:
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
        allow_offline = (not force_online) or has_creds
        self.offline_btn.setEnabled(allow_offline)
        self.offline_btn.setToolTip("请先登录正版账号" if not allow_offline else "切换到离线昵称，保留正版凭证")
        self.online_btn.setChecked(method == LOGIN_MICROSOFT or not allow_offline)
        self.offline_btn.setChecked(method == LOGIN_OFFLINE and allow_offline)
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
            self.status_label.setText(t("VERSION_HOME_OFFLINE_NAME_EDITABLE"))
        elif force_online:
            self.status_label.setText("未登录正版 · 点下方“正版”登录")
        elif method == LOGIN_OFFLINE:
            self.status_label.setText(t("VERSION_HOME_OFFLINE_NAME_EDITABLE"))
        else:
            label = next((lbl for key, lbl, _tp in _LOGIN_METHODS if key == method),
                         "离线模式")
            self.status_label.setText(label)
        # 正版模式显示当前账号的皮肤；迟到的旧账号头像会被忽略。
        if logged_in:
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
                    self._avatar_ready.emit(uuid_str, data)
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _apply_avatar_bytes(self, uuid_str: str, data: bytes):
        """主线程根据字节构建/缩放 QPixmap 并设置到头像。"""
        if (self._server_mode or self._settings.get("login_method") != LOGIN_MICROSOFT
                or (self._settings.get("ms_credentials") or {}).get("uuid") != uuid_str):
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
        self.name_label.setText("Server")
        self.name_label.show()
        self.status_label.hide()
        self.online_btn.hide()
        self.offline_btn.hide()

    def set_player_mode(self):
        if not self._server_mode:
            return
        self._server_mode = False
        self._server = None
        self.name_label.show()
        self.status_label.show()
        self.online_btn.show()
        self.offline_btn.show()
        self.refresh()

    def refresh_visual(self):
        if self._server_mode:
            self.avatar_label.setPixmap(
                _server_avatar_pixmap(self._server, self._avatar_size))

    def _change_offline_name(self):
        """修改当前离线账号的昵称，保留其他离线账号。"""
        from accounts import offline_names
        from settings import update_settings
        cur = load_settings().get("username", "Steve")
        new, ok = QInputDialog.getText(self, t("VERSION_HOME_EDIT_OFFLINE_NAME_TITLE"),
                                       t("VERSION_HOME_OFFLINE_IN_GAME_NAME"),
                                       text=cur)
        if not ok:
            return
        new = new.strip()
        if not self._valid_offline_name(new):
            return
        names = offline_names(load_settings())
        if new.casefold() != cur.casefold() and any(
                name.casefold() == new.casefold() for name in names):
            QMessageBox.information(self, "昵称已存在", "这个离线昵称已在列表中，直接从下拉框切换即可。")
            return
        def change(settings):
            settings["offline_accounts"] = [new if item.casefold() == cur.casefold() else item
                                            for item in offline_names(settings)]
            settings["username"] = new
        update_settings(change)
        self.refresh()
        self.changed.emit()

    def _valid_offline_name(self, name):
        import re
        if re.fullmatch(r"[A-Za-z0-9_]{3,16}", name or ""):
            return True
        QMessageBox.warning(self, "离线昵称无效", "昵称需为 3–16 位英文字母、数字或下划线。")
        return False

    def _add_offline_account(self):
        from accounts import offline_names, select_offline
        name, ok = QInputDialog.getText(self, "添加离线账号", "游戏内昵称（3–16 位）：")
        if not ok:
            return
        name = name.strip()
        if not self._valid_offline_name(name):
            return
        if any(existing.casefold() == name.casefold() for existing in offline_names(load_settings())):
            QMessageBox.information(self, "昵称已存在", "这个昵称已在列表中，直接从下拉框切换即可。")
            return
        select_offline(name)
        self.refresh()
        self.changed.emit()

    def _remove_offline_account(self):
        from accounts import remove_offline
        name = load_settings().get("username", "Steve")
        if QMessageBox.question(self, "移除离线账号",
                f"从启动器移除离线昵称 {name}？存档文件不会删除。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        remove_offline(name)
        self.refresh()
        self.changed.emit()

    # ---- 微软正版登录 ----
    def _do_microsoft_login(self):
        """后台申请设备码、轮询授权；慢网络不阻塞启动器界面。"""
        from microsoft_auth import MsAuth
        from PySide6.QtCore import QObject, Signal as _Sig, QTimer

        class _Bridge(QObject):
            code_ready = _Sig(object)
            done = _Sig(object)
            fail = _Sig(str)

        bridge = _Bridge(self)
        auth = MsAuth()
        state = {"code": "", "url": "", "closed": False}
        dlg = QDialog(self)
        dlg.setWindowTitle("微软登录 · 请在浏览器完成授权")
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dlg.setMinimumSize(520, 300)
        dl = QVBoxLayout(dlg)
        title = QLabel("正在连接微软账号服务…")
        title.setWordWrap(True)
        dl.addWidget(title)
        code_lbl = QLabel("")
        code_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        code_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        url_lbl = QLabel("")
        url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        url_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        dl.addWidget(code_lbl)
        dl.addWidget(url_lbl)
        btn_row = QHBoxLayout()
        copy_btn = QPushButton("复制代码")
        open_btn = QPushButton("打开授权页面")
        copy_btn.setEnabled(False)
        open_btn.setEnabled(False)
        btn_row.addWidget(copy_btn)
        btn_row.addWidget(open_btn)
        dl.addLayout(btn_row)
        wait = QLabel("网络慢时可能需要稍等。授权网页也可在手机上打开，启动器仍需连接微软与 Minecraft 服务。")
        wait.setWordWrap(True)
        wait.setStyleSheet(f"color: {muted_color()};")
        dl.addWidget(wait)
        close_btn = QPushButton("取消")
        close_btn.clicked.connect(dlg.reject)
        dl.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)

        def code_ready(info):
            if state["closed"]:
                return
            state["code"] = info.get("user_code", "")
            state["url"] = info.get("verification_uri", "")
            title.setText("请在浏览器输入设备代码，授权后保持此窗口打开：")
            code_lbl.setText(f"<span style='font-size:28px;font-weight:bold;'>{state['code']}</span>")
            url_lbl.setText(state["url"])
            copy_btn.setEnabled(True)
            open_btn.setEnabled(True)
            if state["url"]:
                QDesktopServices.openUrl(QUrl(state["url"]))

        def finish(result):
            if state["closed"]:
                return
            dlg.accept()
            self._finish_ms_login(result)

        def failed(message):
            if state["closed"]:
                return
            dlg.reject()
            QMessageBox.warning(self, "微软登录", message)

        bridge.code_ready.connect(code_ready)
        bridge.done.connect(finish)
        bridge.fail.connect(failed)
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(state["code"]))
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(state["url"])))

        def worker():
            try:
                info = auth.start_device_code()
                if state["closed"]:
                    return
                bridge.code_ready.emit(info)
                result = auth.await_token()
                if not state["closed"]:
                    bridge.done.emit(result)
            except Exception as error:
                if not state["closed"]:
                    bridge.fail.emit(f"{error}\n\n请确认能连接 login.live.com、Xbox Live 和 Minecraft 服务；网络较慢时可稍后重试。")

        threading.Thread(target=worker, daemon=True).start()
        dlg.exec()
        state["closed"] = True
        auth.cancel()

    def _finish_ms_login(self, result: dict):
        """登录成功：按 UUID 加入正版账号列表，并设为当前账号。"""
        from accounts import save_microsoft_login
        save_microsoft_login(result)
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
        """只移除当前正版账号，其他正版账号及存档不受影响。"""
        from accounts import remove_microsoft
        account = load_settings().get("ms_credentials") or {}
        uuid = account.get("uuid")
        if not uuid:
            return
        if QMessageBox.question(self, "移除正版账号",
                f"从本机移除 {account.get('username') or '当前账号'} 的登录凭证？再次使用需要重新授权。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        remove_microsoft(uuid)
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
    """当前实例卡片:显示选中的实例关键信息,**点击进入详情**。

    详情入口从「顶部标签页」收敛到这张卡片——卡片本来就是「当前选择」的展示区,
    点它看详情符合直觉,也不用再占一行按钮。
    """

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._inst = None
        self._build_ui()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('点击查看当前实例 / 服务端的详情')

    def mouseReleaseEvent(self, event):
        """整张卡片可点(左键);其它按键交给基类,避免抢掉右键菜单之类。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _build_ui(self):
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("instCard")
        set_style(self, lambda: f"#instCard {{ {panel_style()} }}")
        apply_card_shadow(self)

        self.title = QLabel(t("VERSION_HOME_CURRENT_SELECTION"))
        set_style(self.title, lambda: f"font-weight: bold; font-size: 13px; color: {muted_color()};")
        self.inst_label = QLabel(t("VERSION_HOME_NO_INSTANCE_SELECTED"))
        self.inst_label.setWordWrap(True)
        set_style(self.inst_label, lambda: f"font-weight: bold; font-size: 14px; color: {text_color()};")

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

        # 当前实例卡片:点击即进入详情(详情入口不再占用按钮行)
        self.inst_card = InstanceSettingsCard()
        self.inst_card.clicked.connect(self.instance_details_requested.emit)
        lay.addWidget(self.inst_card)

        lay.addStretch(1)

        # 「实例详情」按钮:紧贴启动按钮上方,按模式路由(客户端实例 / 服务端)。
        # 行2(新建游戏 / 下载 Mod)已移除:这两个功能在「下载新资源」页本就有,
        # 新手教程会说明;少一行按钮让左列更清爽。
        self.details_btn = QPushButton("实例详情")
        self.details_btn.setToolTip("查看当前实例/服务端的详细信息、Mod、配置与日志")
        self.details_btn.setMinimumHeight(44)
        self.details_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_style(self.details_btn, card_btn_style)
        self.details_btn.clicked.connect(self.instance_details_requested.emit)
        lay.addWidget(self.details_btn)

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
        self.config_btn.setText(t("VERSION_HOME_ONE_CLICK").rstrip(" ▾▼"))
        self.config_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.config_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.config_btn.setMinimumHeight(44)
        self.config_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_style(self.config_btn, card_btn_style)
        cfg_menu = QMenu(self.config_btn)
        set_style(cfg_menu, popup_menu_style)
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
        self.launch_btn.setObjectName("launch_game_button")
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
        self.server_center.details_requested.connect(self.instance_details_requested.emit)
        self.server_center.running_changed.connect(lambda _: self._update_server_launch_button())
        # 日志由主窗口状态球详情承载，保留同一个 view 接收实时输出。
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        # 切回「实例」标签页时自动刷新(不再有刷新按钮)
        self.tabs.currentChanged.connect(self._on_home_tab_changed)

        lay.addWidget(self.tabs)
        return right

    def set_instance_count(self, n: int):
        """把右列「实例」标签页文本更新为「实例(共x个)」。"""
        if hasattr(self, "tabs") and hasattr(self, "_version_tab_index"):
            self.tabs.setTabText(self._version_tab_index, t(f"实例(共{n}个)", f"Instances ({n})"))

    def _on_home_tab_changed(self, index: int):
        from ui_anim import reveal
        reveal(self.tabs.widget(index))
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
        set_style(menu, popup_menu_style)
        menu.addAction('打开服务端文件夹', self.server_center.open_folder)
        menu.addSeparator()
        menu.addAction('手动指定启动 JAR（识别失败时）…', self.server_center.choose_launch_jar)
        menu.addAction('恢复自动识别启动入口', self.server_center.use_automatic_launch_entry)
        menu.addSeparator()
        menu.addAction('补全运行库…', self.server_center.install_runtime)
        menu.addAction('查看候选审核报告…', self.server_center.show_candidate_report)
        menu.addAction('启动测试并逐项修复…', self.server_center.start_repair_test)
        menu.addAction('恢复本次测试停用的 Mod…', self.server_center.restore_repair_mods)
        menu.addAction('导出可启动运行包（含运行库）…', self.server_center.export_runtime)
        menu.addAction('刷新服务端列表', self.server_center.refresh)
        self._server_config_menu = menu
        return menu

    def _set_server_mode(self, server=None):
        self._server_mode = True
        self.login_card.set_server_mode(server)
        self.inst_card.set_server(server)
        # 行2(打开目录 / 查看 Mod)已移除:行3 的「服务端管理」下拉里本就有
        # 「打开服务端目录」,「查看 Mod」走右侧服务端详情的 Mod 页。
        self.import_btn.setText('服务端管理')
        self.import_btn.setToolTip('启动入口 / 运行库 / 审核报告 / 导出')
        self.import_btn.setMenu(self._server_manage_menu())
        self.config_btn.setText('导入服务端')
        self.config_btn.setMenu(self._import_menu())
        has_server = server is not None
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
        set_style(menu, popup_menu_style)
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
        # 行2 已移除(新建游戏 / 下载 Mod → 都在「下载新资源」页,教程会说明)。
        self.import_btn.setText('智能导入' if self._smart_import_enabled
                                else t("VERSION_HOME_IMPORT_MODPACK"))
        self.import_btn.setToolTip(
            '智能识别客户端、服务端和作者资料；严格扫描仍然生效。'
            if self._smart_import_enabled else '')
        self.import_btn.setMenu(None)
        self.config_btn.setText(t("VERSION_HOME_ONE_CLICK").rstrip(" ▾▼"))
        self.config_btn.setMenu(self._client_config_menu)
        for button in (self.import_btn, self.config_btn):
            button.setEnabled(True)
        self._update_client_launch_target(self.current_instance())

    def _update_client_launch_target(self, inst):
        """Keep the primary action visibly tied to the selected instance."""
        name = (inst or {}).get("name") or (inst or {}).get("id", "")
        self.launch_btn.setText(t("VERSION_HOME_LAUNCH_GAME"))
        self.launch_btn.setToolTip(f"将启动：{name}" if name else t("VERSION_HOME_SELECT_INSTANCE_FIRST"))
        self.launch_btn.setEnabled(inst is not None)

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
        """左侧按钮动作(行2 已移除,现在只剩导入整合包走这里)。

        - third : 导入整合包(客户端)
        服务端的两个按钮都是下拉菜单,不需要在这里派发。
        """
        if self._server_mode:
            return
        if slot == 'third':
            self.import_modpack_requested.emit()

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

        self.instance_list = InstanceDropList()
        self.instance_list.ai_pin_provider = self._pin_instance
        self.instance_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)   # 逐像素滚动,触控板更顺
        set_style(self.instance_list, lambda: list_style() +
                  f"QListWidget::item:selected:hover {{ background: {current_color('sel_bg')};"
                  f" border: 1px solid {current_color('accent')}; }}"
                  f"QListWidget::item:selected {{ border: 1px solid {current_color('accent')}; }}")
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
            self._update_client_launch_target(inst)
        self.instance_selected.emit(inst)

    def _launch_current_via_key(self, item):
        """键盘导航:实例列表里按 Enter → 启动选中实例(遥控器式)。
        itemActivated 在回车/双击时触发。"""
        inst = item.data(Qt.ItemDataRole.UserRole)
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


# ===================== Merged from instance_drop_list.py =====================
import os
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QListWidget


class InstanceDropList(QListWidget):
    folders_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setToolTip('可以拖入已有实例文件夹，复制导入并保留原文件')

    @staticmethod
    def folders(event):
        urls = event.mimeData().urls()
        if not urls or not all(u.isLocalFile() and os.path.isdir(u.toLocalFile()) for u in urls):
            return []
        return list(dict.fromkeys(u.toLocalFile() for u in urls))

    def dragEnterEvent(self, event):
        if self.folders(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        folders = self.folders(event)
        if folders:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.folders_dropped.emit(folders)
        else:
            event.ignore()
