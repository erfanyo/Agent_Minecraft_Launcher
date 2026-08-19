# -*- coding: utf-8 -*-
"""
设置对话框:游戏名、内存、版本隔离。
点"确定"时把表单内容写进 config.json。
"""
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from settings import save_settings


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("启动器设置")
        self.settings = dict(settings)  # 复制一份,点确定才真正生效

        self.username_edit = QLineEdit(settings.get("username", "Player"))
        self.username_edit.setPlaceholderText("离线模式显示的游戏名")

        self.memory_spin = QSpinBox()
        self.memory_spin.setRange(1, 16)
        self.memory_spin.setSuffix(" GB")
        self.memory_spin.setValue(settings.get("memory_gb", 2))

        self.isolation_check = QCheckBox("每个版本用独立游戏目录(存档/配置/Mod 互不干扰)")
        self.isolation_check.setChecked(settings.get("version_isolation", True))

        form = QFormLayout()
        form.addRow("游戏名:", self.username_edit)
        form.addRow("内存:", self.memory_spin)
        form.addRow("版本隔离:", self.isolation_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def accept(self):
        """点确定:把表单内容收集进 self.settings 并保存"""
        self.settings["username"] = self.username_edit.text().strip() or "Player"
        self.settings["memory_gb"] = self.memory_spin.value()
        self.settings["version_isolation"] = self.isolation_check.isChecked()
        save_settings(self.settings)
        super().accept()
