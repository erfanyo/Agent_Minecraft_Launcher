# -*- coding: utf-8 -*-
"""
设置中心(顶部标签卡版):左菜单(游戏/Java/语言/个性化/系统/软件信息/AI助手/镜像源)+ 右侧面板,复用 CenterShell,
和「下载新资源」同一套布局/操作逻辑。解决原「设置弹窗(模态)」挡住引导遮罩的问题。

保存:颜色/壁纸/动画与 Java 管理自动保存；其余设置由底部按钮统一应用。
"""
from launcher_app.ui.ui_notifications import task_notice, task_warning, inline_notice, inline_warning, action_question
from launcher_app.ui.task_center import task_question
import threading
import uuid

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox, QPlainTextEdit,
    QComboBox, QDialogButtonBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox, QInputDialog,
    QToolButton, QVBoxLayout, QWidget, QMenu,
)

from launcher_app.ai.assistant import AISettingsForm
from launcher_app.core.background_tasks import BackgroundTask
from launcher_app.ui.center_shell import CenterShell
from launcher_app.resources.downloader import MIRROR_SOURCES, MIRROR_STRATEGIES, MIRROR_REGION_PRESETS
from launcher_app.core.i18n import t
import paths
from paths import DEFAULT_GAME_DIR
from os_platform.openpath import open_path
from settings import update_settings
from launcher_app.ui.ui_style import (card_btn_style, muted_color, set_style,
                      COLOR_BLIND_PRESETS, check_readability, panel_style, text_color,
                      accent_color, danger_color, success_color, current_color, popup_menu_style)
from launcher_app.ui.ui_switch import ToggleSwitch, setting_switch_row
from launcher_app.ui.settings_section import SettingsSection


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


