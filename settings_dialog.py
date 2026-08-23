# -*- coding: utf-8 -*-
"""
设置对话框(启动器整体设置):
- 游戏:游戏名、内存、版本隔离、游戏目录(.minecraft 位置,可指向任意已有目录)
- AI:服务商 / 接口 / 密钥 / 模型 / 文件权限(与首次引导共用同一表单)
点"确定"时把表单内容写进 config.json。
"""
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
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

import i18n
import paths
from assistant import AISettingsForm
from settings import save_settings


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("启动器设置")
        self.setMinimumWidth(430)
        self.settings = dict(settings)  # 复制一份,点确定才真正生效

        # ---------- 游戏区 ----------
        self.username_edit = QLineEdit(settings.get("username", "Player"))
        self.username_edit.setPlaceholderText("离线模式显示的游戏名")

        self.memory_spin = QSpinBox()
        self.memory_spin.setRange(1, 16)
        self.memory_spin.setSuffix(" GB")
        self.memory_spin.setValue(settings.get("memory_gb", 2))

        self.isolation_check = QCheckBox("每个版本用独立游戏目录(存档/配置/Mod 互不干扰)")
        self.isolation_check.setChecked(settings.get("version_isolation", True))

        self.game_dir_edit = QLineEdit(settings.get("game_dir") or paths.DEFAULT_GAME_DIR)
        browse_btn = QPushButton("浏览…")
        browse_btn.clicked.connect(self._browse_game_dir)
        default_btn = QPushButton("默认")
        default_btn.setToolTip("回到启动器目录下的 .minecraft")
        default_btn.clicked.connect(lambda: self.game_dir_edit.setText(paths.DEFAULT_GAME_DIR))
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.game_dir_edit, 1)
        dir_row.addWidget(browse_btn)
        dir_row.addWidget(default_btn)

        game_form = QFormLayout()
        game_form.addRow("游戏名:", self.username_edit)
        game_form.addRow("内存:", self.memory_spin)
        game_form.addRow("版本隔离:", self.isolation_check)
        game_form.addRow("游戏目录:", dir_row)
        dir_hint = QLabel("可以是任意位置,包括 PCL2 / 官方启动器创建的 .minecraft(自动读取里面的实例)")
        dir_hint.setWordWrap(True)
        dir_hint.setStyleSheet("color: #888888;")

        # ---------- 界面语言(自动跟随系统,可覆盖) ----------
        self.language_combo = QComboBox()
        for label, value in (("自动(跟随系统)", "auto"), ("中文", "zh"), ("English", "en")):
            self.language_combo.addItem(label, value)
        cur = settings.get("language", "auto")
        idx = self.language_combo.findData(cur)
        self.language_combo.setCurrentIndex(idx if idx >= 0 else 0)
        lang_hint = QLabel("切换语言后需重启启动器生效(检测系统语言:中文系统自动用中文)")
        lang_hint.setStyleSheet("color: #888888;")

        # ---------- 界面模式(新手多提示 / 专家少提示) ----------
        self.ui_mode_combo = QComboBox()
        for label, value in (("新手(显示更多提示与科普)", "beginner"),
                             ("专家(精简提示)", "expert")):
            self.ui_mode_combo.addItem(label, value)
        mode = settings.get("ui_mode", "beginner")
        idx = self.ui_mode_combo.findData(mode)
        self.ui_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        mode_hint = QLabel("新手模式:首页显示资源结构科普、更详细的状态提示;专家模式:全部隐藏/精简。")
        mode_hint.setStyleSheet("color: #888888;")
        mode_hint.setWordWrap(True)

        lang_form = QFormLayout()
        lang_form.addRow("界面语言:", self.language_combo)
        lang_form.addRow("界面模式:", self.ui_mode_combo)

        # ---------- AI 区 ----------
        ai_title = QLabel("AI 助手")
        ai_title.setStyleSheet("font-weight: bold; margin-top: 8px;")
        self.ai_form = AISettingsForm(self.settings)
        ai_hint = QLabel("AI 设置与菜单「AI → AI 设置」完全一致,改哪边都行。")
        ai_hint.setStyleSheet("color: #888888;")

        layout = QVBoxLayout(self)
        layout.addLayout(game_form)
        layout.addWidget(dir_hint)
        layout.addLayout(lang_form)
        layout.addWidget(lang_hint)
        layout.addWidget(mode_hint)
        layout.addWidget(ai_title)
        layout.addWidget(self.ai_form)
        layout.addWidget(ai_hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_game_dir(self):
        start = self.game_dir_edit.text().strip() or paths.DEFAULT_GAME_DIR
        d = QFileDialog.getExistingDirectory(self, "选择 Minecraft 游戏目录", start)
        if d:
            self.game_dir_edit.setText(d)

    def accept(self):
        """点确定:把表单内容收集进 self.settings 并保存"""
        self.settings["username"] = self.username_edit.text().strip() or "Player"
        self.settings["memory_gb"] = self.memory_spin.value()
        self.settings["version_isolation"] = self.isolation_check.isChecked()
        self.settings["game_dir"] = self.game_dir_edit.text().strip()
        self.settings["language"] = self.language_combo.currentData()
        self.settings["ui_mode"] = self.ui_mode_combo.currentData()
        self.settings.update(self.ai_form.values())
        save_settings(self.settings)
        i18n.set_language(self.settings["language"])
        paths.set_game_dir(self.settings["game_dir"])  # 改路径立即全局生效
        super().accept()
