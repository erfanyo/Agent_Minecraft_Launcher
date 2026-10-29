"""Reusable directory + filename picker for ZIP exports."""
from __future__ import annotations
from launcher_app.core.i18n import t
from pathlib import Path

from PySide6.QtWidgets import (QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                               QLineEdit, QMessageBox, QPushButton, QVBoxLayout)

from launcher_app.ui.ui_style import card_btn_style, set_style


class ZipDestinationDialog(QDialog):
    def __init__(self, title, default_directory, default_filename, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(610, 170)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.directory = QLineEdit(str(default_directory))
        browse = QPushButton(t('选择文件夹…'))
        set_style(browse, card_btn_style)
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.directory, 1)
        row.addWidget(browse)
        form.addRow(t('保存目录：'), row)
        self.filename = QLineEdit(str(default_filename))
        self.filename.setPlaceholderText(t('例如 amcl-server-runtime.zip'))
        form.addRow(t('文件名：'), self.filename)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton(t('取消'))
        confirm = QPushButton(t('确定'))
        for button in (cancel, confirm):
            set_style(button, card_btn_style)
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self._accept_checked)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)
        self.destination = None

    def _browse(self):
        start = self.directory.text().strip()
        if not Path(start).is_dir():
            start = str(Path(start).parent) if start else str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, t('选择保存目录'), start)
        if chosen:
            self.directory.setText(chosen)

    def _accept_checked(self):
        try:
            self.destination = compose_zip_destination(
                self.directory.text(), self.filename.text())
        except ValueError as exc:
            QMessageBox.information(self, t('导出位置不完整'), str(exc))
            return
        if Path(self.destination).exists():
            QMessageBox.information(self, t('文件已存在'), t('请换一个文件名；AMCL 不会覆盖已有导出。'))
            return
        self.accept()


def choose_zip_destination(parent, title, default_directory, default_filename):
    dialog = ZipDestinationDialog(title, default_directory, default_filename, parent)
    return dialog.destination if dialog.exec() == QDialog.DialogCode.Accepted else None


# ===================== Merged from export_paths.py =====================
"""Small path helpers shared by export UIs and headless code."""
from pathlib import Path
import re


def compose_zip_destination(directory, filename):
    directory = str(directory or '').strip()
    filename = str(filename or '').strip()
    if not directory:
        raise ValueError('请选择保存目录。')
    if not filename:
        raise ValueError('请填写文件名。')
    if Path(filename).name != filename or filename in ('.', '..'):
        raise ValueError('文件名不能包含路径或目录分隔符。')
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', filename) or filename.rstrip(' .') != filename:
        raise ValueError('文件名包含 Windows 不允许的字符，或以空格/句点结尾。')
    if not filename.lower().endswith('.zip'):
        filename += '.zip'
    return str(Path(directory).expanduser().absolute() / filename)
