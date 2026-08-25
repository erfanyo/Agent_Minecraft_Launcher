# -*- coding: utf-8 -*-
"""
设置中心(顶部标签卡版):左菜单(游戏/界面/AI助手/镜像源)+ 右侧面板,复用 CenterShell,
和「下载新资源」同一套布局/操作逻辑。解决原「设置弹窗(模态)」挡住引导遮罩的问题。

保存:底部「保存设置」按钮 → 收集各面板 → save_settings → 发射 applied。
"""
import threading
import uuid

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from assistant import AISettingsForm
from center_shell import CenterShell
from downloader import MIRROR_SOURCES, MIRROR_STRATEGIES
from i18n import t
from paths import DEFAULT_GAME_DIR
from settings import save_settings
from ui_style import (card_btn_style, muted_color, set_style,
                      COLOR_BLIND_PRESETS, check_readability, panel_style, text_color)


def _fmt_mcp_entry(c: dict) -> str:
    """把配置里的 MCP 客户端项转成设置文本框里的一行。
    HTTP → url;stdio → 名字>=命令。"""
    if (c.get("transport") or "http").strip().lower() in ("stdio", "local", "command", "process"):
        command = c.get("command")
        if isinstance(command, list):
            import shlex
            command = shlex.join([str(x) for x in command])
        return f"{c.get('name', 'mcp')}>={command or ''}"
    return c.get("url", "")


def _parse_mcp_entries(text: str) -> list:
    """解析设置文本框里的 MCP 客户端(用 ; 分隔,兼容旧用逗号)。
    "http://…/mcp"            → {"name":"mcpN","transport":"http","url":…}
    "名字>=uvx mc-wiki-mcp"    → {"name":"名字","transport":"stdio","command":["uvx","mc-wiki-mcp"]}"""
    entries = []
    raw = (text or "").replace(",", ";")   # 兼容旧格式(逗号分隔)
    for i, line in enumerate(raw.split(";")):
        line = line.strip()
        if not line:
            continue
        if ">=" in line:
            nm, cmd = line.split(">=", 1)
            nm = nm.strip() or f"mcp{i + 1}"
            # 拆命令:支持带引号(如含空格的 python 路径)
            import shlex
            try:
                cmd_list = shlex.split(cmd.strip())
            except Exception:
                cmd_list = [cmd.strip()] if cmd.strip() else []
            if cmd_list:
                entries.append({"name": nm, "transport": "stdio", "command": cmd_list})
        else:
            nm = f"mcp{i + 1}"
            # 判断是否 http
            url = line.strip()
            entries.append({"name": nm, "transport": "http", "url": url})
    return entries


class ToggleSwitch(QWidget):
    """iOS 风格开关(替代 QCheckBox):可点击切换,checked 状态用颜色区分。
    用 clicked(checked_forwards) 信号替代 QCheckBox.toggled。"""
    toggled = Signal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(46, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, v: bool):
        if self._checked != v:
            self._checked = v
            self.update()
            self.toggled.emit(v)

    def mousePressEvent(self, e):
        self.setChecked(not self._checked)

    def paintEvent(self, _):
        from PySide6.QtGui import QColor, QPainter
        from PySide6.QtCore import Qt as _Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QColor("#5B8DEF") if self._checked else QColor("#444a56")
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(track)
        p.drawRoundedRect(0, 0, 46, 24, 12, 12)
        # 圆点
        p.setBrush(QColor("#ffffff"))
        x = 25 if self._checked else 5
        p.drawEllipse(x, 4, 16, 16)
        p.end()