class SettingsCenter(QWidget):
    applied = Signal()   # 保存后发出,主窗口据此刷新(set_ui_mode / ai_dock 等)
    visual_changed = Signal()  # 轻量外观设置已自动保存，只刷新外观，不重扫实例
    runtime_changed = Signal()  # Java 等运行时设置已保存，只同步内存配置
    _dl_progress = Signal(int, int)
    _dl_finished = Signal(bool, str)

    def __init__(self, settings: dict, parent=None, initial_tab: str | None = None):
        super().__init__(parent)
        self.settings = dict(settings)
        self._custom_mirrors = [dict(c) for c in self.settings.get("custom_mirrors", []) or []]
        self._model_downloading = False
        self._java_task = None
        self._visual_save_timer = QTimer(self)
        self._visual_save_timer.setSingleShot(True)
        self._visual_save_timer.setInterval(220)
        self._visual_save_timer.timeout.connect(self._save_visual_settings)
        self._dl_progress.connect(self._on_model_dl_progress)
        self._dl_finished.connect(self._on_model_dl_finished)

        self.shell = CenterShell(self, menu_width=150)
        self.shell.add_section(t("GAME"), self._build_game)
        self.shell.add_section(t("备份"), self._build_backup)
        self.shell.add_section("Java", self._build_java)
        self.shell.add_section(t("语言"), self._build_language)
        self.shell.add_section(t("个性化"), self._build_ui)
        self.shell.add_section(t("SYSTEM"), self._build_system)
        self.shell.add_section(t("模型"), self._build_models)
        self.shell.add_section(t("软件信息"), self._build_software_info)
        if self._should_show_ai_settings():
            self.shell.add_section(t("AI_ASSISTANT"), self._build_ai)
        self.shell.add_section(t("MIRROR"), self._build_mirror)
        self.shell.add_section(t("PLUGINS"), self._build_plugins)
        from launcher_app.features.registry import settings_pages
        for feature_id, feature_name, builder in settings_pages():
            label = '联机设置' if feature_id == 'lan_bridge' else feature_name
            self.shell.add_section(t(label), builder)
        # 插件注册的独立设置页:在左菜单【各单开一行】(按插件名)。
        # 只在插件【启用】时才加(关闭/默认关未启用的插件不占菜单);可用齿轮从插件页进入,或启用后出现。
        self._plugin_settings_rows = []
        try:
            import launcher_app.extensions.plugin_manager as plugin_manager
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

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.shell, 1)
        bottom = QHBoxLayout()
        self._autosave_hint = QLabel(t("设置自动保存；插件启停需重启后生效"))
        self._autosave_hint.setStyleSheet(f"color:{muted_color()};")
        bottom.addWidget(self._autosave_hint)
        bottom.addStretch()
        lay.addLayout(bottom)
        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.setInterval(650)
        self._settings_save_timer.timeout.connect(lambda: self.apply(automatic=True))
        visual_controls = {self.theme_combo, self.wallpaper_source_combo,
                           self.wallpaper_preset_combo, self.wallpaper_blur_slider,
                           self.wallpaper_mask_slider, self.animations_check}
        # Bind after page construction, so defaults do not overwrite saved settings.
        for control in self.findChildren(QWidget):
            if control in visual_controls:
                continue
            if isinstance(control, QLineEdit):
                if control is self.game_dir_edit:
                    control.editingFinished.connect(self._queue_settings_save)
                else:
                    control.textEdited.connect(self._queue_settings_save)
                control.editingFinished.connect(self.flush_autosave)
            elif isinstance(control, QComboBox):
                control.currentIndexChanged.connect(self._queue_settings_save)
            elif isinstance(control, (QSpinBox, QSlider)):
                control.valueChanged.connect(self._queue_settings_save)
            elif isinstance(control, (ToggleSwitch, QCheckBox)):
                control.toggled.connect(self._queue_settings_save)
            elif isinstance(control, QPlainTextEdit):
                control.textChanged.connect(self._queue_settings_save)
        if hasattr(self, 'model_cards'):
            self.model_cards.changed.connect(self._queue_settings_save)

    def _queue_settings_save(self, *_):
        self._settings_save_timer.start()

    def flush_autosave(self):
        if self._settings_save_timer.isActive():
            self._settings_save_timer.stop()
            self.apply(automatic=True)

    def _should_show_ai_settings(self) -> bool:
        if (bool(self.settings.get("ai_configured", False))
                or bool((self.settings.get("ai_cloud_api_key")
                         or self.settings.get("ai_api_key") or "").strip())):
            return True
        try:
            import launcher_app.ai.model_registry as model_registry
            return model_registry.is_downloaded("qwen3.5-0.8b-xlam-q4km")
        except Exception:
            return False

    def refresh_ai_config_visibility(self):
        """Add the AI settings page after a model is installed or API is configured."""
        if self._should_show_ai_settings() and not hasattr(self, "ai_form"):
            self.shell.add_section(t("AI_ASSISTANT"), self._build_ai)

    # ================= 游戏 =================
    def _build_game(self) -> QWidget:
        saved_memory = int(self.settings.get('memory_gb', 0) or 0)
        self.memory_auto_check = ToggleSwitch(saved_memory <= 0)
        self.memory_auto_check.setToolTip(t('自动：每次启动时根据当前可用内存、该实例历史峰值或 Mod 数量估算。\n手动：使用下方指定的 Java 堆上限。'))
        from launcher_app.ui.numeric_input import SettingsSpinBox
        self.memory_spin = SettingsSpinBox()
        self.memory_spin.setRange(1, 64)
        self.memory_spin.setSuffix(" GB")
        self.memory_spin.setValue(saved_memory if saved_memory > 0 else 4)
        self.memory_spin.setEnabled(not self.memory_auto_check.isChecked())
        self.memory_auto_check.toggled.connect(self._on_memory_policy_changed)
        self.isolation_check = ToggleSwitch(self.settings.get("version_isolation", True))
        self.game_dir_edit = QLineEdit(self.settings.get("game_dir") or DEFAULT_GAME_DIR)
        browse_btn = QPushButton(t("浏览…")); browse_btn.clicked.connect(self._browse_game_dir)
        default_btn = QPushButton(t("默认")); default_btn.clicked.connect(
            lambda: self.game_dir_edit.setText(DEFAULT_GAME_DIR))
        dir_row = QHBoxLayout(); dir_row.addWidget(self.game_dir_edit, 1)
        dir_row.addWidget(browse_btn); dir_row.addWidget(default_btn)

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow(t("内存策略:"), setting_switch_row(
            t("自动分配内存"), self.memory_auto_check, t("根据可用内存和实例使用情况估算")))
        form.addRow(t("手动内存:"), self.memory_spin)
        from launcher_app.ui.memory_meter import MemoryMeter
        self.memory_meter = MemoryMeter(lambda: 0 if self.memory_auto_check.isChecked() else self.memory_spin.value())
        self.memory_spin.valueChanged.connect(self.memory_meter.refresh)
        self.memory_auto_check.toggled.connect(self.memory_meter.refresh)
        form.addRow('', self.memory_meter)
        from launcher_app.instances.advanced_launch import editor
        self.jvm_editor = editor(self.settings.get('jvm_args', ''))
        memory_form = form
        form = QFormLayout()
        form.addRow(t("版本隔离:"), setting_switch_row(
            t("独立游戏目录"), self.isolation_check, t("各版本的存档、配置和 Mod 分开保存")))
        form.addRow(t("游戏目录:"), dir_row)
        hint = QLabel(t("可以是任意位置,包括 PCL2 / 官方启动器创建的 .minecraft(自动读取里面的实例)"))
        hint.setWordWrap(True); hint.setStyleSheet(f"color: {muted_color()};")
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(16, 12, 16, 12); l.setSpacing(10)
        memory = SettingsSection(t('内存分配'))
        memory.content.addLayout(memory_form)
        launch = SettingsSection(t('JVM 启动参数'))
        launch.content.addWidget(self.jvm_editor)
        storage = SettingsSection(t('游戏目录与版本隔离'))
        storage.content.addLayout(form)
        storage.content.addWidget(hint)
        l.setSpacing(16)
        for chapter in (memory, launch, storage):
            l.addWidget(chapter)
        l.addStretch()
        return w

    def _browse_game_dir(self):
        from PySide6.QtWidgets import QFileDialog
        start = self.game_dir_edit.text().strip() or DEFAULT_GAME_DIR
        d = QFileDialog.getExistingDirectory(self, t('选择 Minecraft 游戏目录'), start,
                                            QFileDialog.Option.DontUseNativeDialog)
        if d:
            self.game_dir_edit.setText(d)

    def _build_backup(self) -> QWidget:
        self.backup_remind_check = ToggleSwitch(self.settings.get("backup_remind_on_exit", True))
        self.backup_auto_check = ToggleSwitch(self.settings.get("backup_auto_on_exit", False))
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        section = SettingsSection(t('退出游戏后的备份策略'))
        layout.addWidget(section)
        page_layout = layout
        layout = section.content
        layout.addWidget(setting_switch_row(
            t("退出时提醒备份"), self.backup_remind_check,
            t("只在本次游玩修改了本地世界后提醒；在提醒里勾选不再提示后，可在这里恢复。")))
        layout.addWidget(setting_switch_row(
            t("退出时自动备份"), self.backup_auto_check,
            t("每次退出且本地世界有变化时自动备份；启用后不再弹出提醒。")))
        hint = QLabel(t("备份保存在游戏目录的 backups/{instance_name}/ 下。联机服务器游玩不会触发本地世界备份。"))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {muted_color()};")
        layout.addWidget(hint)
        page_layout.addStretch()
        return panel

    def refresh_backup_settings(self):
        from settings import load_settings
        current = load_settings()
        for name, key in (("backup_remind_check", "backup_remind_on_exit"),
                          ("backup_auto_check", "backup_auto_on_exit")):
            control = getattr(self, name, None)
            if control is not None:
                control.setChecked(bool(current.get(key, key == "backup_remind_on_exit")))

    def _on_memory_policy_changed(self, automatic: bool):
        self.memory_spin.setEnabled(not automatic)

    # ================= 语言 / 个性化 =================
    @staticmethod
    def _wrap_scroll(w) -> QScrollArea:
        """把页面内容包进滚动区(纵向内容多时可用滚动条,不拥挤)。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setWidget(w)
        return scroll

    def _build_language(self) -> QWidget:
        self.language_combo = QComboBox()
        for label, value in ((t("自动(跟随系统)"), "auto"), ("中文", "zh"), ("English (preview)", "en")):
            self.language_combo.addItem(label, value)
        # 可选语言包(第三方/玩梗):从这里选能整包换肤
        try:
            import launcher_app.core.i18n as i18n
            for pid, meta in i18n.list_packs().items():
                if pid in ('zh', 'en'):
                    continue
                self.language_combo.addItem(t('语言包：{name} ({id})').format(name=t(meta['name']), id=pid), pid)
        except Exception:
            pass
        idx = self.language_combo.findData(self.settings.get("language", "auto"))
        if idx < 0:
            idx = self.language_combo.findData("auto")
        self.language_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.sync_minecraft_language_check = ToggleSwitch(
            bool(self.settings.get("sync_minecraft_language", True)))
        self.sync_minecraft_language_check.setToolTip(
            t("开启：每次启动前把实例 options.txt 的语言设为当前启动器语言；关闭后可在游戏内独立选择。"))

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow(t("启动器语言:"), self.language_combo)
        hint = QLabel(t("切换启动器语言后需要重启。语言同步可让新启动的实例跟随这里的选择。"))
        hint.setWordWrap(True); hint.setStyleSheet(f"color: {muted_color()};")
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(16, 12, 16, 12); l.setSpacing(10)
        language = SettingsSection(t('语言与游戏同步'))
        l.addWidget(language)
        page_layout = l
        l = language.content
        l.addLayout(form)
        l.addWidget(setting_switch_row(t("启动时同步 Minecraft 语言"),
                                       self.sync_minecraft_language_check,
                                       t("跟随启动器或系统语言；关闭后可在游戏内单独选择")))
        l.addWidget(hint)
        page_layout.addStretch()
        return w

    # ================= 个性化 =================
    def _build_ui(self) -> QWidget:

        self.ui_mode_combo = QComboBox()
        for label, value in ((t("FULL_MORE_TIPS_GUIDES"), "beginner"),
                             (t("SUMMARY_CONCISE"), "expert")):
            self.ui_mode_combo.addItem(label, value)
        idx = self.ui_mode_combo.findData(self.settings.get("ui_mode", "beginner"))
        self.ui_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        mode_hint = QLabel(t("全面:首页显示资源结构科普、更详细的状态提示;摘要:隐藏科普、精简提示。"))
        mode_hint.setWordWrap(True); mode_hint.setStyleSheet(f"color: {muted_color()};")

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow(t("界面模式:"), self.ui_mode_combo)
        form.addRow("", mode_hint)

        self.theme_combo = QComboBox()
        for label, value in (("跟随系统", "system"), ("浅色", "light"), ("深色", "dark")):
            self.theme_combo.addItem(t(label), value)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(
            self.settings.get('ui_theme', 'system'))))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        form.addRow(t("外观主题:"), self.theme_combo)

        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(16, 12, 16, 12); l.setSpacing(10)
        from launcher_app.ui.settings_section import SettingsSection
        page_layout = l
        appearance = SettingsSection(t('界面与主题'))
        page_layout.addWidget(appearance)
        l = appearance.content
        l.addLayout(form)
        self.animations_check = ToggleSwitch(bool(self.settings.get("ui_animations_enabled", True)))
        l.addWidget(setting_switch_row(t("界面动画"), self.animations_check,
                                       t('淡入、标签切换等过渡效果')))
        # 配色(自定义主题):改 强调色/文字色/次要文字/背景色
        l.addSpacing(12)
        colors = SettingsSection(t('自定义配色'))
        page_layout.addWidget(colors)
        l = colors.content
        self._color_btns = {}
        cbtn_row = QHBoxLayout(); cbtn_row.setSpacing(8)
        for slot, label in [("accent", "强调色"), ("text", "文字色"), ("muted", "次要文字"), ("panel_bg", "背景色")]:
            b = QPushButton(t(label))
            set_style(b, card_btn_style)
            b.clicked.connect(lambda _c, s=slot, lb=label: self._pick_color(s, lb))
            cbtn_row.addWidget(b, 1)
            self._color_btns[slot] = b
        reset_btn = QPushButton(t("重置默认")); set_style(reset_btn, card_btn_style)
        reset_btn.clicked.connect(self._reset_colors)
        cbtn_row.addWidget(reset_btn)
        l.addLayout(cbtn_row)
        color_hint = QLabel(t("配色修改后立即生效；自定义文字色会按所选颜色显示。"))
        color_hint.setWordWrap(True); color_hint.setStyleSheet(f"color: {muted_color()};")
        l.addWidget(color_hint)
        # 色盲/色弱友好模板(为无障碍预设,一键应用)
        cb_row = QHBoxLayout(); cb_row.setSpacing(8)
        cb_row.addWidget(QLabel(t("配色模板(无障碍):")))
        self._cb_combo = QComboBox()
        self._cb_combo.addItem(t("(无)"), "")
        for _name in COLOR_BLIND_PRESETS:
            self._cb_combo.addItem(t(_name), _name)
        cb_row.addWidget(self._cb_combo, 1)
        apply_cb_btn = QPushButton(t("应用模板"))
        set_style(apply_cb_btn, card_btn_style); apply_cb_btn.setMinimumHeight(32)
        apply_cb_btn.clicked.connect(self._apply_cb_preset)
        cb_row.addWidget(apply_cb_btn)
        l.addLayout(cb_row)
        # 可读性提示(改色后检查文字/强调色是否看不清)
        self._readability_label = QLabel("")
        self._readability_label.setWordWrap(True)
        l.addWidget(self._readability_label)
        self._refresh_color_btn_text()
        # 自定义背景(阶段 2):壁纸源 + 遮罩强度(决策 1/2/3)
        l.addSpacing(12)
        background = SettingsSection(t('背景与遮罩'))
        page_layout.addWidget(background)
        l = background.content
        self.wallpaper_source_combo = QComboBox()
        for _lab, _val in (("关闭", "none"), ("内置风景", "bundled"), ("预设渐变", "preset"),
                           ("本机图片", "user")):
            self.wallpaper_source_combo.addItem(t(_lab), _val)
        self.wallpaper_source_combo.setCurrentIndex(
            max(0, self.wallpaper_source_combo.findData(
                'preset' if self.settings.get('ui_wallpaper_source') == 'official'
                else self.settings.get("ui_wallpaper_source", "bundled"))))
        self.wallpaper_source_combo.currentIndexChanged.connect(
            lambda *_: self._on_wallpaper_source_changed(True))
        src_row = QHBoxLayout(); src_row.addWidget(QLabel(t("壁纸:")))
        src_row.addWidget(self.wallpaper_source_combo, 1)
        l.addLayout(src_row)
        official_link = QLabel(t('<a href="https://www.minecraft.net/zh-hans/collectibles">官方壁纸 ↗</a>'))
        official_link.setOpenExternalLinks(True)
        official_link.setToolTip(t('在浏览器中打开 Minecraft 官方素材页面；下载后可作为本机图片选择'))
        l.addWidget(official_link)

        from launcher_app.ui.ui_background import PRESETS
        self.wallpaper_preset_combo = QComboBox()
        for _pid in PRESETS:
            self.wallpaper_preset_combo.addItem(_pid, _pid)
        self.wallpaper_preset_combo.setCurrentIndex(
            max(0, self.wallpaper_preset_combo.findData(
                self.settings.get("ui_wallpaper_preset", "teal"))))
        self.wallpaper_preset_combo.currentIndexChanged.connect(self._queue_visual_autosave)
        preset_row = QHBoxLayout(); preset_row.addWidget(QLabel(t("预设:")))
        preset_row.addWidget(self.wallpaper_preset_combo, 1)
        l.addLayout(preset_row)

        self._wallpaper_user_path = self.settings.get("ui_wallpaper_user_path", "") or ""
        from launcher_app.ui.wallpaper_picker import WallpaperDropButton
        self.wallpaper_user_btn = WallpaperDropButton()
        set_style(self.wallpaper_user_btn, card_btn_style)
        self.wallpaper_user_btn.clicked.connect(self._pick_wallpaper_image)
        self.wallpaper_user_btn.fileDropped.connect(self._import_wallpaper_image)
        self.wallpaper_user_label = QLabel(self._wallpaper_user_path or t('未选择'))
        self.wallpaper_user_label.setWordWrap(True)
        self.wallpaper_user_label.setStyleSheet(f"color: {muted_color()};")
        l.addWidget(self.wallpaper_user_btn)
        l.addWidget(self.wallpaper_user_label)
        from launcher_app.ui.ui_background import blur_strength
        self.wallpaper_blur_slider = QSlider(Qt.Orientation.Horizontal)
        self.wallpaper_blur_slider.setRange(0, 80)
        self._wallpaper_blur_custom = self.settings.get('ui_wallpaper_blur') is not None
        self.wallpaper_blur_slider.setValue(blur_strength(self.settings))
        self.wallpaper_blur_slider.setToolTip(t('0 = 关闭；数值越大越模糊。调整后缓存结果，不修改原图。'))
        self.wallpaper_blur_label = QLabel()
        self.wallpaper_blur_slider.valueChanged.connect(self._on_wallpaper_blur_changed)
        self.wallpaper_blur_label.setText(t('模糊强度: {v0}').format(v0=(self.wallpaper_blur_slider.value())) +
                                          (t('（关闭）') if self.wallpaper_blur_slider.value() == 0 else ''))
        blur_row = QHBoxLayout(); blur_row.addWidget(QLabel(t('模糊:')))
        blur_row.addWidget(self.wallpaper_blur_slider, 1)
        blur_row.addWidget(self.wallpaper_blur_label)
        l.addLayout(blur_row)

        self.wallpaper_mask_slider = QSlider(Qt.Orientation.Horizontal)
        self.wallpaper_mask_slider.setRange(0, 80)
        try:
            from launcher_app.ui.ui_background import mask_strength
            _mask = round(mask_strength(self.settings) * 100)
        except Exception:
            _mask = 55
        self._wallpaper_mask_custom = self.settings.get('ui_wallpaper_mask') is not None
        self.wallpaper_mask_slider.setValue(_mask)
        self.wallpaper_mask_label = QLabel(t('遮罩强度: {v0}%').format(v0=(self.wallpaper_mask_slider.value())))
        self.wallpaper_mask_slider.valueChanged.connect(self._on_wallpaper_mask_changed)
        mask_row = QHBoxLayout(); mask_row.addWidget(QLabel(t("遮罩:")))
        mask_row.addWidget(self.wallpaper_mask_slider, 1)
        mask_row.addWidget(self.wallpaper_mask_label)
        l.addLayout(mask_row)
        reset_wallpaper_btn = QPushButton(t("恢复主题默认值"))
        set_style(reset_wallpaper_btn, card_btn_style)
        reset_wallpaper_btn.clicked.connect(self._reset_wallpaper_defaults)
        l.addWidget(reset_wallpaper_btn)
        bg_hint = QLabel(t("遮罩让壁纸上的文字更容易看清。选择本机图片时会复制到启动器缓存，原图不会被修改。"))
        bg_hint.setWordWrap(True); bg_hint.setStyleSheet(f"color: {muted_color()};")
        l.addWidget(bg_hint)
        self.animations_check.toggled.connect(self._queue_visual_autosave)
        self._on_wallpaper_source_changed(False)
        page_layout.addStretch()
        return self._wrap_scroll(w)

    def _copy_mcp_link(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(getattr(self, "_mcp_url", ""))
        if hasattr(self, "_mcp_status"):
            self._mcp_status.setText(t('已复制 HTTP 链接 → 客户端「http」选项填它'))

    def _clear_cache(self, kind: str):
        """清除 Mod 图片/描述缓存:kind='icons' 或 'desc'。清完提示删了多少个。"""
        try:
            import launcher_app.ui.image_cache as image_cache
            if kind == "icons":
                n = image_cache.clear_icons()
                msg = f"已清除 {n} 个图片缓存。"
            else:
                n = image_cache.clear_desc()
                msg = f"已清除 {n} 条描述翻译缓存。"
            inline_notice(self, t('清除缓存'), msg)
        except Exception as e:
            inline_warning(self, t('清除缓存'), t('清除失败:{v0}: {v1}').format(v0=(type(e).__name__), v1=(e)))

    def _on_wallpaper_source_changed(self, save: bool = True):
        """切换壁纸源 → 只启用对应控件。"""
        src = self.wallpaper_source_combo.currentData()
        self.wallpaper_preset_combo.setEnabled(src == "preset")
        self.wallpaper_user_btn.setEnabled(src == "user")
        self.wallpaper_user_btn.setVisible(src == 'user')
        self.wallpaper_user_label.setVisible(src == 'user')
        self.wallpaper_blur_slider.setEnabled(src != 'none')
        if save:
            self._queue_visual_autosave()

    def _on_wallpaper_mask_changed(self, value: int):
        self._wallpaper_mask_custom = True
        self.wallpaper_mask_label.setText(t('遮罩强度: {v0}%').format(v0=(value)))
        self._queue_visual_autosave()

    def _on_wallpaper_blur_changed(self, value: int):
        self._wallpaper_blur_custom = True
        self.wallpaper_blur_label.setText(t('模糊强度: {v0}').format(v0=(value)) + (t('（关闭）') if value == 0 else ''))
        self._queue_visual_autosave()

    def _on_theme_combo_changed(self, *_):
        from launcher_app.ui.ui_tokens import set_theme_mode
        set_theme_mode(self.theme_combo.currentData())
        self.refresh_wallpaper_defaults()
        self._queue_visual_autosave()

    def refresh_wallpaper_defaults(self):
        """Show the current theme's defaults without turning them into overrides."""
        from launcher_app.ui.ui_background import blur_strength, mask_strength
        if not self._wallpaper_mask_custom:
            self.wallpaper_mask_slider.blockSignals(True)
            self.wallpaper_mask_slider.setValue(round(mask_strength({}) * 100))
            self.wallpaper_mask_slider.blockSignals(False)
            self.wallpaper_mask_label.setText(t('遮罩强度: {v0}%').format(v0=(self.wallpaper_mask_slider.value())))
        if not self._wallpaper_blur_custom:
            self.wallpaper_blur_slider.blockSignals(True)
            self.wallpaper_blur_slider.setValue(blur_strength({}))
            self.wallpaper_blur_slider.blockSignals(False)
            value = self.wallpaper_blur_slider.value()
            self.wallpaper_blur_label.setText(t('模糊强度: {v0}').format(v0=(value)) + (t('（关闭）') if value == 0 else ''))

    def _reset_wallpaper_defaults(self):
        self._wallpaper_mask_custom = False
        self._wallpaper_blur_custom = False
        self.refresh_wallpaper_defaults()
        self._queue_visual_autosave()

    def _queue_visual_autosave(self, *_):
        self._visual_save_timer.start()

    def _save_preserving_accounts(self):
        """其他设置页的旧快照不能覆盖登录卡片刚切换的账户。"""
        account_keys = {"username", "offline_accounts", "login_method",
                        "ms_credentials", "microsoft_accounts"}
        def change(live):
            live.update({key: value for key, value in self.settings.items()
                         if key not in account_keys})
            self.settings = live
        update_settings(change)

    def _save_visual_settings(self):
        """只保存可即时回退的外观项，不触发实例重扫或 AI 重载。"""
        self.settings['ui_theme'] = self.theme_combo.currentData()
        self.settings["ui_wallpaper_source"] = self.wallpaper_source_combo.currentData()
        self.settings["ui_wallpaper_preset"] = self.wallpaper_preset_combo.currentData()
        self.settings["ui_wallpaper_mask"] = (self.wallpaper_mask_slider.value()
                                               if self._wallpaper_mask_custom else None)
        self.settings['ui_wallpaper_blur'] = (self.wallpaper_blur_slider.value()
                                              if self._wallpaper_blur_custom else None)
        self.settings["ui_wallpaper_user_path"] = getattr(self, "_wallpaper_user_path", "")
        self.settings["ui_animations_enabled"] = self.animations_check.isChecked()
        self._save_preserving_accounts()
        try:
            from launcher_app.ui.ui_anim import set_animations_enabled
            set_animations_enabled(self.settings["ui_animations_enabled"])
        except Exception:
            pass
        self._notify_visual_saved()

    def _notify_visual_saved(self):
        if hasattr(self, "_autosave_hint"):
            self._autosave_hint.setText(t("外观已自动保存 ✓"))
        self.visual_changed.emit()

    def _pick_wallpaper_image(self):
        """选本地图片 → 复制进 AMCL/cache/wallpapers/(遵循文件放置约定),记录相对路径。"""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, t('选择壁纸图片'), "", t('图片 (*.png *.jpg *.jpeg *.bmp *.webp)'))
        if not path:
            return
        self._import_wallpaper_image(path)

    def _import_wallpaper_image(self, path):
        import os
        import shutil
        from PySide6.QtGui import QImageReader
        from paths import cache_dir
        # Validate contents, not just the extension; reject corrupt/non-image files.
        reader = QImageReader(path)
        size = reader.size()
        if not size.isValid() or size.width() * size.height() > 40_000_000:
            task_warning(self, t('选择壁纸'), t('图片无法读取或太大，请选择不超过 4000 万像素的图片。'))
            return
        if reader.read().isNull():
            task_warning(self, t('选择壁纸'), t('这张图片没能打开，换一张试试？'))
            return
        try:
            wall_dir = cache_dir("wallpapers")
            ext = os.path.splitext(path)[1].lower() or ".png"
            name = f"user_{uuid.uuid4().hex}{ext}"
            shutil.copy2(path, os.path.join(wall_dir, name))
            self._wallpaper_user_path = os.path.join("wallpapers", name)
            self.wallpaper_user_label.setText(os.path.basename(path))
            index = self.wallpaper_source_combo.findData("user")
            if index >= 0:
                self.wallpaper_source_combo.setCurrentIndex(index)
            self._queue_visual_autosave()
        except Exception as e:
            task_warning(self, t('选择壁纸'), t('复制图片失败:{v0}: {v1}').format(v0=(type(e).__name__), v1=(e)))

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
            self._mcp_status.setText(t('已生成 {v0} 与 {v1}(在 AMCL 文件夹)').format(v0=(cfg_path), v1=(cmd_path)))

    # ---- 配色(自定义主题) ----
    def _refresh_color_btn_text(self):
        from launcher_app.ui.ui_style import get_custom_colors
        cur = get_custom_colors()
        labels = {"accent": "强调色", "text": "文字色", "muted": "次要文字", "panel_bg": "背景色"}
        for slot, b in getattr(self, "_color_btns", {}).items():
            v = cur.get(slot)
            b.setText(t(labels.get(slot, slot)) + ': ' + (v if v else t('默认')))

    def _update_readability(self):
        """改色后检查文字/强调色是否可能看不清,显示在提示行。"""
        try:
            from launcher_app.ui.ui_style import get_custom_colors
            msgs = check_readability(get_custom_colors())
            lbl = getattr(self, "_readability_label", None)
            if lbl is None:
                return
            if msgs:
                lbl.setStyleSheet(f"color:{danger_color()}; font-size:11px;")
                lbl.setText("\n".join(msgs))
            else:
                lbl.setStyleSheet(f"color:{success_color()}; font-size:11px;")
                lbl.setText(t("配色可读性良好（文字、强调色与背景对比适中）。"))
        except Exception:
            pass

    def _apply_cb_preset(self):
        """应用色盲/色弱配色模板(无障碍预设)。"""
        from launcher_app.ui.ui_style import apply_color_blind_preset
        name = self._cb_combo.currentData() or ""
        if not name:
            return
        cols = apply_color_blind_preset(name)
        if not cols:
            return
        from launcher_app.ui.ui_style import set_custom_colors
        set_custom_colors(cols)
        self.settings["ui_custom_colors"] = cols
        self._save_preserving_accounts()
        self._notify_visual_saved()
        self._refresh_color_btn_text()
        self._retheme()
        self._update_readability()

    def _pick_color(self, slot: str, label: str):
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog
        from launcher_app.ui.ui_style import get_custom_colors, set_custom_colors
        cur = get_custom_colors()
        start = QColor(cur.get(slot)) if cur.get(slot) else QColor(accent_color())
        c = QColorDialog.getColor(start, self, f"选择{label}")
        if not c.isValid():
            return
        cols = dict(cur); cols[slot] = c.name()
        set_custom_colors(cols)
        self.settings["ui_custom_colors"] = cols
        self._save_preserving_accounts()
        self._notify_visual_saved()
        self._refresh_color_btn_text()
        self._retheme()
        self._update_readability()

    def _reset_colors(self):
        from launcher_app.ui.ui_style import clear_custom_colors
        clear_custom_colors()
        self.settings["ui_custom_colors"] = {}
        self._save_preserving_accounts()
        self._notify_visual_saved()
        self._refresh_color_btn_text()
        self._retheme()
        self._update_readability()

    def _retheme(self):
        """自定义配色改了 → 实时重刷整应用上色(之前要重启才生效)。
        也清空主题化图标缓存,让图标颜色跟随新配色。"""
        try:
            from launcher_app.ui.ui_style import refresh_theme
            refresh_theme()
        except Exception:
            pass
        try:
            from launcher_app.ui.theme_icon import recolor_icons
            recolor_icons()
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

    def _open_changelog(self):
        """更新日志对话框(从首页标签页搬来;首次打开时才拉取)。"""
        from launcher_app.ui.changelog_dialog import ChangelogDialog
        ChangelogDialog(self).exec()

    # ================= 系统 =================
    def _build_system(self) -> QWidget:
        """与视觉外观无关的维护项集中在这里，避免“个性化”页变成杂物间。"""
        w = QWidget()
        l = QVBoxLayout(w); l.setContentsMargins(16, 12, 16, 12); l.setSpacing(10)

        page_layout = l
        maintenance = SettingsSection(t('启动器维护'))
        page_layout.addWidget(maintenance)
        l = maintenance.content
        hint = QLabel(t("更新、教程和缓存都放在这里；不会影响你的游戏存档或已安装的 Mod。"))
        hint.setWordWrap(True); hint.setStyleSheet(f"color:{muted_color()};")
        l.addWidget(hint)
        self.task_notifications_check = ToggleSwitch(bool(self.settings.get('ui_task_notifications', True)))
        l.addWidget(setting_switch_row(t('任务提示集中到状态球'), self.task_notifications_check,
            t('关闭可恢复传统提示窗口；文件选择、授权、EULA 和 AI 交互保留专用界面。')))

        update_btn = QPushButton(t("CHECK_FOR_UPDATES"))
        tutorial_btn = QPushButton(t("REPLAY_GUIDED_TUTORIAL"))
        # 更新日志从首页标签页搬到这里:与「检查更新」同属「关于启动器自身」的动作。
        changelog_btn = QPushButton(t("更新日志"))
        for btn in (update_btn, tutorial_btn, changelog_btn):
            btn.setMinimumHeight(34); set_style(btn, card_btn_style)
        update_btn.clicked.connect(self._open_update)
        tutorial_btn.clicked.connect(self._open_guide)
        changelog_btn.clicked.connect(self._open_changelog)
        actions = QHBoxLayout()
        actions.addWidget(update_btn); actions.addWidget(changelog_btn)
        actions.addWidget(tutorial_btn); actions.addStretch()
        l.addLayout(actions)

        reset_notices = QPushButton(t('恢复所有“不再提示”'))
        reset_notices.setToolTip(t('恢复杀毒接续说明、内存建议、备份提醒及插件推荐提示；不会启用插件或更改杀毒设置。'))
        def restore_notices():
            from launcher_app.ui.optional_notices import reset_optional_notices
            restored = reset_optional_notices()
            keys = ('dismissed_notices', 'ignore_memory_launch_advice', 'backup_remind_on_exit',
                    'plugin_prompt_declined', 'plugin_prompt_seen')
            for key in keys:
                self.settings[key] = restored[key]
            if hasattr(self, 'backup_remind_check'):
                self.backup_remind_check.setChecked(True)
            owner = self.window()
            if isinstance(getattr(owner, 'settings', None), dict):
                owner.settings.update({key: restored[key] for key in keys})
            reset_notices.setText(t('已恢复全部提示'))
        reset_notices.clicked.connect(restore_notices)
        l.addWidget(reset_notices)

        cache_section = SettingsSection(t('缓存管理'))
        page_layout.addWidget(cache_section)
        l = cache_section.content
        cache_hint = QLabel(t("清除后不会删 Mod、实例或存档；下次打开资源详情时会重新下载图片或翻译。"))
        cache_hint.setWordWrap(True); cache_hint.setStyleSheet(f"color:{muted_color()};")
        clear_icon_btn = QPushButton(t("清除 Mod 图片缓存"))
        clear_desc_btn = QPushButton(t("清除描述翻译缓存"))
        for btn in (clear_icon_btn, clear_desc_btn):
            btn.setMinimumHeight(34); set_style(btn, card_btn_style)
        clear_icon_btn.clicked.connect(lambda: self._clear_cache("icons"))
        clear_desc_btn.clicked.connect(lambda: self._clear_cache("desc"))
        cache_row = QHBoxLayout(); cache_row.addWidget(clear_icon_btn); cache_row.addWidget(clear_desc_btn); cache_row.addStretch()
        l.addWidget(cache_hint); l.addLayout(cache_row)

        cf_section = SettingsSection(t('CurseForge 资源'))
        page_layout.addWidget(cf_section)
        l = cf_section.content
        cf_hint = QLabel(t('官方发行版可使用内置的获批应用 Key；自行构建或需要覆盖时，可填写自己的获批 Key。自定义 Key 仅保存在本机，请勿发到聊天或提交到 Git。作者的第三方分发限制仍然适用。'))
        cf_hint.setOpenExternalLinks(True); cf_hint.setWordWrap(True)
        cf_hint.setStyleSheet(f"color:{muted_color()};")
        self.curseforge_key_edit = QLineEdit(self.settings.get("curseforge_api_key", ""))
        self.curseforge_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.curseforge_key_edit.setPlaceholderText(t('仅限获批的 Third-Party API Key；不要把密钥发到聊天或提交到 Git'))
        l.addWidget(cf_hint); l.addWidget(self.curseforge_key_edit); page_layout.addStretch()
        return self._wrap_scroll(w)

    # ================= 软件信息 =================
    def _software_info_card(self, name: str, role: str, license_name: str,
                            description: str, project_url: str,
                            license_url: str = "") -> QWidget:
        """创建软件信息页使用的统一鸣谢卡片。"""
        card = QWidget()
        card.setObjectName("software_component_card")
        card.setStyleSheet(
            f"QWidget#software_component_card {{ {panel_style()} }}"
            "QWidget#software_component_card QLabel { border: none; background: transparent; }"
        )
        card.setMinimumHeight(126)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(5)

        title = QLabel(f"<b>{t(name)}</b>")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setStyleSheet(f"font-size:15px; color:{text_color()};")
        meta = QLabel(f"{t(role)} · {t(license_name)}")
        meta.setObjectName("software_component_meta")
        meta.setStyleSheet(f"color:{accent_color()}; font-size:11px; font-weight:bold;")
        body = QLabel(t(description))
        body.setWordWrap(True)
        body.setStyleSheet(f"color:{muted_color()};")
        links = f'<a href="{project_url}">{t("项目主页")}</a>'
        if license_url:
            links += f' · <a href="{license_url}">{t("许可证")}</a>'
        link_label = QLabel(links)
        link_label.setTextFormat(Qt.TextFormat.RichText)
        link_label.setOpenExternalLinks(True)
        link_label.setStyleSheet(f"color:{accent_color()};")

        layout.addWidget(title)
        layout.addWidget(meta)
        layout.addWidget(body, 1)
        layout.addWidget(link_label)
        return card

    def _build_software_info(self) -> QWidget:
        from launcher_app.core.updater import VERSION
        w = QWidget()
        l = QVBoxLayout(w); l.setContentsMargins(16, 12, 16, 12); l.setSpacing(12)

        product_card = QWidget()
        product_card.setObjectName("software_product_card")
        product_card.setStyleSheet(
            f"QWidget#software_product_card {{ {panel_style()} }}"
            "QWidget#software_product_card QLabel { border: none; background: transparent; }"
        )
        product_layout = QVBoxLayout(product_card)
        product_layout.setContentsMargins(16, 14, 16, 14)
        product_layout.setSpacing(5)
        title = QLabel("Agent Minecraft Launcher")
        title.setStyleSheet(f"font-size:18px; font-weight:bold; color:{text_color()};")
        version = QLabel(t('当前版本：{v0}').format(v0=(VERSION)))
        version.setStyleSheet(f"color:{muted_color()};")
        description = QLabel(t("Minecraft 实例、资源、联机与 AI 辅助管理工具。"))
        description.setWordWrap(True)
        project_links = QLabel(
            t('<a href="https://github.com/erfanyo/Agent_Minecraft_Launcher">源代码</a>\u3000·\u3000<a href="https://github.com/erfanyo/Agent_Minecraft_Launcher/blob/main/LICENSE">GPL-3.0-only 许可证</a>'))
        project_links.setTextFormat(Qt.TextFormat.RichText)
        project_links.setOpenExternalLinks(True)
        project_links.setStyleSheet(f"color:{accent_color()};")
        product_layout.addWidget(title); product_layout.addWidget(version)
        product_layout.addWidget(description); product_layout.addWidget(project_links)
        l.addWidget(product_card)

        thanks_title = QLabel(t("鸣谢"))
        thanks_title.setStyleSheet(f"font-size:16px; font-weight:bold; color:{text_color()};")
        thanks_hint = QLabel(t('感谢这些项目为启动器的界面、下载、诊断、AI 和联机功能提供基础能力。'))
        thanks_hint.setWordWrap(True); thanks_hint.setStyleSheet(f"color:{muted_color()};")
        l.addWidget(thanks_title); l.addWidget(thanks_hint)

        components = [
            ("Qt for Python / PySide6", "随程序运行", "LGPL-3.0 / GPL-3.0 / 商业许可",
             "构建启动器的桌面界面。", "https://doc.qt.io/qtforpython-6/",
             "https://doc.qt.io/qtforpython-6/licenses.html"),
            ("Requests", "随程序运行", "Apache-2.0",
             "处理版本清单、资源、登录和模型下载等网络请求。", "https://github.com/psf/requests",
             "https://github.com/psf/requests/blob/main/LICENSE"),
            ("psutil", "随程序运行", "BSD-3-Clause",
             "检测可用内存并记录游戏进程的资源占用。", "https://github.com/giampaolo/psutil",
             "https://github.com/giampaolo/psutil/blob/master/LICENSE"),
            ("cryptography", "可选功能", "Apache-2.0 或 BSD",
             "用于验证第三方插件的 Ed25519 签名。", "https://github.com/pyca/cryptography",
             "https://github.com/pyca/cryptography/blob/main/LICENSE"),
            ("pywebview", "可选界面", "BSD-3-Clause",
             "使用系统 WebView 承载网页界面，不随程序打包 Chromium。", "https://github.com/r0x0r/pywebview",
             "https://github.com/r0x0r/pywebview/blob/master/LICENSE"),
            ("llama.cpp", "本地 AI 运行时", "MIT",
             "在本机运行可选的小型语言模型。", "https://github.com/ggml-org/llama.cpp",
             "https://github.com/ggml-org/llama.cpp/blob/master/LICENSE"),
            ("Qwen3.5-0.8B", "按需下载模型", "Apache-2.0",
             "为本地 AI 提供基础模型；只在用户选择本地模型时下载。", "https://huggingface.co/Qwen/Qwen3.5-0.8B",
             "https://huggingface.co/Qwen/Qwen3.5-0.8B/blob/main/LICENSE"),
            ("EasyTier", "启用联机插件后自动准备", "LGPL-3.0",
             "为虚拟局域网联机提供底层组网能力。它是独立项目；启动房间由用户操作触发。",
             "https://github.com/EasyTier/EasyTier",
             "https://github.com/EasyTier/EasyTier/blob/main/LICENSE"),
            ("Terracotta / 陶瓦联机", "启用联机插件后自动准备", "AGPL-3.0-or-later（含独立程序集成例外）",
             "感谢 burningtnt 开发陶瓦联机，为跨启动器 Minecraft 房间码联机提供能力。AMCL 下载原版程序并通过其进程间接口连接。",
             "https://github.com/burningtnt/Terracotta",
             "https://github.com/burningtnt/Terracotta/blob/master/LICENSE"),
            ("PyInstaller", "仅用于构建", "GPL-2.0-or-later（含启动器例外）",
             "把开发版本构建为可分发的 Windows 程序。", "https://pyinstaller.org/",
             "https://pyinstaller.org/en/stable/license.html"),
        ]
        grid = QGridLayout(); grid.setContentsMargins(0, 0, 0, 0); grid.setSpacing(10)
        for index, component in enumerate(components):
            grid.addWidget(self._software_info_card(*component), index // 2, index % 2)
        grid.setColumnStretch(0, 1); grid.setColumnStretch(1, 1)
        l.addLayout(grid)

        service_title = QLabel(t("服务与社区"))
        service_title.setStyleSheet(f"font-size:16px; font-weight:bold; color:{text_color()};")
        service_hint = QLabel(
            t('资源搜索与兼容版本查找使用 <a href="https://modrinth.com">Modrinth</a>；Minecraft 文件的国内镜像加速由 <a href="https://bmclapidoc.bangbang93.com">BMCLAPI</a> 提供。这些是独立的外部服务，是否使用由下载策略和用户操作决定。'))
        service_hint.setTextFormat(Qt.TextFormat.RichText)
        service_hint.setOpenExternalLinks(True); service_hint.setWordWrap(True)
        service_hint.setStyleSheet(f"color:{muted_color()};")
        l.addWidget(service_title); l.addWidget(service_hint); l.addStretch()
        return self._wrap_scroll(w)

    def _build_java(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        section = SettingsSection(t('Java 运行时管理'))
        layout.addWidget(section)
        self._add_java_manager(section.content)
        layout.addStretch()
        return self._wrap_scroll(page)

    def _add_java_manager(self, layout: QVBoxLayout):
        title = QLabel(t("Java 运行时"))
        title.setStyleSheet(f"font-weight:bold; color:{text_color()};")
        hint = QLabel(
            t("启动器会按 Minecraft 版本自动选择 Java。这里可以准备 Java 8/17/21/25，"
            "或登记整合包要求的特殊 Java；单个实例仍可在「实例详情 → 启动设置」中覆盖。"))
        hint.setWordWrap(True); hint.setStyleSheet(f"color:{muted_color()};")
        self.java_list = QListWidget()
        self.java_list.setMinimumHeight(130)
        self.java_status = QLabel(t("尚未扫描"))
        self.java_status.setWordWrap(True); self.java_status.setStyleSheet(f"color:{muted_color()};")

        refresh_btn = QPushButton(t("重新扫描"))
        add_btn = QPushButton(t("添加已有 Java…"))
        open_btn = QPushButton(t("打开运行时目录"))
        prepare_btn = QPushButton(t("准备 Java…"))
        from PySide6.QtWidgets import QMenu
        from launcher_app.ui.ui_style import popup_menu_style
        prepare_menu = QMenu(prepare_btn)
        set_style(prepare_menu, popup_menu_style)
        for major in (8, 17, 21, 25):
            prepare_menu.addAction(f"Java {major}", lambda _checked=False, m=major: self._install_java(m))
        prepare_btn.clicked.connect(lambda: prepare_menu.popup(
            prepare_btn.mapToGlobal(prepare_btn.rect().bottomLeft())))
        self._java_buttons = [refresh_btn, add_btn, open_btn, prepare_btn]
        for button in self._java_buttons:
            button.setMinimumHeight(32); set_style(button, card_btn_style)
        refresh_btn.clicked.connect(self._refresh_java_list)
        add_btn.clicked.connect(self._add_existing_java)
        open_btn.clicked.connect(self._open_java_runtime_dir)

        row = QHBoxLayout()
        row.addWidget(prepare_btn)
        row.addWidget(add_btn); row.addWidget(refresh_btn); row.addStretch()
        row2 = QHBoxLayout()
        row2.addWidget(open_btn); row2.addStretch()
        layout.addWidget(title); layout.addWidget(hint); layout.addWidget(self.java_list)
        layout.addLayout(row); layout.addLayout(row2); layout.addWidget(self.java_status)
        self._refresh_java_list()

    def _set_java_busy(self, busy: bool):
        for button in getattr(self, "_java_buttons", []):
            button.setEnabled(not busy)

    def _run_java_task(self, work, on_success, initial_status: str):
        if self._java_task is not None and self._java_task.is_running:
            self.java_status.setText(t("已有 Java 任务正在进行…"))
            return
        self.java_status.setText(initial_status)
        self._set_java_busy(True)
        task = BackgroundTask(work, self)
        self._java_task = task
        task.status.connect(self.java_status.setText)
        task.progress.connect(
            lambda done, total: self.java_status.setText(
                t('处理中… {v0}%').format(v0=(int(done * 100 / total) if total else 0))))
        task.succeeded.connect(on_success)
        task.failed.connect(lambda error: self.java_status.setText(t('Java 操作失败：{v0}').format(v0=(error))))
        task.finished.connect(lambda: self._set_java_busy(False))
        task.start()

    def _refresh_java_list(self):
        preferred = dict(self.settings.get("java_paths") or {})
        self._run_java_task(
            lambda _task: __import__('launcher_app.runtime.java_manager', fromlist=['*']).list_java_installations(
                paths.RUNTIME_DIR, preferred.values()),
            self._show_java_installations,
            "正在后台扫描 Java，不会阻塞设置页…",
        )

    def _show_java_installations(self, installations):
        self.java_list.clear()
        preferred = dict(self.settings.get("java_paths") or {})
        for info in installations or []:
            path = info["path"]
            item = QListWidgetItem(
                f"Java {info['major']} · {info['source']}\n{path}")
            item.setData(Qt.ItemDataRole.UserRole, info)
            self.java_list.addItem(item)
        self.java_status.setText(
            t('找到 {v0} 个 Java，启动时会按游戏版本自动选择。').format(v0=(self.java_list.count()))
            if self.java_list.count() else t('没有找到 Java；可让启动器准备 Java 8/17/21/25。'))

    def _add_existing_java(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, t('添加已有 Java'), "", t('Java (java.exe javaw.exe);;所有文件 (*)'))
        if not path:
            return
        self._run_java_task(
            lambda _task: (path, __import__('launcher_app.runtime.java_manager', fromlist=['*']).java_major(path)),
            lambda result: self._remember_java(*result),
            "正在识别 Java 版本…",
        )

    def _install_java(self, major: int):
        def work(task):
            from launcher_app.runtime.java_manager import ensure_java
            return ensure_java(
                paths.RUNTIME_DIR, major, max_major=major, prefer_managed=True,
                status_callback=task.report_status,
                progress_callback=task.report_progress,
            )
        self._run_java_task(
            work,
            lambda path, m=major: self._remember_java(path, m),
            f"正在准备 Java {major}…",
        )

    def _remember_java(self, path: str, major: int):
        if not path or int(major or 0) <= 0:
            self.java_status.setText(t("无法读取这个 Java 的版本，请确认选择的是 java.exe。"))
            return
        preferred = dict(self.settings.get("java_paths") or {})
        preferred[str(int(major))] = path
        self.settings["java_paths"] = preferred
        self._save_preserving_accounts()
        self.runtime_changed.emit()
        self.java_status.setText(t('Java {v0} 已准备好。').format(v0=(major)))
        QTimer.singleShot(0, self._refresh_java_list)

    def _selected_java(self):
        item = self.java_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _prefer_selected_java(self):
        info = self._selected_java()
        if not info:
            self.java_status.setText(t("请先选中一个 Java。"))
            return
        self._remember_java(info["path"], info["major"])

    def _forget_selected_java(self):
        info = self._selected_java()
        if not info:
            self.java_status.setText(t("请先选中一个 Java。"))
            return
        preferred = dict(self.settings.get("java_paths") or {})
        if preferred.get(str(info["major"])) == info["path"]:
            preferred.pop(str(info["major"]), None)
            self.settings["java_paths"] = preferred
            self._save_preserving_accounts()
            self.runtime_changed.emit()
        self._refresh_java_list()

    def _open_java_runtime_dir(self):
        import os
        os.makedirs(paths.RUNTIME_DIR, exist_ok=True)
        open_path(paths.RUNTIME_DIR)

    def _reopen_tutorial(self):
        p = self.window()
        if p is not None and hasattr(p, "open_tutorial"):
            p.open_tutorial()

    # ================= AI 助手 =================
    def _build_models(self) -> QWidget:
        """模型管理独立页(DSH 风格卡片):服务商/API 密钥/模型目录 + 内置模型卡片。"""
        from launcher_app.ai.model_cards import ModelCardsPanel
        self.model_cards = ModelCardsPanel(self.settings)
        self.model_cards.changed.connect(lambda: None)
        hint = QLabel(t('· 每张卡片 = 一个模型来源;点「编辑」展开配置 API 密钥 / 模型目录;\n· 「内置」卡片是启动器自带的离线小模型,展开内容为下载状态与推理后端;\n· 「+ 添加模型」可新增服务商(DeepSeek、Ollama、LM Studio、自定义等)。'))
        hint.setWordWrap(True); hint.setStyleSheet(f"color: {muted_color()};")
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(16, 12, 16, 12); l.setSpacing(10)
        l.addWidget(self.model_cards, 1)
        l.addWidget(hint)
        return self._wrap_scroll(w)

    def _build_ai(self) -> QWidget:
        self.ai_form = AISettingsForm(self.settings)
        self.mod_translate_check = ToggleSwitch(bool(self.settings.get("ai_mod_translate", True)))
        self.mod_translate_selection = dict(self.settings.get('ai_mod_translate_selection') or {})
        self.mod_translate_source = QPushButton()
        self.mod_translate_source.setEnabled(self.mod_translate_check.isChecked())
        self.mod_translate_check.toggled.connect(self.mod_translate_source.setEnabled)
        self.mod_translate_menu = QMenu(self.mod_translate_source)
        set_style(self.mod_translate_menu, popup_menu_style)
        self.mod_translate_menu.aboutToShow.connect(self._fill_translation_menu)
        self.mod_translate_source.setMenu(self.mod_translate_menu)
        self._translation_button_text()
        self.cloud_tool_log_check = ToggleSwitch(bool(self.settings.get("ai_cloud_tool_log", True)))
        self.cloud_tool_log_check.setToolTip(t("记录用户请求、工具参数、工具结果和最终回复；API 密钥会自动脱敏。"))

        hint = QLabel(t('· 云/本地两块分开配:顶部选「当前使用(AI 策略)」哪档,AI 对话就走哪边;\n· ⚠️ 本地是小模型:只懂直白指令,理解不了模糊需求(如"按功能找 mod"),甚至会选错工具;这类要靠云端,想要稳定体验请配云端(如 DeepSeek);\n· 发图片(多模态):只有所选模型本身会看图才有效,内置本地模型自动关闭。'))
        hint.setWordWrap(True); hint.setStyleSheet(f"color: {muted_color()};")

        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(16, 12, 16, 12); l.setSpacing(10)
        source_row = QHBoxLayout()
        source_row.setContentsMargins(12, 0, 12, 0)
        source_row.setSpacing(10)
        _src_lbl = QLabel(t("翻译来源:")); _src_lbl.setStyleSheet(f"color:{text_color()}; font-weight:bold;")
        source_row.addWidget(_src_lbl)
        source_row.addWidget(self.mod_translate_source, 1)
        l.addWidget(self.ai_form)
        from launcher_app.ui.settings_section import SettingsSection
        l.setSpacing(16)
        translation = SettingsSection(t('资源描述翻译'))
        translation.content.addWidget(setting_switch_row(t("Mod 描述 AI 翻译"), self.mod_translate_check, t("将英文描述翻译成中文")))
        translation.content.addLayout(source_row)
        translation_hint = QLabel(t('内置模型下载后置顶显示；其他模型按已配置的 API 供应商选择。'))
        translation_hint.setWordWrap(True)
        translation_hint.setStyleSheet(f'color:{muted_color()};')
        translation.content.addWidget(translation_hint)
        l.addWidget(translation)
        logs = SettingsSection(t('运行记录与自动回收'))
        logs.content.addWidget(setting_switch_row(t("记录云端 AI 工具调用"), self.cloud_tool_log_check,
                                       t('仅保存在本机，API 密钥会脱敏')))
        from launcher_app.ai.run_retention_ui import RunRetentionPanel
        self.run_log_retention = RunRetentionPanel(self.settings)
        logs.content.addWidget(self.run_log_retention)
        l.addWidget(logs)
        web = SettingsSection(t('公开网页访问'))
        web.content.addWidget(QLabel(t('公开网页允许的域名（逗号分隔）')))
        self.web_domains = QLineEdit(self.settings.get('ai_web_allowed_domains', 'bilibili.com,b23.tv'))
        self.web_domains.setPlaceholderText('bilibili.com,b23.tv')
        self.web_domains.setToolTip(t('允许域名及其子域名；仅匿名读取公开网页，不接入内网或浏览器账号。只添加你信任的站点。'))
        web.content.addWidget(self.web_domains)
        l.addWidget(web)
        from launcher_app.ui.cloud_drive_settings import connection_section
        self.cloud_drive_section = connection_section()
        l.addWidget(self.cloud_drive_section)
        guide = SettingsSection(t('使用说明'))
        guide.content.addWidget(hint)
        l.addWidget(guide)
        l.addStretch()
        return self._wrap_scroll(w)

    def _translation_button_text(self):
        selected = self.mod_translate_selection
        if selected.get('kind') == 'builtin':
            from launcher_app.ai.model_registry import RESOURCES
            name = RESOURCES.get(selected.get('model'), {}).get('name', selected.get('model', ''))
            text = '内置 · ' + name
        elif selected.get('kind') == 'api':
            from launcher_app.ai.model_cards import _provider_label
            text = _provider_label(selected.get('provider', '')) + ' · ' + selected.get('model', '')
        else:
            text = t('选择翻译模型')
        self.mod_translate_source.setText(text)

    def _choose_translation_model(self, kind, provider, model):
        self.mod_translate_selection = {'kind': kind, 'provider': provider, 'model': model}
        self._translation_button_text()
        self._queue_settings_save()

    def _fill_translation_menu(self):
        menu = self.mod_translate_menu
        menu.clear()
        from launcher_app.ai.model_registry import RESOURCES, is_downloaded
        from launcher_app.ai.model_cards import _provider_label
        for model, resource in RESOURCES.items():
            if is_downloaded(model):
                action = menu.addAction(t('内置 · ') + resource.get('name', model))
                action.triggered.connect(lambda checked=False, m=model: self._choose_translation_model('builtin', '', m))
        settings = dict(self.settings)
        settings.update(self.ai_form.values())
        if hasattr(self, 'model_cards'):
            settings.update(self.model_cards.values())
        providers = dict(settings.get('ai_model_providers') or {})
        pid = settings.get('ai_cloud_provider', '')
        if pid and pid not in providers:
            providers[pid] = {'base_url': settings.get('ai_cloud_base_url', ''),
                              'models': (settings.get('ai_cloud_models') or {}).get(pid) or
                              [{'id': settings.get('ai_cloud_model', '')}]}
        if settings.get('ai_local_mode') in ('ollama', 'lmstudio'):
            pid = settings['ai_local_mode']
            providers.setdefault(pid, {'base_url': settings.get('ai_local_endpoint') or
                ('http://127.0.0.1:11434/v1' if pid == 'ollama' else 'http://127.0.0.1:1234/v1'),
                'models': [{'id': settings.get('ai_external_model', '')}]})
        if menu.actions() and providers:
            menu.addSeparator()
        for pid, data in providers.items():
            if not data.get('base_url'):
                continue
            rows = data.get('models') or []
            models = [row for row in rows if isinstance(row, dict) and row.get('id')]
            if not models:
                continue
            submenu = menu.addMenu(_provider_label(pid))
            set_style(submenu, popup_menu_style)
            for row in models:
                model = row['id']
                action = submenu.addAction(row.get('name') or model)
                action.triggered.connect(lambda checked=False, p=pid, m=model: self._choose_translation_model('api', p, m))
        if not menu.actions():
            menu.addAction(t('请先下载内置模型或配置 API 模型')).setEnabled(False)

    def _is_model_downloaded(self) -> bool:
        try:
            import launcher_app.ai.model_registry as model_registry
            return model_registry.is_downloaded("qwen3.5-0.8b-xlam-q4km")
        except Exception:
            return False

    def _init_model_dl_button(self):
        if not hasattr(self, "model_dl_btn"):
            return   # 旧下载按钮已移除(下载入口改为内置模型卡片),此方法保留兼容但不再有控件
        ready = self._is_model_downloaded()
        if ready:
            self.model_dl_btn.setText(t("READY"))
            self.model_dl_btn.setEnabled(False)
            self.model_dl_status.setText(t("LOCAL_MODEL_DOWNLOADED_READY"))
        else:
            self.model_dl_btn.setText(t("DOWNLOAD_LOCAL_MODEL"))
            self.model_dl_btn.setEnabled(True)
            self.model_dl_status.setText(t("NOT_DOWNLOADED_500MB_CLICK_TO_START"))

    def _start_model_download(self):
        if not hasattr(self, "model_dl_btn"):
            return
        if self._model_downloading:
            return
        if self._is_model_downloaded():
            self._init_model_dl_button()
            return
        self._model_downloading = True
        self.model_dl_btn.setEnabled(False)
        self.model_dl_btn.setText(t("DOWNLOADING_0"))
        self.model_dl_status.setText(t("DOWNLOADING_LOCAL_MODEL_MIRROR_FIRST"))
        host = self.window()
        if host is not None and hasattr(host, "model_download_progress"):
            host.model_download_progress("正在下载本地模型(约500MB,镜像优先)…", 0, 1)

        def worker():
            ok, msg = True, "✅ 本地模型下载完成,之后可用内置本地模型。"
            try:
                import launcher_app.ai.model_registry as model_registry
                model_registry.download("qwen3.5-0.8b-xlam-q4km",
                                        progress_callback=lambda d, total: self._dl_progress.emit(d, total))
            except Exception as e:
                ok = False
                msg = f"❌ 本地模型下载失败:{type(e).__name__}: {str(e)[:200]}"
            self._dl_finished.emit(ok, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_model_dl_progress(self, done, total):
        if not hasattr(self, "model_dl_btn"):
            return
        pct = int(done * 100 / total) if total else 0
        self.model_dl_btn.setText(t(f"下载中 {pct}%…", f"Downloading {pct}%…"))
        host = self.window()
        if host is not None and hasattr(host, "model_download_progress"):
            host.model_download_progress("", done, total)

    def _on_model_dl_finished(self, ok, msg):
        if not hasattr(self, "model_dl_btn"):
            return
        self._model_downloading = False
        self.model_dl_status.setText(msg)
        host = self.window()
        if host is not None and hasattr(host, "model_download_done"):
            host.model_download_done(ok, msg)
        if ok:
            self.model_dl_btn.setText(t("READY"))
            self.model_dl_btn.setEnabled(False)
        else:
            self.model_dl_btn.setText(t("DOWNLOAD_LOCAL_MODEL"))
            self.model_dl_btn.setEnabled(True)

    # ================= 镜像源 =================
    def _build_mirror(self) -> QWidget:
        self.mirror_region_combo = QComboBox()
        self.mirror_region_combo.addItem(t("选择地区推荐…"), None)
        for key, (label, _strategy, _mirror) in MIRROR_REGION_PRESETS.items():
            self.mirror_region_combo.addItem(t(label), key)
        self.mirror_region_combo.currentIndexChanged.connect(self._apply_mirror_region_preset)
        region_hint = QLabel(t('地区推荐只填写下方策略和镜像站；欧洲、美洲、非洲与中东优先使用官方 CDN。'))
        region_hint.setWordWrap(True)
        region_hint.setStyleSheet(f"color: {muted_color()};")
        self.strategy_combo = QComboBox()
        for key, info in MIRROR_STRATEGIES.items():
            self.strategy_combo.addItem(t(info["name"]), key)
        idx = self.strategy_combo.findData(self.settings.get("mirror_strategy", "smart_official"))
        self.strategy_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.strategy_combo.currentIndexChanged.connect(self._on_strategy_changed)
        self.strategy_hint = QLabel(""); self.strategy_hint.setWordWrap(True)
        self.strategy_hint.setStyleSheet(f"color: {muted_color()};")
        self._update_strategy_hint()

        self.mirror_combo = QComboBox()
        self.mirror_hint = QLabel(""); self.mirror_hint.setWordWrap(True)
        self.mirror_hint.setStyleSheet(f"color: {muted_color()};")
        self._refresh_mirror_combo()
        self.mirror_combo.currentIndexChanged.connect(self._update_mirror_hint)
        self.mirror_combo.setEnabled(self.strategy_combo.currentData() != "official_only")

        self.custom_name_edit = QLineEdit(); self.custom_name_edit.setPlaceholderText(t("名称,如 我的镜像"))
        self.custom_url_edit = QLineEdit(); self.custom_url_edit.setPlaceholderText(t("base 地址,如 https://mirror.example.com"))
        add_btn = QPushButton(t("添加")); add_btn.clicked.connect(self._add_custom_mirror)
        add_row = QHBoxLayout(); add_row.addWidget(self.custom_name_edit, 1)
        add_row.addWidget(self.custom_url_edit, 2); add_row.addWidget(add_btn)
        self.custom_list = QListWidget(); self.custom_list.setMinimumHeight(90)
        self._refresh_custom_list()
        del_btn = QPushButton(t("删除选中")); del_btn.clicked.connect(self._remove_custom_mirror)
        del_row = QHBoxLayout(); del_row.addStretch(); del_row.addWidget(del_btn)

        form = QFormLayout()
        form.addRow(t("地区推荐:"), self.mirror_region_combo)
        form.addRow("", region_hint)
        form.addRow(t("下载策略:"), self.strategy_combo)
        form.addRow("", self.strategy_hint)
        form.addRow(t("镜像站:"), self.mirror_combo)
        form.addRow("", self.mirror_hint)

        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(16, 12, 16, 12)
        l.setSpacing(16)
        routing = SettingsSection(t('下载来源与镜像策略'))
        routing.content.addLayout(form)
        custom = SettingsSection(t('自定义镜像'))
        custom.content.addWidget(QLabel(t('与 BMCLAPI 同构：填 base 地址，自动映射 libraries / assets / version 等路径。')))
        custom.content.addLayout(add_row)
        custom.content.addWidget(self.custom_list)
        custom.content.addLayout(del_row)
        l.addWidget(routing); l.addWidget(custom); l.addStretch()
        return w

    def _apply_mirror_region_preset(self):
        key = self.mirror_region_combo.currentData()
        preset = MIRROR_REGION_PRESETS.get(key)
        if not preset:
            return
        _, strategy, mirror = preset
        strategy_idx = self.strategy_combo.findData(strategy)
        mirror_idx = self.mirror_combo.findData(mirror)
        if strategy_idx >= 0:
            self.strategy_combo.setCurrentIndex(strategy_idx)
        if mirror_idx >= 0:
            self.mirror_combo.setCurrentIndex(mirror_idx)

    def _build_plugins(self) -> QWidget:
        """插件管理:列出 plugins/*.py(开关启停)。整页放进滚动条,避免垂直拥挤。
        - 启用/禁用 = 开关样式(默认为关即表示默认关闭,不写文字);
        - 标题大、描述小;注册内容移到 tooltip(悬停才显示);
        - 有独立设置页的插件 → 开关旁齿轮按钮,点击跳到该插件设置页。"""
        import launcher_app.extensions.plugin_manager as plugin_manager
        page = QWidget()
        l = QVBoxLayout(page); l.setContentsMargins(16, 12, 16, 12); l.setSpacing(8)
        head = QLabel(t('插件 = 启动器的可选功能模块。\n核心组件(启动/实例/下载/设置/AI)不在插件列表里,保证稳定。'))
        head.setWordWrap(True); head.setStyleSheet(f"color: {muted_color()};")
        head_row = QHBoxLayout()
        head_row.addWidget(head, 1)
        # 右上角:重启启动器(生成/禁用插件后手动重启生效)
        restart_btn = QPushButton(t("RESTART_TO_APPLY"))
        set_style(restart_btn, card_btn_style); restart_btn.setMinimumHeight(32)
        restart_btn.setToolTip(t('插件启停/新增后需重启启动器才生效。'))
        restart_btn.clicked.connect(self._restart_launcher)
        head_row.addWidget(restart_btn)
        l.addLayout(head_row)

        third_party_row = QHBoxLayout()
        third_party_label = QLabel(t('允许 AI 制作 / 第三方插件（可执行本机 Python 代码，未经沙箱隔离）'))
        third_party_label.setWordWrap(True)
        self.third_party_plugins_switch = ToggleSwitch(bool(self.settings.get('third_party_plugins_enabled', False)))
        self.third_party_plugins_switch.setAccessibleName(t('允许第三方插件'))
        self.third_party_plugins_switch.toggled.connect(self._toggle_third_party_plugins)
        third_party_row.addWidget(third_party_label, 1)
        third_party_row.addWidget(self.third_party_plugins_switch)
        l.addLayout(third_party_row)

        disabled = set(self.settings.get("plugins_disabled", []) or [])
        enabled_override = set(self.settings.get("plugins_enabled", []) or [])
        metas = plugin_manager.discover_plugins_meta()
        category_layouts = {}
        for category in ('Mod 管理', '功能'):
            toggle = QPushButton(t(category))
            toggle.setCheckable(True)
            toggle.setChecked(True)
            set_style(toggle, card_btn_style)
            l.addWidget(toggle)
            container = QWidget()
            group = QVBoxLayout(container)
            group.setContentsMargins(0, 0, 0, 0)
            toggle.toggled.connect(container.setVisible)
            l.addWidget(container)
            category_layouts[category] = group
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
            set_style(title, lambda: f"font-weight:bold; font-size:15px; color:{text_color()};")
            # 注册内容 → tooltip(悬停显示)
            contents = self._describe_plugin(name, None)
            if contents:
                title.setToolTip(f"{pname}({name}.py)\n{contents}")
            row.addWidget(title, 1)
            # 有独立设置页 → 齿轮按钮
            if meta.get("has_settings"):
                gear = QToolButton()
                gear.setText("⚙")
                gear.setToolTip(t("插件设置"))
                gear.setCursor(Qt.CursorShape.PointingHandCursor)
                gear.clicked.connect(lambda _c, n=name: self._goto_plugin_setting(n))
                row.addWidget(gear)
            # 开关
            tsw = ToggleSwitch(is_on)
            tsw.setAccessibleName(t('启用插件 {v0}').format(v0=(pname)))
            tsw.toggled.connect(lambda ch, n=name: self._toggle_plugin(n, ch))
            row.addWidget(tsw)
            cl.addLayout(row)
            if pdesc:
                d = QLabel(pdesc); d.setWordWrap(True)
                set_style(d, lambda: f"color: {muted_color()}; font-size: 11px;")
                cl.addWidget(d)
            api_version = meta.get("api_version", 0)
            if api_version != plugin_manager.PLUGIN_API_VERSION:
                compatibility = QLabel(
                    t('需要更新：此插件声明 API {v0}，当前启动器需要 API {v1}。').format(v0=(api_version or t('未声明')), v1=(plugin_manager.PLUGIN_API_VERSION)))
                compatibility.setWordWrap(True)
                compatibility.setStyleSheet("color: #d68a3b; font-size: 11px;")
                cl.addWidget(compatibility)
            category_layouts[plugin_manager.plugin_category(name)].addWidget(card)

        if not plugin_manager.discover_plugins():
            empty = QLabel(t('还没有插件。把 .py 插件放进启动器的 plugins/ 目录即可;或让 AI 按模板生成一个(见「插件模板」)。'))
            empty.setWordWrap(True); empty.setStyleSheet(f"color: {muted_color()};")
            l.addWidget(empty)
        l.addStretch()

        # 放进滚动区(垂直拥挤也能滚)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setWidget(page)
        return scroll

    def _toggle_third_party_plugins(self, checked):
        if checked:
            phrase = '我已清楚ai制作/第三方插件的风险'
            text, accepted = QInputDialog.getText(
                self, t('开启第三方插件'),
                t('第三方插件可以读写本机文件、访问网络及运行程序。\n此开关不代表插件已审核或已隔离。\n\n请输入以下文字确认：\n') + phrase)
            if not accepted or text.strip() != phrase:
                self.third_party_plugins_switch.blockSignals(True)
                self.third_party_plugins_switch.setChecked(False)
                self.third_party_plugins_switch.blockSignals(False)
                return
        self.settings['third_party_plugins_enabled'] = bool(checked)
        update_settings(lambda live: live.update(third_party_plugins_enabled=bool(checked)))
        self._autosave_hint.setText(t('第三方插件设置已保存，重启启动器后生效'))

    def _plugin_page_with_toggle(self, pid: str, build_fn) -> QWidget:
        """给插件的独立设置页加一个顶部开关条(启用/禁用本插件)。
        这样在「插件:xxx」设置页里也能直接开关,不用回插件管理页。"""
        import launcher_app.extensions.plugin_manager as plugin_manager
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
        tsw.setAccessibleName(t('启用插件 {v0}').format(v0=(name)))
        tsw.toggled.connect(lambda ch, n=pid: self._toggle_plugin(n, ch))
        tl.addWidget(lbl, 1); tl.addWidget(QLabel(t("启用"))); tl.addWidget(tsw)
        lay.addWidget(top)
        # 插件设置的 build_fn 内容
        lay.addWidget(build_fn())
        return outer

    def _restart_launcher(self):
        """重启启动器(插件新增/启停后生效)。"""
        try:
            self.flush_autosave()
            import os, sys
            if getattr(sys, "frozen", False):   # PyInstaller exe
                import shutil
                exe = sys.executable
                os.spawnv(os.P_NOWAIT, exe, [exe])
            else:
                import subprocess
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                subprocess.Popen([sys.executable, os.path.join(project_root, 'main.py')],
                                 cwd=project_root)
            QApplication.closeAllWindows()
        except Exception as e:
            inline_warning(self, t('重启'), t('重启失败:{v0}: {v1}').format(v0=(type(e).__name__), v1=(e)))

    def _goto_plugin_setting(self, name: str):
        """跳到某插件的独立设置页(在设置左菜单单开一行,标签为 插件:<显示名>)。
        若插件未启用(默认关,其设置行未加载),提示先启用。"""
        try:
            import launcher_app.extensions.plugin_manager as plugin_manager
            meta = plugin_manager.discover_plugins_meta().get(name, {})
            display = meta.get("name") or name
            if self.shell.switch_by_label(f"插件:{display}"):
                return
            inline_notice(self, t('插件设置'),
                                    t('「{v0}」目前未启用(默认关闭)。\n请先把它的开关打开,再点⚙进入设置。').format(v0=(display)))
        except Exception:
            pass

    def _describe_plugin(self, name: str, mod) -> str:
        """给插件页面显示该插件注册了哪些内容。"""
        import launcher_app.extensions.plugin_manager as plugin_manager
        bits = []
        ntools = sum(1 for k in plugin_manager.TOOLS if k.startswith(f"{name}__"))
        if ntools:
            bits.append(f"AI 工具 ×{ntools}")
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
        disabled_value, enabled_value = sorted(disabled), sorted(enabled_over)
        def persist(live):
            live['plugins_disabled'] = disabled_value
            live['plugins_enabled'] = enabled_value
        update_settings(persist)
        self._autosave_hint.setText(t('插件设置已保存，重启启动器后生效'))

    def _on_strategy_changed(self):
        self._update_strategy_hint()
        self.mirror_combo.setEnabled(self.strategy_combo.currentData() != "official_only")

    def _update_strategy_hint(self):
        info = MIRROR_STRATEGIES.get(self.strategy_combo.currentData())
        self.strategy_hint.setText(t(info["desc"]) if info else "")

    def _refresh_mirror_combo(self):
        cur = self.settings.get("mirror_source", "bmclapi")
        self.mirror_combo.blockSignals(True); self.mirror_combo.clear()
        for key, info in MIRROR_SOURCES.items():
            self.mirror_combo.addItem(t(info["name"]), key)
        for cm in self._custom_mirrors:
            self.mirror_combo.addItem(t('自定义: {v0}').format(v0=(cm.get('name', '?'))), "custom:" + cm.get("id", ""))
        idx = self.mirror_combo.findData(cur)
        if idx < 0:
            idx = self.mirror_combo.findData("bmclapi")
        self.mirror_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.mirror_combo.blockSignals(False); self._update_mirror_hint()

    def _update_mirror_hint(self):
        key = self.mirror_combo.currentData()
        if key in MIRROR_SOURCES:
            self.mirror_hint.setText(t(MIRROR_SOURCES[key]["desc"]))
        elif key and key.startswith("custom:"):
            cid = key.split(":", 1)[1]
            for cm in self._custom_mirrors:
                if cm.get("id") == cid:
                    self.mirror_hint.setText(t('自定义镜像:{v0} — {v1}').format(v0=(cm.get('name', '')), v1=(cm.get('url', ''))))
                    return
        else:
            self.mirror_hint.setText("")

    def _add_custom_mirror(self):
        name = self.custom_name_edit.text().strip()
        url = self.custom_url_edit.text().strip()
        if not name or not url:
            inline_warning(self, t('镜像源'), t('请填写名称和地址')); return
        if not url.startswith(("http://", "https://")):
            inline_warning(self, t('镜像源'), t('地址必须以 http:// 或 https:// 开头')); return
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
            inline_notice(self, t('镜像源'), t('先在列表里选中要删除的自定义镜像')); return
        self._custom_mirrors.pop(row); self._refresh_custom_list(); self._refresh_mirror_combo()

    # ================= 保存 =================
    def apply(self, automatic=False):
        if hasattr(self, 'web_domains'):
            from launcher_app.browser.public_web import parse_domains
            try:
                parse_domains(self.web_domains.text())
            except ValueError as error:
                self._autosave_hint.setText(t('尚未保存网页域名：') + str(error))
                return
        if hasattr(self, 'task_notifications_check'):
            self.settings['ui_task_notifications'] = self.task_notifications_check.isChecked()
        try:
            self.settings['jvm_args'] = self.jvm_editor.values()
        except ValueError as error:
            if automatic:
                self._autosave_hint.setText(t('尚未保存：') + str(error))
            else:
                inline_warning(self, t('JVM 参数'), str(error))
            return
        self.settings["memory_gb"] = 0 if self.memory_auto_check.isChecked() else self.memory_spin.value()
        self.settings["version_isolation"] = self.isolation_check.isChecked()
        if hasattr(self, "backup_remind_check"):
            self.settings["backup_remind_on_exit"] = self.backup_remind_check.isChecked()
            self.settings["backup_auto_on_exit"] = self.backup_auto_check.isChecked()
        self.settings["game_dir"] = self.game_dir_edit.text().strip()
        self.settings["language"] = self.language_combo.currentData()
        self.settings["sync_minecraft_language"] = self.sync_minecraft_language_check.isChecked()
        self.settings["ui_mode"] = self.ui_mode_combo.currentData()
        if hasattr(self, "ai_form"):
            self.settings.update(self.ai_form.values())
            if hasattr(self, "model_cards"):
                self.settings.update(self.model_cards.values())
            self.settings["ai_mod_translate"] = self.mod_translate_check.isChecked()
            self.settings['ai_mod_translate_selection'] = dict(self.mod_translate_selection)
            self.settings["ai_cloud_tool_log"] = self.cloud_tool_log_check.isChecked()
            self.settings.update(self.run_log_retention.values())
            self.settings['ai_web_allowed_domains'] = self.web_domains.text().strip()
            self.settings['cloud_drive_defender_scan'] = self.cloud_drive_section.defender_scan.isChecked()
        self.settings["mirror_strategy"] = self.strategy_combo.currentData()
        self.settings["mirror_source"] = self.mirror_combo.currentData()
        self.settings["custom_mirrors"] = self._custom_mirrors
        self.settings["curseforge_api_key"] = self.curseforge_key_edit.text().strip()
        # 自定义背景(阶段 2)
        self.settings['ui_theme'] = self.theme_combo.currentData()
        self.settings['ui_wallpaper_blur'] = (self.wallpaper_blur_slider.value()
                                              if self._wallpaper_blur_custom else None)
        self.settings["ui_wallpaper_source"] = self.wallpaper_source_combo.currentData()
        self.settings["ui_wallpaper_preset"] = self.wallpaper_preset_combo.currentData()
        self.settings["ui_wallpaper_mask"] = (self.wallpaper_mask_slider.value()
                                               if self._wallpaper_mask_custom else None)
        if getattr(self, "_wallpaper_user_path", ""):
            self.settings["ui_wallpaper_user_path"] = self._wallpaper_user_path
        self.settings["ui_animations_enabled"] = self.animations_check.isChecked()
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
        for page in self.shell.stack.findChildren(QWidget):
            fields = getattr(page, '_browser_agent_fields', None)
            if fields:
                enabled, token = fields
                changed = (self.settings.get('browser_agent_enabled', False) != enabled.isChecked() or
                           self.settings.get('browser_extension_token', '') != token.text().strip())
                self.settings['browser_agent_enabled'] = enabled.isChecked()
                self.settings['browser_extension_token'] = token.text().strip()
                if changed:
                    from launcher_app.browser.browser_agent import close
                    close()
                break
        self._save_preserving_accounts()
        paths.set_game_dir(self.settings["game_dir"])
        try:
            import launcher_app.core.i18n as i18n
            i18n.set_language(self.settings["language"])
        except Exception:
            pass
        self.applied.emit()
        self._autosave_hint.setText(t('设置已自动保存；插件启停需重启后生效'))
