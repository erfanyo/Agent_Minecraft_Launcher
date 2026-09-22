"""Reusable directory + filename picker for ZIP exports."""
from pathlib import Path

from PySide6.QtWidgets import (QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                               QLineEdit, QMessageBox, QPushButton, QVBoxLayout)

from export_paths import compose_zip_destination
from ui_style import card_btn_style, set_style


class ZipDestinationDialog(QDialog):
    def __init__(self, title, default_directory, default_filename, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(610, 170)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.directory = QLineEdit(str(default_directory))
        browse = QPushButton('选择文件夹…')
        set_style(browse, card_btn_style)
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.directory, 1)
        row.addWidget(browse)
        form.addRow('保存目录：', row)
        self.filename = QLineEdit(str(default_filename))
        self.filename.setPlaceholderText('例如 amcl-server-runtime.zip')
        form.addRow('文件名：', self.filename)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton('取消')
        confirm = QPushButton('确定')
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
        chosen = QFileDialog.getExistingDirectory(self, '选择保存目录', start)
        if chosen:
            self.directory.setText(chosen)

    def _accept_checked(self):
        try:
            self.destination = compose_zip_destination(
                self.directory.text(), self.filename.text())
        except ValueError as exc:
            QMessageBox.information(self, '导出位置不完整', str(exc))
            return
        if Path(self.destination).exists():
            QMessageBox.information(self, '文件已存在', '请换一个文件名；AMCL 不会覆盖已有导出。')
            return
        self.accept()


def choose_zip_destination(parent, title, default_directory, default_filename):
    dialog = ZipDestinationDialog(title, default_directory, default_filename, parent)
    return dialog.destination if dialog.exec() == QDialog.DialogCode.Accepted else None

