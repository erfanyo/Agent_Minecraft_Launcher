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
    QLineEdit, QListWidget, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from assistant import AISettingsForm
from center_shell import CenterShell
from downloader import MIRROR_SOURCES, MIRROR_STRATEGIES
from i18n import t
from paths import DEFAULT_GAME_DIR
from settings import save_settings
from ui_style import card_btn_style, muted_color


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
        if initial_tab:
            self.shell.switch_by_label(initial_tab)

        save_btn = QPushButton(t("保存设置", "Save settings"))
        save_btn.setStyleSheet(card_btn_style())
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
    def _build_ui(self) -> QWidget:
        self.language_combo = QComboBox()
        for label, value in (("自动(跟随系统)", "auto"), ("中文", "zh"), ("English", "en")):
            self.language_combo.addItem(label, value)
        idx = self.language_combo.findData(self.settings.get("language", "auto"))
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
                open_btn = QPushButton("临时查看"); open_btn.setStyleSheet(card_btn_style())
                open_btn.clicked.connect(self._reopen_tutorial); row.addWidget(open_btn)
            l.addLayout(row)
        # 检查更新 / 重播引导教程(原在菜单栏,现并入设置 → 界面;重播按钮不放在最外层)
        l.addSpacing(8)
        upd_btn = QPushButton(t("检查更新…", "Check for Updates…"))
        tut_btn = QPushButton(t("重播引导教程", "Replay guided tutorial"))
        for b in (upd_btn, tut_btn):
            b.setStyleSheet(card_btn_style()); b.setMinimumHeight(32)
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
            b.setStyleSheet(card_btn_style())
            b.clicked.connect(lambda _c, s=slot, lb=label: self._pick_color(s, lb))
            cbtn_row.addWidget(b, 1)
            self._color_btns[slot] = b
        reset_btn = QPushButton("重置默认"); reset_btn.setStyleSheet(card_btn_style())
        reset_btn.clicked.connect(self._reset_colors)
        cbtn_row.addWidget(reset_btn)
        l.addLayout(cbtn_row)
        color_hint = QLabel("配色改完保存后,**整个启动器**在下次启动/重建时生效;当前设置页立即预览强调色。")
        color_hint.setWordWrap(True); color_hint.setStyleSheet("color:#8a93a0;")
        l.addWidget(color_hint)
        self._refresh_color_btn_text()
        l.addStretch()
        return w

    # ---- 配色(自定义主题) ----
    def _refresh_color_btn_text(self):
        from ui_style import get_custom_colors
        cur = get_custom_colors()
        labels = {"accent": "强调色", "text": "文字色", "panel_bg": "背景色"}
        for slot, b in getattr(self, "_color_btns", {}).items():
            v = cur.get(slot)
            b.setText(f"{labels.get(slot, slot)}:" + (v if v else "默认"))

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

    def _reset_colors(self):
        from ui_style import clear_custom_colors
        clear_custom_colors()
        self.settings["ui_custom_colors"] = {}
        save_settings(self.settings)
        self._refresh_color_btn_text()

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
        return w

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
        save_settings(self.settings)
        self.applied.emit()
