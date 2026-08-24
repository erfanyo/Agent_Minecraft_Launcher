# -*- coding: utf-8 -*-
"""
设置对话框(启动器整体设置),按功能拆成多个标签页:
- 游戏:游戏名、内存、版本隔离、游戏目录(.minecraft 位置,可指向任意已有目录)
- 界面:语言、界面模式
- AI 助手:服务商 / 接口 / 密钥 / 模型 / 文件权限 / 多模态(图片输入)
- 镜像源:选择下载镜像源(官方 / BMCLAPI / 自定义),管理自定义镜像
点"确定"时把各标签页内容写进 config.json。
"""
import uuid

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
)

import i18n
import paths
from assistant import AISettingsForm
from downloader import MIRROR_SOURCES, MIRROR_STRATEGIES
from settings import save_settings


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None, tab: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("启动器设置")
        self.setMinimumWidth(470)
        self.settings = dict(settings)  # 复制一份,点确定才真正生效
        self._custom_mirrors = [dict(c) for c in self.settings.get("custom_mirrors", []) or []]

        # ---------- 标签页:游戏 / 界面 / AI 助手 / 镜像源 ----------
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_game_tab(), "游戏")
        self.tabs.addTab(self._build_ui_tab(), "界面")
        self.tabs.addTab(self._build_ai_tab(), "AI 助手")
        self.tabs.addTab(self._build_mirror_tab(), "镜像源")
        if tab == "mirror":
            self.tabs.setCurrentIndex(self.tabs.count() - 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)

    # ================= 游戏 =================
    def _build_game_tab(self) -> QWidget:
        from PySide6.QtWidgets import QWidget

        self.username_edit = QLineEdit(self.settings.get("username", "Player"))
        self.username_edit.setPlaceholderText("离线模式显示的游戏名")

        self.memory_spin = QSpinBox()
        self.memory_spin.setRange(1, 16)
        self.memory_spin.setSuffix(" GB")
        self.memory_spin.setValue(self.settings.get("memory_gb", 2))

        self.isolation_check = QCheckBox("每个版本用独立游戏目录(存档/配置/Mod 互不干扰)")
        self.isolation_check.setChecked(self.settings.get("version_isolation", True))

        self.game_dir_edit = QLineEdit(self.settings.get("game_dir") or paths.DEFAULT_GAME_DIR)
        browse_btn = QPushButton("浏览…")
        browse_btn.clicked.connect(self._browse_game_dir)
        default_btn = QPushButton("默认")
        default_btn.setToolTip("回到启动器目录下的 .minecraft")
        default_btn.clicked.connect(lambda: self.game_dir_edit.setText(paths.DEFAULT_GAME_DIR))
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.game_dir_edit, 1)
        dir_row.addWidget(browse_btn)
        dir_row.addWidget(default_btn)

        form = QFormLayout()
        form.addRow("游戏名:", self.username_edit)
        form.addRow("内存:", self.memory_spin)
        form.addRow("版本隔离:", self.isolation_check)
        form.addRow("游戏目录:", dir_row)
        dir_hint = QLabel("可以是任意位置,包括 PCL2 / 官方启动器创建的 .minecraft(自动读取里面的实例)")
        dir_hint.setWordWrap(True)
        dir_hint.setStyleSheet("color: #888888;")

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addLayout(form)
        lay.addWidget(dir_hint)
        lay.addStretch()
        return w

    def _browse_game_dir(self):
        start = self.game_dir_edit.text().strip() or paths.DEFAULT_GAME_DIR
        d = QFileDialog.getExistingDirectory(self, "选择 Minecraft 游戏目录", start)
        if d:
            self.game_dir_edit.setText(d)

    # ================= 界面 =================
    def _build_ui_tab(self) -> QWidget:
        from PySide6.QtWidgets import QWidget

        # 界面语言(自动跟随系统,可覆盖)
        self.language_combo = QComboBox()
        for label, value in (("自动(跟随系统)", "auto"), ("中文", "zh"), ("English", "en")):
            self.language_combo.addItem(label, value)
        cur = self.settings.get("language", "auto")
        idx = self.language_combo.findData(cur)
        self.language_combo.setCurrentIndex(idx if idx >= 0 else 0)
        lang_hint = QLabel("切换语言后需重启启动器生效(检测系统语言:中文系统自动用中文)")
        lang_hint.setStyleSheet("color: #888888;")

        # 界面模式(新手多提示 / 专家少提示)
        self.ui_mode_combo = QComboBox()
        for label, value in (("新手(显示更多提示与科普)", "beginner"),
                             ("专家(精简提示)", "expert")):
            self.ui_mode_combo.addItem(label, value)
        mode = self.settings.get("ui_mode", "beginner")
        idx = self.ui_mode_combo.findData(mode)
        self.ui_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        mode_hint = QLabel("新手模式:首页显示资源结构科普、更详细的状态提示;专家模式:全部隐藏/精简。")
        mode_hint.setStyleSheet("color: #888888;")
        mode_hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("界面语言:", self.language_combo)
        form.addRow("界面模式:", self.ui_mode_combo)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addLayout(form)
        lay.addWidget(lang_hint)
        lay.addWidget(mode_hint)
        lay.addStretch()
        return w

    # ================= AI 助手 =================
    def _build_ai_tab(self) -> QWidget:
        from PySide6.QtWidgets import QWidget

        # AI 策略三档:决定 AI 对话走本地/云端/混合(业务化文案,保存到 ai_strategy)
        self.ai_strategy_combo = QComboBox()
        for label, value in (("本地优先(省钱)", "local_first"),
                             ("云端优先(更强)", "cloud_first"),
                             ("混合(平衡)", "hybrid")):
            self.ai_strategy_combo.addItem(label, value)
        cur_strategy = self.settings.get("ai_strategy", "local_first") or "local_first"
        idx = self.ai_strategy_combo.findData(cur_strategy)
        self.ai_strategy_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.ai_strategy_combo.setToolTip(
            "决定 AI 对话默认怎么分流:\n"
            "· 本地优先(省钱):简单操作用本地小模型,复杂任务自动转云端;\n"
            "· 云端优先(更强):一切走云端大模型(需联网,未配云端会自动降级);\n"
            "· 混合(平衡):按规则分流 + 模型复核,本地/云端平衡。")
        ai_strategy_hint = QLabel("AI 策略:本地更省钱、云端更强;切换后立即生效,无需重启。")
        ai_strategy_hint.setWordWrap(True)
        ai_strategy_hint.setStyleSheet("color: #888888;")
        ai_strategy_row = QHBoxLayout()
        ai_strategy_row.addWidget(QLabel("AI 策略:"))
        ai_strategy_row.addWidget(self.ai_strategy_combo, 1)

        self.ai_form = AISettingsForm(self.settings)
        ai_hint = QLabel("AI 设置会自动保存,下次打开启动器仍然有效。\n"
                         "· 云/本地两块分开配:顶部选「当前使用」哪边,AI 对话就走哪边;\n"
                         "· 发图片(多模态):只有所选模型本身会\"看图\"才有效,内置本地模型自动关闭;\n"
                         "· 本地模型约 500MB,首次用到时后台自动下载(镜像优先)。")
        ai_hint.setWordWrap(True)
        ai_hint.setStyleSheet("color: #888888;")

        # Mod 描述本地 AI 翻译(英→中)开关:归属 AI 功能,默认开
        self.mod_translate_check = QCheckBox("Mod 描述本地 AI 翻译(英→中)")
        self.mod_translate_check.setChecked(bool(self.settings.get("ai_mod_translate", True)))
        self.mod_translate_check.setToolTip(
            "在「下载新资源 → 资源详情」面板把英文 Mod 描述翻译成中文。\n"
            "开:详情显示中文翻译 + \"机翻仅供参考\"标注;关:显示英文原文。")
        mod_ai_hint = QLabel("开:选 Mod 时详情面板把英文描述翻成中文(本地小模型,翻译在后台跑,不卡界面)。")
        mod_ai_hint.setWordWrap(True)
        mod_ai_hint.setStyleSheet("color: #888888;")
        mod_ai_row = QHBoxLayout()
        mod_ai_row.addWidget(self.mod_translate_check)
        mod_ai_row.addStretch()

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addLayout(ai_strategy_row)
        lay.addWidget(ai_strategy_hint)
        lay.addWidget(self.ai_form)
        lay.addLayout(mod_ai_row)
        lay.addWidget(mod_ai_hint)
        lay.addWidget(ai_hint)
        lay.addStretch()
        return w

    # ================= 镜像源 =================
    def _build_mirror_tab(self) -> QWidget:
        from PySide6.QtWidgets import QWidget

        # 下载策略:官方/镜像谁优先、用不用(官方源与镜像站的分工由策略决定)
        self.strategy_combo = QComboBox()
        for key, info in MIRROR_STRATEGIES.items():
            self.strategy_combo.addItem(info["name"], key)
        cur = self.settings.get("mirror_strategy", "smart_official")
        idx = self.strategy_combo.findData(cur)
        self.strategy_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.strategy_combo.currentIndexChanged.connect(self._on_strategy_changed)
        self.strategy_hint = QLabel("")
        self.strategy_hint.setWordWrap(True)
        self.strategy_hint.setStyleSheet("color: #888888;")
        self._update_strategy_hint()

        # 镜像站:实际用到的镜像(策略里"只用官方"时自动禁用)
        self.mirror_hint = QLabel("")
        self.mirror_hint.setWordWrap(True)
        self.mirror_hint.setStyleSheet("color: #888888;")
        self.mirror_combo = QComboBox()
        self._refresh_mirror_combo()
        self.mirror_combo.currentIndexChanged.connect(self._update_mirror_hint)
        self.mirror_combo.setEnabled(cur != "official_only")

        form = QFormLayout()
        form.addRow("下载策略:", self.strategy_combo)
        form.addRow("", self.strategy_hint)
        form.addRow("镜像站:", self.mirror_combo)
        form.addRow("", self.mirror_hint)

        # 自定义镜像:名称 + 地址,添加进列表;选中可删除
        self.custom_name_edit = QLineEdit()
        self.custom_name_edit.setPlaceholderText("名称,如 我的镜像")
        self.custom_url_edit = QLineEdit()
        self.custom_url_edit.setPlaceholderText("base 地址,如 https://mirror.example.com")
        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self._add_custom_mirror)
        add_row = QHBoxLayout()
        add_row.addWidget(self.custom_name_edit, 1)
        add_row.addWidget(self.custom_url_edit, 2)
        add_row.addWidget(add_btn)

        self.custom_list = QListWidget()
        self.custom_list.setMinimumHeight(90)
        self._refresh_custom_list()
        del_btn = QPushButton("删除选中")
        del_btn.clicked.connect(self._remove_custom_mirror)
        del_row = QHBoxLayout()
        del_row.addStretch()
        del_row.addWidget(del_btn)

        sep = QLabel("自定义镜像(与 BMCLAPI 同构:填 base 地址,自动映射 libraries/ assets/ version/ 等路径)")
        sep.setWordWrap(True)
        sep.setStyleSheet("font-weight: bold; margin-top: 10px;")

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addLayout(form)
        lay.addWidget(sep)
        lay.addLayout(add_row)
        lay.addWidget(self.custom_list)
        lay.addLayout(del_row)
        lay.addStretch()
        return w

    def _on_strategy_changed(self):
        self._update_strategy_hint()
        # "只用官方源"时镜像站用不上,禁用选择框
        self.mirror_combo.setEnabled(self.strategy_combo.currentData() != "official_only")

    def _update_strategy_hint(self):
        key = self.strategy_combo.currentData()
        info = MIRROR_STRATEGIES.get(key)
        self.strategy_hint.setText(info["desc"] if info else "")

    def _refresh_mirror_combo(self):
        """重建镜像源下拉框(内置预设 + 自定义),尽量保持原选中项"""
        cur = self.mirror_combo.currentData() if self.mirror_combo.count() \
            else self.settings.get("mirror_source", "bmclapi")
        self.mirror_combo.blockSignals(True)
        self.mirror_combo.clear()
        for key, info in MIRROR_SOURCES.items():
            self.mirror_combo.addItem(info["name"], key)
        for cm in self._custom_mirrors:
            self.mirror_combo.addItem(f"自定义: {cm.get('name', '?')}", "custom:" + cm.get("id", ""))
        idx = self.mirror_combo.findData(cur)
        if idx < 0:   # 原选中项已被删除(如自定义镜像被移除)→ 退回 BMCLAPI
            idx = self.mirror_combo.findData("bmclapi")
        self.mirror_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.mirror_combo.blockSignals(False)
        self._update_mirror_hint()

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
            self.mirror_hint.setText("自定义镜像")
        else:
            self.mirror_hint.setText("")

    def _add_custom_mirror(self):
        name = self.custom_name_edit.text().strip()
        url = self.custom_url_edit.text().strip()
        if not name or not url:
            QMessageBox.warning(self, "镜像源", "请填写名称和地址")
            return
        if not url.startswith(("http://", "https://")):
            QMessageBox.warning(self, "镜像源", "地址必须以 http:// 或 https:// 开头")
            return
        self._custom_mirrors.append(
            {"id": uuid.uuid4().hex[:8], "name": name, "url": url.rstrip("/")})
        self.custom_name_edit.clear()
        self.custom_url_edit.clear()
        self._refresh_custom_list()
        self._refresh_mirror_combo()
        # 选中刚添加的自定义镜像
        idx = self.mirror_combo.findData("custom:" + self._custom_mirrors[-1]["id"])
        self.mirror_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _refresh_custom_list(self):
        self.custom_list.clear()
        for cm in self._custom_mirrors:
            self.custom_list.addItem(f"{cm.get('name', '?')}  —  {cm.get('url', '')}")

    def _remove_custom_mirror(self):
        row = self.custom_list.currentRow()
        if row < 0:
            QMessageBox.information(self, "镜像源", "先在列表里选中要删除的自定义镜像")
            return
        self._custom_mirrors.pop(row)
        self._refresh_custom_list()
        self._refresh_mirror_combo()   # 若正在用被删的镜像,自动退回 BMCLAPI

    # ================= 确定 =================
    def accept(self):
        """点确定:把各标签页内容收集进 self.settings 并保存"""
        self.settings["username"] = self.username_edit.text().strip() or "Player"
        self.settings["memory_gb"] = self.memory_spin.value()
        self.settings["version_isolation"] = self.isolation_check.isChecked()
        self.settings["game_dir"] = self.game_dir_edit.text().strip()
        self.settings["language"] = self.language_combo.currentData()
        self.settings["ui_mode"] = self.ui_mode_combo.currentData()
        self.settings.update(self.ai_form.values())   # 含 ai_multimodal(多模态图片输入)
        self.settings["ai_strategy"] = self.ai_strategy_combo.currentData()
        self.settings["ai_mod_translate"] = self.mod_translate_check.isChecked()
        self.settings["mirror_strategy"] = self.strategy_combo.currentData()
        self.settings["mirror_source"] = self.mirror_combo.currentData()
        self.settings["custom_mirrors"] = self._custom_mirrors
        save_settings(self.settings)
        i18n.set_language(self.settings["language"])
        paths.set_game_dir(self.settings["game_dir"])  # 改路径立即全局生效
        super().accept()
