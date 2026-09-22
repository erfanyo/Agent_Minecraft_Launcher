"""Qt workflow for building a reviewable server candidate from a client instance."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressDialog,
    QPushButton, QVBoxLayout)

from background_tasks import BackgroundTask
from export_paths import compose_zip_destination
from server_pack_builder import build_candidate_server_pack, supported_conversion
from ui_style import card_btn_style, hint_style, set_style


def _select_java(game_dir, minecraft, task):
    from java_manager import ensure_java, java_version_probe, minecraft_java_range
    from settings import load_settings
    minimum, maximum = minecraft_java_range(minecraft)
    preferred = str((load_settings().get('java_paths') or {}).get(str(minimum)) or '').strip()
    if preferred and Path(preferred).is_file():
        major, error = java_version_probe(preferred)
        if not error and major >= minimum and (maximum is None or major <= maximum):
            task.report_status(f'使用 Java 管理中设置的 Java {major}。')
            return preferred
    return ensure_java(os.path.join(game_dir, 'runtime'), minimum,
                       max_major=maximum, prefer_managed=(maximum == 8),
                       status_callback=task.report_status,
                       progress_callback=task.report_progress)


class ServerPackBuilderDialog(QDialog):
    def __init__(self, *, instance_id, instance_dir, game_dir, minecraft,
                 loader, loader_version, parent=None):
        super().__init__(parent)
        self.instance_id = instance_id
        self.instance_dir = instance_dir
        self.game_dir = game_dir
        self.minecraft = minecraft
        self.loader = loader or ''
        self.loader_version = loader_version or ''
        self._task = None
        self.setWindowTitle('转换为候选服务端')
        self.resize(660, 470)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        title = QLabel('<b>客户端实例 → 候选服务端包</b>')
        title.setStyleSheet('font-size: 17px;')
        layout.addWidget(title)
        intro = QLabel(
            'AMCL 会在隔离目录安装对应服务端、复制共用内容，并只排除有明确证据的客户端 Mod。'
            '原实例不会被修改；不会启动正式服务器，也不会替你接受 EULA。')
        intro.setWordWrap(True)
        intro.setStyleSheet(hint_style())
        layout.addWidget(intro)

        form = QFormLayout()
        form.addRow('来源实例：', QLabel(self.instance_id))
        form.addRow('环境：', QLabel(
            f'Minecraft {self.minecraft} · {self.loader or "未知加载器"} {self.loader_version}'.rstrip()))
        self.name_edit = QLineEdit(self.instance_id + ' 服务端')
        form.addRow('候选名称：', self.name_edit)
        self.world_combo = QComboBox()
        self.world_combo.addItem('不带存档（推荐）', None)
        saves = Path(self.instance_dir, 'saves')
        if saves.is_dir():
            for folder in sorted(saves.iterdir()):
                if folder.is_dir() and not folder.is_symlink():
                    self.world_combo.addItem('带入存档：' + folder.name, folder.name)
        form.addRow('初始世界：', self.world_combo)
        self.output_dir_edit = QLineEdit(str(Path(self.game_dir, 'exports')))
        browse = QPushButton('选择文件夹…')
        set_style(browse, card_btn_style)
        browse.clicked.connect(self._browse)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_dir_edit, 1)
        output_row.addWidget(browse)
        form.addRow('保存目录：', output_row)
        self.output_name_edit = QLineEdit(self.instance_id + '-server-candidate.zip')
        self.output_name_edit.setPlaceholderText('候选服务端文件名')
        form.addRow('文件名：', self.output_name_edit)
        layout.addLayout(form)

        self.import_check = QCheckBox('完成后加入 AMCL 服务端列表')
        self.import_check.setChecked(True)
        self.import_check.setToolTip('加入后仍需由你阅读并确认 EULA，才能首次启动。')
        layout.addWidget(self.import_check)
        warning = QLabel(
            '注意：无法判断适用端的 Mod 会保留；疑似含 Token、Webhook、RCON 密码的配置只会在报告中标记文件名，'
            '不会读取或显示密钥值。第一次启动仍应查看日志并人工复核。')
        warning.setWordWrap(True)
        warning.setStyleSheet(hint_style())
        layout.addWidget(warning)
        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton('取消')
        self.start_btn = QPushButton('开始转换')
        for button in (cancel, self.start_btn):
            set_style(button, card_btn_style)
        cancel.clicked.connect(self.reject)
        self.start_btn.clicked.connect(self._start)
        buttons.addWidget(cancel)
        buttons.addWidget(self.start_btn)
        layout.addLayout(buttons)

        ok, reason = supported_conversion(self.loader, self.minecraft)
        if not ok:
            self.start_btn.setEnabled(False)
            self.start_btn.setToolTip(reason)
            QMessageBox.information(self, '当前实例暂不支持自动转换', reason)

    def _browse(self):
        start = self.output_dir_edit.text().strip()
        if not Path(start).is_dir():
            start = str(Path(start).parent) if start else self.game_dir
        path = QFileDialog.getExistingDirectory(self, '选择候选服务端保存目录', start)
        if path:
            self.output_dir_edit.setText(path)

    def reject(self):
        if self._task is not None and self._task.is_running:
            return
        super().reject()

    def closeEvent(self, event):
        if self._task is not None and self._task.is_running:
            event.ignore()
            return
        super().closeEvent(event)

    def _start(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.information(self, '信息不完整', '请填写候选名称。')
            return
        try:
            output = compose_zip_destination(
                self.output_dir_edit.text(), self.output_name_edit.text())
        except ValueError as exc:
            QMessageBox.information(self, '导出位置不完整', str(exc))
            return
        if Path(output).exists():
            QMessageBox.information(self, '文件已存在', '请选择一个尚不存在的新文件名。')
            return
        selected_world = self.world_combo.currentData()
        add_to_list = self.import_check.isChecked()

        def work(task):
            java = _select_java(self.game_dir, self.minecraft, task)
            result = build_candidate_server_pack(
                self.instance_dir, output, name=name, minecraft=self.minecraft,
                loader=self.loader, loader_version=self.loader_version, java=java,
                selected_world=selected_world,
                status_callback=task.report_status,
                progress_callback=task.report_progress)
            if add_to_list:
                from archive_inspection import inspect_archive
                from server_packs import import_server_pack
                task.report_status('正在复核候选包并加入服务端列表…')
                scan = inspect_archive(output, status_callback=task.report_status,
                                       progress_callback=task.report_progress)
                result['importedPath'] = import_server_pack(
                    output, self.game_dir, scan['sha256'],
                    status_callback=task.report_status,
                    progress_callback=task.report_progress,
                    display_name=result['report']['name'])
            return result

        progress = QProgressDialog('正在准备转换…', '取消', 0, 1000, self)
        progress.setWindowTitle('转换为候选服务端')
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        task = BackgroundTask(work, self)
        self._task = task
        task.status.connect(progress.setLabelText)
        task.progress.connect(lambda done, total: progress.setValue(
            min(1000, int(done * 1000 / max(total, 1)))))
        progress.canceled.connect(task.cancel)
        task.failed.connect(lambda message: (progress.close(),
            QMessageBox.warning(self, '转换失败', message)))
        task.cancelled_signal.connect(lambda: (progress.close(),
            QMessageBox.information(self, '已取消', '转换已取消；未完成的临时目录会自动清理。')))
        task.succeeded.connect(lambda result: self._finished(progress, result))
        task.start()

    def _finished(self, progress, result):
        progress.close()
        report = result['report']
        excluded = sum(1 for item in report['mods'] if item['action'] == 'excluded')
        unknown = sum(1 for item in report['mods']
                      if item['action'] == 'included' and item['environment'] == 'unknown')
        text = (f"候选服务端包已生成：\n{result['path']}\n\n"
                f"明确排除 {excluded} 个 Mod；保留 {unknown} 个适用端未知的 Mod。\n"
                '包内附有审核报告和逐文件哈希。')
        if result.get('importedPath'):
            text += '\n\n已加入服务端列表；首次启动前仍需由你确认 EULA。'
            try:
                self.window().home_panel.server_center.refresh()
            except (AttributeError, RuntimeError):
                pass
        QMessageBox.information(self, '转换完成', text)
        self.accept()


def open_server_pack_builder(parent, *, instance_id, instance_dir, game_dir,
                             minecraft, loader, loader_version):
    dialog = ServerPackBuilderDialog(
        instance_id=instance_id, instance_dir=instance_dir, game_dir=game_dir,
        minecraft=minecraft, loader=loader, loader_version=loader_version,
        parent=parent)
    return dialog.exec()