class SettingsCenter(QWidget):
    applied = Signal()   # 保存后发出,主窗口据此刷新(set_ui_mode / ai_dock 等)
    _dl_progress = Signal(int, int)
    _dl_finished = Signal(bool, str)

    def __init__(self, settings: dict, parent=None, initial_tab: str | None = None):
        super().__init__(parent)
        self.settings = dict(settings)
        self._custom_mirrors = [dict(c) for c in self.settings.get("custom_mirrors", []) or []]
        self._model_downloading = False
        self._dl_progress.connect(self._on_model_dl_progress)
        self._dl_finished.connect(self._on_model_dl_finished)

        self.shell = CenterShell(self, menu_width=150)
        self.shell.add_section(t("游戏", "Game"), self._build_game)
        self.shell.add_section(t("界面", "UI"), self._build_ui)
        self.shell.add_section(t("AI 助手", "AI"), self._build_ai)
        self.shell.add_section(t("镜像源", "Mirror"), self._build_mirror)
        self.shell.add_section(t("插件", "Plugins"), self._build_plugins)
        # 插件注册的独立设置页:在左菜单【各单开一行】(按插件名)。
        # 只在插件【启用】时才加(关闭/默认关未启用的插件不占菜单);可用齿轮从插件页进入,或启用后出现。
        self._plugin_settings_rows = []
        try:
            import plugin_manager
            disabled = set(self.settings.get("plugins_disabled", []) or [])
            enabled_override = set(self.settings.get("plugins_enabled", []) or [])
            pm_meta = plugin_manager.discover_plugins_meta()
            for pid in sorted(pm_meta.keys()):
                if not pm_meta[pid].get("has_settings"):
                    continue
                default_on = pm_meta[pid].get("default_enabled", True)
                is_on = (pid not in disabled) and (default_on or pid in enabled_override)
                if not is_on:
                    continue   # 未启用 → 不显示设置行
                build_fn = plugin_manager.plugin_settings_page(pid)
                if build_fn:
                    self.shell.add_section(t(f"插件:{pm_meta[pid].get('name') or pid}"),
                                           lambda p=pid, b=build_fn: self._plugin_page_with_toggle(p, b))
                    self._plugin_settings_rows.append(pid)
        except Exception:
            pass
        if initial_tab:
            self.shell.switch_by_label(initial_tab)

        save_btn = QPushButton(t("保存设置", "Save settings"))
        set_style(save_btn, card_btn_style)
        save_btn.setMinimumHeight(38)
        save_btn.clicked.connect(self.apply)
        self._save_btn = save_btn

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.shell, 1)
        lay.addWidget(save_btn)

    # ================= 游戏 =================
    def _build_game(self) -> QWidget:
        self.username_edit = QLineEdit(self.settings.get("username", "Player"))
        self.username_edit.setPlaceholderText("离线模式显示的游戏名")
        self.memory_spin = QSpinBox()
        self.memory_spin.setRange(1, 16)
        self.memory_spin.setSuffix(" GB")
        self.memory_spin.setValue(self.settings.get("memory_gb", 2))
        self.isolation_check = QCheckBox("每个版本用独立游戏目录(存档/配置/Mod 互不干扰)")
        self.isolation_check.setChecked(self.settings.get("version_isolation", True))
        self.game_dir_edit = QLineEdit(self.settings.get("game_dir") or DEFAULT_GAME_DIR)
        browse_btn = QPushButton("浏览…"); browse_btn.clicked.connect(self._browse_game_dir)
        default_btn = QPushButton("默认"); default_btn.clicked.connect(
            lambda: self.game_dir_edit.setText(DEFAULT_GAME_DIR))
        dir_row = QHBoxLayout(); dir_row.addWidget(self.game_dir_edit, 1)
        dir_row.addWidget(browse_btn); dir_row.addWidget(default_btn)

        form = QFormLayout()
        form.addRow("游戏名:", self.username_edit)
        form.addRow("内存:", self.memory_spin)
        form.addRow("版本隔离:", self.isolation_check)
        form.addRow("游戏目录:", dir_row)
        hint = QLabel("可以是任意位置,包括 PCL2 / 官方启动器创建的 .minecraft(自动读取里面的实例)")
        hint.setWordWrap(True); hint.setStyleSheet("color: #888888;")
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(16, 12, 16, 12)
        l.addLayout(form); l.addWidget(hint); l.addStretch()
        return w

    def _browse_game_dir(self):
        from PySide6.QtWidgets import QFileDialog
        start = self.game_dir_edit.text().strip() or DEFAULT_GAME_DIR
        d = QFileDialog.getExistingDirectory(self, "选择 Minecraft 游戏目录", start)
        if d:
            self.game_dir_edit.setText(d)

    # ================= 界面 =================
    @staticmethod
    def _wrap_scroll(w) -> QScrollArea:
        """把页面内容包进滚动区(纵向内容多时可用滚动条,不拥挤)。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(w)
        return scroll

    def _build_ui(self) -> QWidget:
        self.language_combo = QComboBox()
        for label, value in (("自动(跟随系统)", "auto"), ("中文", "zh"), ("English", "en")):
            self.language_combo.addItem(label, value)
        # 可选语言包(第三方/玩梗):从这里选能整包换肤
        try:
            import i18n
            for pid, meta in i18n.list_packs().items():
                self.language_combo.addItem(f"语言包:{meta['name']}({pid})", pid)
        except Exception:
            pass
        idx = self.language_combo.findData(self.settings.get("language", "auto"))
        if idx < 0:
            idx = self.language_combo.findData("auto")
        self.language_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.ui_mode_combo = QComboBox()
        for label, value in ((t("全面(显示更多提示与科普)", "Full (more tips & guides)"), "beginner"),
                             (t("摘要(精简提示)", "Summary (concise)"), "expert")):
            self.ui_mode_combo.addItem(label, value)
        idx = self.ui_mode_combo.findData(self.settings.get("ui_mode", "beginner"))
        self.ui_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        mode_hint = QLabel("全面:首页显示资源结构科普、更详细的状态提示;摘要:隐藏科普、精简提示。")
        mode_hint.setWordWrap(True); mode_hint.setStyleSheet("color: #888888;")

        form = QFormLayout()
        form.addRow("界面语言:", self.language_combo)
        form.addRow("界面模式:", self.ui_mode_combo)
        form.addRow("", mode_hint)

        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(16, 12, 16, 12)
        l.addLayout(form)
        l.addSpacing(8)
        # 已临时弃用 / 废案功能登记
        from deprecated_features import get_deprecated
        for d in get_deprecated():
            info = QLabel(f"<b>{d.get('name')}</b>  ·  状态:{d.get('status','')}<br>"
                          f"<span style='color:#8a93a0;'>{d.get('note','')}</span>")
            info.setWordWrap(True); info.setTextFormat(Qt.TextFormat.RichText)
            row = QHBoxLayout(); row.addWidget(info, 1)
            if d.get("reopen") == "tutorial":
                open_btn = QPushButton("临时查看"); set_style(open_btn, card_btn_style)
                open_btn.clicked.connect(self._reopen_tutorial); row.addWidget(open_btn)
            l.addLayout(row)
        # 检查更新 / 重播引导教程(原在菜单栏,现并入设置 → 界面;重播按钮不放在最外层)
        l.addSpacing(8)
        upd_btn = QPushButton(t("检查更新…", "Check for Updates…"))
        tut_btn = QPushButton(t("重播引导教程", "Replay guided tutorial"))
        for b in (upd_btn, tut_btn):
            set_style(b, card_btn_style); b.setMinimumHeight(32)
        upd_btn.clicked.connect(self._open_update)
        tut_btn.clicked.connect(self._open_guide)
        more_row = QHBoxLayout(); more_row.addWidget(upd_btn); more_row.addWidget(tut_btn); more_row.addStretch()
        l.addLayout(more_row)

        # 配色(自定义主题):改 强调色/文字色/背景色
        l.addSpacing(12)
        theme_title = QLabel("🎨 配色(自定义主题,文字颜色也可以改):")
        theme_title.setStyleSheet(f"font-weight:bold; color:{muted_color()};")
        l.addWidget(theme_title)
        self._color_btns = {}
        cbtn_row = QHBoxLayout(); cbtn_row.setSpacing(8)
        for slot, label in [("accent", "强调色"), ("text", "文字色"), ("panel_bg", "背景色")]:
            b = QPushButton(label)
            set_style(b, card_btn_style)
            b.clicked.connect(lambda _c, s=slot, lb=label: self._pick_color(s, lb))
            cbtn_row.addWidget(b, 1)
            self._color_btns[slot] = b
        reset_btn = QPushButton("重置默认"); set_style(reset_btn, card_btn_style)
        reset_btn.clicked.connect(self._reset_colors)
        cbtn_row.addWidget(reset_btn)
        l.addLayout(cbtn_row)
        color_hint = QLabel("配色改完**立即覆盖整个启动器**(实时上色,不用等重启);当前设置页同步预览。")
        color_hint.setWordWrap(True); color_hint.setStyleSheet("color:#8a93a0;")
        l.addWidget(color_hint)
        # 色盲/色弱友好模板(为无障碍预设,一键应用)
        cb_row = QHBoxLayout(); cb_row.setSpacing(8)
        cb_row.addWidget(QLabel("配色模板(无障碍):"))
        self._cb_combo = QComboBox()
        self._cb_combo.addItem("(无)", "")
        for _name in COLOR_BLIND_PRESETS:
            self._cb_combo.addItem(_name, _name)
        cb_row.addWidget(self._cb_combo, 1)
        apply_cb_btn = QPushButton("应用模板")
        set_style(apply_cb_btn, card_btn_style); apply_cb_btn.setMinimumHeight(32)
        apply_cb_btn.clicked.connect(self._apply_cb_preset)
        cb_row.addWidget(apply_cb_btn)
        l.addLayout(cb_row)
        # 可读性提示(改色后检查文字/强调色是否看不清)
        self._readability_label = QLabel("")
        self._readability_label.setWordWrap(True)
        l.addWidget(self._readability_label)
        self._refresh_color_btn_text()
        # 缓存管理:清除 Mod 图片/描述缓存(换新图/翻译更新时用)
        l.addSpacing(12)
        cache_title = QLabel("🗂 缓存(Mod 图片 & 描述翻译):")
        cache_title.setStyleSheet(f"font-weight:bold; color:{muted_color()};")
        l.addWidget(cache_title)
        cache_hint = QLabel("图片/描述按 Mod 名缓存(不同版本同一 Mod 复用)。若某 Mod 更新了图标或想重翻描述,清除后重新打开该 Mod 即可。")
        cache_hint.setWordWrap(True); cache_hint.setStyleSheet("color:#8a93a0;")
        l.addWidget(cache_hint)
        cache_row = QHBoxLayout(); cache_row.setSpacing(8)
        clear_icon_btn = QPushButton("清除图片缓存"); set_style(clear_icon_btn, card_btn_style); clear_icon_btn.setMinimumHeight(32)
        clear_icon_btn.clicked.connect(lambda: self._clear_cache("icons"))
        clear_desc_btn = QPushButton("清除描述翻译缓存"); set_style(clear_desc_btn, card_btn_style); clear_desc_btn.setMinimumHeight(32)
        clear_desc_btn.clicked.connect(lambda: self._clear_cache("desc"))
        cache_row.addWidget(clear_icon_btn)
        cache_row.addWidget(clear_desc_btn)
        l.addLayout(cache_row)
        l.addStretch()
        return self._wrap_scroll(w)

    def _copy_mcp_link(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(getattr(self, "_mcp_url", ""))
        if hasattr(self, "_mcp_status"):
            self._mcp_status.setText("已复制 HTTP 链接 → 客户端「http」选项填它")

    def _clear_cache(self, kind: str):
        """清除 Mod 图片/描述缓存:kind='icons' 或 'desc'。清完提示删了多少个。"""
        try:
            import image_cache
            if kind == "icons":
                n = image_cache.clear_icons()
                msg = f"已清除 {n} 个图片缓存。"
            else:
                n = image_cache.clear_desc()
                msg = f"已清除 {n} 条描述翻译缓存。"
            QMessageBox.information(self, "清除缓存", msg)
        except Exception as e:
            QMessageBox.warning(self, "清除缓存", f"清除失败:{type(e).__name__}: {e}")

    def _gen_mcp_files(self):
        """生成 MCP 连接/客户端配置文件,写到启动器创建的 AMCL 文件夹。"""
        import json as _json, os as _os, paths as _paths
        cfg = {
            "name": "amcl",
            "transport": "http",
            "http_url": self._mcp_url,
            "stdio": {"command": self._mcp_pyexe, "args": [self._mcp_main_py, "--mcp"]},
            "command": f'"{self._mcp_pyexe}" "{self._mcp_main_py}" --mcp-http 8766',
            "note": "客户端选 http → 用 http_url;选 本地命令/stdio → 用 stdio 的 command+args;"
                    "或在本机该命令行启动。",
        }
        d = _paths.CONFIG_DIR
        _os.makedirs(d, exist_ok=True)
        cfg_path = _os.path.join(d, "mcp_config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            _json.dump(cfg, f, ensure_ascii=False, indent=2)
        cmd_path = _os.path.join(d, "mcp_http.cmd")
        with open(cmd_path, "w", encoding="utf-8") as f:
            f.write('@echo off\r\nchcp 65001 >nul\r\necho AMCL MCP HTTP: '
                    + self._mcp_url + '\r\necho 客户端选 http 填上面地址, Ctrl+C 停止。\r\n'
                    + f'"{self._mcp_pyexe}" "{self._mcp_main_py}" --mcp-http 8766\r\npause\r\n')
        if hasattr(self, "_mcp_status"):
            self._mcp_status.setText(f"已生成 {cfg_path} 与 {cmd_path}(在 AMCL 文件夹)")

    # ---- 配色(自定义主题) ----
    def _refresh_color_btn_text(self):
        from ui_style import get_custom_colors
        cur = get_custom_colors()
        labels = {"accent": "强调色", "text": "文字色", "panel_bg": "背景色"}
        for slot, b in getattr(self, "_color_btns", {}).items():
            v = cur.get(slot)
            b.setText(f"{labels.get(slot, slot)}:" + (v if v else "默认"))

    def _update_readability(self):
        """改色后检查文字/强调色是否可能看不清,显示在提示行。"""
        try:
            from ui_style import get_custom_colors
            msgs = check_readability(get_custom_colors())
            lbl = getattr(self, "_readability_label", None)
            if lbl is None:
                return
            if msgs:
                lbl.setStyleSheet("color:#E53935; font-size:11px;")
                lbl.setText("\n".join(msgs))
            else:
                lbl.setStyleSheet("color:#4CAF50; font-size:11px;")
                lbl.setText("✅ 配色可读性良好(文字/强调色与背景对比适中)。")
        except Exception:
            pass

    def _apply_cb_preset(self):
        """应用色盲/色弱配色模板(无障碍预设)。"""
        from ui_style import apply_color_blind_preset
        name = self._cb_combo.currentData() or ""
        if not name:
            return
        cols = apply_color_blind_preset(name)
        if not cols:
            return
        from ui_style import set_custom_colors
        set_custom_colors(cols)
        self.settings["ui_custom_colors"] = cols
        save_settings(self.settings)
        self._refresh_color_btn_text()
        self._retheme()
        self._update_readability()

    def _pick_color(self, slot: str, label: str):
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog
        from ui_style import get_custom_colors, set_custom_colors
        cur = get_custom_colors()
        start = QColor(cur.get(slot)) if cur.get(slot) else QColor("#5B8DEF")
        c = QColorDialog.getColor(start, self, f"选择{label}")
        if not c.isValid():
            return
        cols = dict(cur); cols[slot] = c.name()
        set_custom_colors(cols)
        self.settings["ui_custom_colors"] = cols
        save_settings(self.settings)
        self._refresh_color_btn_text()
        self._retheme()
        self._update_readability()

    def _reset_colors(self):
        from ui_style import clear_custom_colors
        clear_custom_colors()
        self.settings["ui_custom_colors"] = {}
        save_settings(self.settings)
        self._refresh_color_btn_text()
        self._retheme()
        self._update_readability()

    def _retheme(self):
        """自定义配色改了 → 实时重刷整应用上色(之前要重启才生效)。"""
        try:
            from ui_style import refresh_theme
            refresh_theme()
        except Exception:
            pass

    def _open_update(self):
        p = self.window()
        if p is not None and hasattr(p, "open_update_dialog"):
            p.open_update_dialog()

    def _open_guide(self):
        p = self.window()
        if p is not None and hasattr(p, "open_guide_demo"):
            p.open_guide_demo()

    def _reopen_tutorial(self):
        p = self.window()
        if p is not None and hasattr(p, "open_tutorial"):
            p.open_tutorial()

    # ================= AI 助手 =================
    def _build_ai(self) -> QWidget:
        self.ai_form = AISettingsForm(self.settings)
        self.mod_translate_check = QCheckBox("Mod 描述本地 AI 翻译(英→中)")
        self.mod_translate_check.setChecked(bool(self.settings.get("ai_mod_translate", True)))
        self.model_dl_btn = QPushButton(t("下载本地模型", "Download local model"))
        self.model_dl_status = QLabel(""); self.model_dl_status.setWordWrap(True)
        self.model_dl_status.setStyleSheet("color: #888888;")
        self.model_dl_btn.clicked.connect(self._start_model_download)
        dl_row = QHBoxLayout(); dl_row.addWidget(self.model_dl_btn); dl_row.addWidget(self.model_dl_status, 1)

        hint = QLabel("· 云/本地两块分开配:顶部选「当前使用(AI 策略)」哪档,AI 对话就走哪边;\n"
                      "· 发图片(多模态):只有所选模型本身会看图才有效,内置本地模型自动关闭;\n"
                      "· 本地模型约 500MB,首次用到时后台自动下载(镜像优先)。")
        hint.setWordWrap(True); hint.setStyleSheet("color: #888888;")

        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(16, 12, 16, 12)
        l.addWidget(self.ai_form); l.addWidget(self.mod_translate_check); l.addWidget(self.model_dl_btn)
        l.addWidget(self.model_dl_status); l.addWidget(hint); l.addStretch()
        # 复用 settings_dialog 的模型下载逻辑(三态按钮)
        self._init_model_dl_button()
        return self._wrap_scroll(w)

    def _is_model_downloaded(self) -> bool:
        try:
            import model_registry
            return model_registry.is_downloaded("qwen3.5-0.8b-xlam-q4km")
        except Exception:
            return False

    def _init_model_dl_button(self):
        ready = self._is_model_downloaded()
        if ready:
            self.model_dl_btn.setText(t("已就绪", "Ready"))
            self.model_dl_btn.setEnabled(False)
            self.model_dl_status.setText(t("本地模型已下载,可直接使用",
                                           "Local model downloaded, ready"))
        else:
            self.model_dl_btn.setText(t("下载本地模型", "Download local model"))
            self.model_dl_btn.setEnabled(True)
            self.model_dl_status.setText(t("未下载(约 500MB,点按钮开始)",
                                           "Not downloaded (~500MB, click to start)"))

    def _start_model_download(self):
        if self._model_downloading:
            return
        if self._is_model_downloaded():
            self._init_model_dl_button()
            return
        self._model_downloading = True
        self.model_dl_btn.setEnabled(False)
        self.model_dl_btn.setText(t("下载中 0%…", "Downloading 0%…"))
        self.model_dl_status.setText(t("正在后台下载本地模型(镜像优先)…",
                                       "Downloading local model (mirror first)…"))
        host = self.window()
        if host is not None and hasattr(host, "model_download_progress"):
            host.model_download_progress("正在下载本地模型(约500MB,镜像优先)…", 0, 1)

        def worker():
            ok, msg = True, "✅ 本地模型下载完成,之后可用内置本地模型。"
            try:
                import model_registry
                model_registry.download("qwen3.5-0.8b-xlam-q4km",
                                        progress_callback=lambda d, total: self._dl_progress.emit(d, total))
            except Exception as e:
                ok = False
                msg = f"❌ 本地模型下载失败:{type(e).__name__}: {str(e)[:200]}"
            self._dl_finished.emit(ok, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_model_dl_progress(self, done, total):
        pct = int(done * 100 / total) if total else 0
        self.model_dl_btn.setText(t(f"下载中 {pct}%…", f"Downloading {pct}%…"))
        host = self.window()
        if host is not None and hasattr(host, "model_download_progress"):
            host.model_download_progress("", done, total)

    def _on_model_dl_finished(self, ok, msg):
        self._model_downloading = False
        self.model_dl_status.setText(msg)
        host = self.window()
        if host is not None and hasattr(host, "model_download_done"):
            host.model_download_done(ok, msg)
        if ok:
            self.model_dl_btn.setText(t("已就绪", "Ready"))
            self.model_dl_btn.setEnabled(False)
        else:
            self.model_dl_btn.setText(t("下载本地模型", "Download local model"))
            self.model_dl_btn.setEnabled(True)

    # ================= 镜像源 =================
    def _build_mirror(self) -> QWidget:
        self.strategy_combo = QComboBox()
        for key, info in MIRROR_STRATEGIES.items():
            self.strategy_combo.addItem(info["name"], key)
        idx = self.strategy_combo.findData(self.settings.get("mirror_strategy", "smart_official"))
        self.strategy_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.strategy_combo.currentIndexChanged.connect(self._on_strategy_changed)
        self.strategy_hint = QLabel(""); self.strategy_hint.setWordWrap(True)
        self.strategy_hint.setStyleSheet("color: #888888;")
        self._update_strategy_hint()

        self.mirror_combo = QComboBox()
        self.mirror_hint = QLabel(""); self.mirror_hint.setWordWrap(True)
        self.mirror_hint.setStyleSheet("color: #888888;")
        self._refresh_mirror_combo()
        self.mirror_combo.currentIndexChanged.connect(self._update_mirror_hint)
        self.mirror_combo.setEnabled(self.strategy_combo.currentData() != "official_only")

        self.custom_name_edit = QLineEdit(); self.custom_name_edit.setPlaceholderText("名称,如 我的镜像")
        self.custom_url_edit = QLineEdit(); self.custom_url_edit.setPlaceholderText("base 地址,如 https://mirror.example.com")
        add_btn = QPushButton("添加"); add_btn.clicked.connect(self._add_custom_mirror)
        add_row = QHBoxLayout(); add_row.addWidget(self.custom_name_edit, 1)
        add_row.addWidget(self.custom_url_edit, 2); add_row.addWidget(add_btn)
        self.custom_list = QListWidget(); self.custom_list.setMinimumHeight(90)
        self._refresh_custom_list()
        del_btn = QPushButton("删除选中"); del_btn.clicked.connect(self._remove_custom_mirror)
        del_row = QHBoxLayout(); del_row.addStretch(); del_row.addWidget(del_btn)

        form = QFormLayout()
        form.addRow("下载策略:", self.strategy_combo)
        form.addRow("", self.strategy_hint)
        form.addRow("镜像站:", self.mirror_combo)
        form.addRow("", self.mirror_hint)

        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(16, 12, 16, 12)
        l.addLayout(form)
        l.addWidget(QLabel("自定义镜像(与 BMCLAPI 同构:填 base 地址,自动映射 libraries/ assets/ version/ 等路径)"))
        l.addLayout(add_row); l.addWidget(self.custom_list); l.addLayout(del_row); l.addStretch()
        return w

    def _build_plugins(self) -> QWidget:
        """插件管理:列出 plugins/*.py(开关启停)。整页放进滚动条,避免垂直拥挤。
        - 启用/禁用 = 开关样式(默认为关即表示默认关闭,不写文字);
        - 标题大、描述小;注册内容移到 tooltip(悬停才显示);
        - 有独立设置页的插件 → 开关旁齿轮按钮,点击跳到该插件设置页。"""
        import plugin_manager
        page = QWidget()
        l = QVBoxLayout(page); l.setContentsMargins(16, 12, 16, 12); l.setSpacing(8)
        head = QLabel("插件 = 启动器的可选功能模块。\n核心组件(启动/实例/下载/设置/AI)不在插件列表里,保证稳定。")
        head.setWordWrap(True); head.setStyleSheet(f"color: {muted_color()};")
        l.addWidget(head)

        disabled = set(self.settings.get("plugins_disabled", []) or [])
        enabled_override = set(self.settings.get("plugins_enabled", []) or [])
        metas = plugin_manager.discover_plugins_meta()
        for name, path in plugin_manager.discover_plugins():
            meta = metas.get(name, {})
            pname = meta.get("name") or name
            pdesc = meta.get("description", "")
            default_on = meta.get("default_enabled", True)
            is_on = (name not in disabled) and (default_on or name in enabled_override)
            card = QWidget(); set_style(card, panel_style)
            cl = QVBoxLayout(card); cl.setContentsMargins(12, 8, 12, 8); cl.setSpacing(3)
            # 行:标题(大)+ 工具/注册内容(tooltip)+ 齿轮 + 开关
            row = QHBoxLayout(); row.setSpacing(6)
            title = QLabel(pname)
            title.setStyleSheet(f"font-weight:bold; font-size:15px; color:{text_color()};")
            # 注册内容 → tooltip(悬停显示)
            contents = self._describe_plugin(name, None)
            if contents:
                title.setToolTip(f"{pname}({name}.py)\n{contents}")
            row.addWidget(title, 1)
            # 有独立设置页 → 齿轮按钮
            if meta.get("has_settings"):
                gear = QToolButton()
                gear.setText("⚙")
                gear.setToolTip("插件设置")
                gear.setCursor(Qt.CursorShape.PointingHandCursor)
                gear.clicked.connect(lambda _c, n=name: self._goto_plugin_setting(n))
                row.addWidget(gear)
            # 开关
            tsw = ToggleSwitch(is_on)
            tsw.toggled.connect(lambda ch, n=name: self._toggle_plugin(n, ch))
            row.addWidget(tsw)
            cl.addLayout(row)
            if pdesc:
                d = QLabel(pdesc); d.setWordWrap(True)
                d.setStyleSheet(f"color: {muted_color()}; font-size: 11px;")
                cl.addWidget(d)
            l.addWidget(card)

        if not plugin_manager.discover_plugins():
            empty = QLabel("还没有插件。把 .py 插件放进启动器的 plugins/ 目录即可;"
                           "或让 AI 按模板生成一个(见「插件模板」)。")
            empty.setWordWrap(True); empty.setStyleSheet(f"color: {muted_color()};")
            l.addWidget(empty)
        # 插件注册的 GUI 页面(章节):嵌入预览
        gui_pages = plugin_manager.GUI_PAGES
        if gui_pages:
            l.addSpacing(8)
            pg_title = QLabel("插件页面:")
            pg_title.setStyleSheet(f"font-weight:bold; color:{muted_color()};")
            l.addWidget(pg_title)
            self._plugin_page_host = QStackedWidget()
            self._plugin_page_labels = []
            for label, build_fn in gui_pages.items():
                try:
                    self._plugin_page_host.addWidget(build_fn())
                    self._plugin_page_labels.append(label)
                except Exception:
                    pass
            if self._plugin_page_labels:
                btn_row = QHBoxLayout(); btn_row.setSpacing(8)
                for i, label in enumerate(self._plugin_page_labels):
                    b = QPushButton(label)
                    set_style(b, card_btn_style); b.setMinimumHeight(30)
                    b.clicked.connect(lambda _c, i=i: self._plugin_page_host.setCurrentIndex(i))
                    btn_row.addWidget(b)
                l.addLayout(btn_row)
                l.addWidget(self._plugin_page_host, 1)
        l.addStretch()

        # 放进滚动区(垂直拥挤也能滚)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _plugin_page_with_toggle(self, pid: str, build_fn) -> QWidget:
        """给插件的独立设置页加一个顶部开关条(启用/禁用本插件)。
        这样在「插件:xxx」设置页里也能直接开关,不用回插件管理页。"""
        import plugin_manager
        outer = QWidget()
        lay = QVBoxLayout(outer); lay.setContentsMargins(10, 8, 10, 6); lay.setSpacing(6)
        # 顶部:插件名 + 开关
        top = QWidget(); set_style(top, panel_style)
        tl = QHBoxLayout(top); tl.setContentsMargins(12, 6, 12, 6)
        name = plugin_manager.discover_plugins_meta().get(pid, {}).get("name") or pid
        lbl = QLabel(name)
        lbl.setStyleSheet(f"font-weight:bold; font-size:14px; color:{text_color()};")
        disabled = set(self.settings.get("plugins_disabled", []) or [])
        enabled_override = set(self.settings.get("plugins_enabled", []) or [])
        default_on = plugin_manager.discover_plugins_meta().get(pid, {}).get("default_enabled", True)
        is_on = (pid not in disabled) and (default_on or pid in enabled_override)
        tsw = ToggleSwitch(is_on)
        tsw.toggled.connect(lambda ch, n=pid: self._toggle_plugin(n, ch))
        tl.addWidget(lbl, 1); tl.addWidget(QLabel("启用")); tl.addWidget(tsw)
        lay.addWidget(top)
        # 插件设置的 build_fn 内容
        lay.addWidget(build_fn())
        return outer

    def _goto_plugin_setting(self, name: str):
        """跳到某插件的独立设置页(在设置左菜单单开一行,标签为 插件:<显示名>)。
        若插件未启用(默认关,其设置行未加载),提示先启用。"""
        try:
            import plugin_manager
            meta = plugin_manager.discover_plugins_meta().get(name, {})
            display = meta.get("name") or name
            if self.shell.switch_by_label(f"插件:{display}"):
                return
            QMessageBox.information(self, "插件设置",
                                    f"「{display}」目前未启用(默认关闭)。\n"
                                    "请先把它的开关打开,再点⚙进入设置。")
        except Exception:
            pass

    def _describe_plugin(self, name: str, mod) -> str:
        """给插件页面显示该插件注册了哪些内容。"""
        import plugin_manager
        bits = []
        ntools = sum(1 for k in plugin_manager.TOOLS if k.startswith(f"{name}__"))
        if ntools:
            bits.append(f"AI 工具 ×{ntools}")
        ngui = sum(1 for k in plugin_manager.GUI_PAGES)
        if ngui:
            bits.append(f"页面 ×{ngui}")
        nset = sum(1 for k in plugin_manager.SETTINGS if k.startswith(f"{name}."))
        if nset:
            bits.append(f"设置项 ×{nset}")
        nsk = sum(1 for c in plugin_manager.SKILLS if c.id.startswith(f"{name}_"))
        if nsk:
            bits.append(f"技能 ×{nsk}")
        return "注册内容: " + " · ".join(bits) if bits else ""

    def _toggle_plugin(self, name: str, checked: bool):
        """切换插件启禁状态(存 settings,下次启动生效)。checked=True=启用。
        默认关闭的插件启用时记入 plugins_enabled;禁用时从 plugins_disabled 移除。"""
        disabled = set(self.settings.get("plugins_disabled", []) or [])
        enabled_over = set(self.settings.get("plugins_enabled", []) or [])
        if checked:
            disabled.discard(name)
            enabled_over.add(name)     # 默认关/被禁的都显式启用
        else:
            disabled.add(name)
            enabled_over.discard(name)
        self.settings["plugins_disabled"] = sorted(disabled)
        self.settings["plugins_enabled"] = sorted(enabled_over)

    def _on_strategy_changed(self):
        self._update_strategy_hint()
        self.mirror_combo.setEnabled(self.strategy_combo.currentData() != "official_only")

    def _update_strategy_hint(self):
        info = MIRROR_STRATEGIES.get(self.strategy_combo.currentData())
        self.strategy_hint.setText(info["desc"] if info else "")

    def _refresh_mirror_combo(self):
        cur = self.settings.get("mirror_source", "bmclapi")
        self.mirror_combo.blockSignals(True); self.mirror_combo.clear()
        for key, info in MIRROR_SOURCES.items():
            self.mirror_combo.addItem(info["name"], key)
        for cm in self._custom_mirrors:
            self.mirror_combo.addItem(f"自定义: {cm.get('name', '?')}", "custom:" + cm.get("id", ""))
        idx = self.mirror_combo.findData(cur)
        if idx < 0:
            idx = self.mirror_combo.findData("bmclapi")
        self.mirror_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.mirror_combo.blockSignals(False); self._update_mirror_hint()

    def _update_mirror_hint(self):
        key = self.mirror_combo.currentData()
        if key in MIRROR_SOURCES:
            self.mirror_hint.setText(MIRROR_SOURCES[key]["desc"])
        elif key and key.startswith("custom:"):
            cid = key.split(":", 1)[1]
            for cm in self._custom_mirrors:
                if cm.get("id") == cid:
                    self.mirror_hint.setText(f"自定义镜像:{cm.get('name', '')} — {cm.get('url', '')}")
                    return
        else:
            self.mirror_hint.setText("")

    def _add_custom_mirror(self):
        name = self.custom_name_edit.text().strip()
        url = self.custom_url_edit.text().strip()
        if not name or not url:
            QMessageBox.warning(self, "镜像源", "请填写名称和地址"); return
        if not url.startswith(("http://", "https://")):
            QMessageBox.warning(self, "镜像源", "地址必须以 http:// 或 https:// 开头"); return
        self._custom_mirrors.append({"id": uuid.uuid4().hex[:8], "name": name, "url": url.rstrip("/")})
        self.custom_name_edit.clear(); self.custom_url_edit.clear()
        self._refresh_custom_list(); self._refresh_mirror_combo()
        idx = self.mirror_combo.findData("custom:" + self._custom_mirrors[-1]["id"])
        self.mirror_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _refresh_custom_list(self):
        self.custom_list.clear()
        for cm in self._custom_mirrors:
            self.custom_list.addItem(f"{cm.get('name', '?')}  —  {cm.get('url', '')}")

    def _remove_custom_mirror(self):
        row = self.custom_list.currentRow()
        if row < 0:
            QMessageBox.information(self, "镜像源", "先在列表里选中要删除的自定义镜像"); return
        self._custom_mirrors.pop(row); self._refresh_custom_list(); self._refresh_mirror_combo()

    # ================= 保存 =================
    def apply(self):
        self.settings["username"] = self.username_edit.text().strip() or "Player"
        self.settings["memory_gb"] = self.memory_spin.value()
        self.settings["version_isolation"] = self.isolation_check.isChecked()
        self.settings["game_dir"] = self.game_dir_edit.text().strip()
        self.settings["language"] = self.language_combo.currentData()
        self.settings["ui_mode"] = self.ui_mode_combo.currentData()
        self.settings.update(self.ai_form.values())
        self.settings["ai_mod_translate"] = self.mod_translate_check.isChecked()
        self.settings["mirror_strategy"] = self.strategy_combo.currentData()
        self.settings["mirror_source"] = self.mirror_combo.currentData()
        self.settings["custom_mirrors"] = self._custom_mirrors
        # MCP 客户端(启动器 AI 调用的外部 MCP 服务器):配置在 MCP 插件设置页(w._mcp_clients_edit)。
        # 从 shell 里找该编辑框(插件未启用/未构建时保留原值)。
        mcp_edit = getattr(self, "mcp_clients_edit", None)
        if mcp_edit is None:
            try:
                # 深度找 shell 里挂着 _mcp_clients_edit 的插件设置页
                for pw in self.shell.stack.findChildren(QWidget):
                    e = getattr(pw, "_mcp_clients_edit", None)
                    if e is not None:
                        mcp_edit = e
                        break
            except Exception:
                mcp_edit = None
        if mcp_edit is not None:
            self.settings["mcp_clients"] = _parse_mcp_entries(mcp_edit.text())
        save_settings(self.settings)
        self.applied.emit()
