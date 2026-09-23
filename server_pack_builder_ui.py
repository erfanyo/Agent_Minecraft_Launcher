"""Qt workflow for building a reviewable server candidate from a client instance."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog,
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

        layout.addWidget(QLabel('导出完成后可选择隔离启动测试；不测试也能直接取得候选 ZIP。'))
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
        def work(task):
            java = _select_java(self.game_dir, self.minecraft, task)
            result = build_candidate_server_pack(
                self.instance_dir, output, name=name, minecraft=self.minecraft,
                loader=self.loader, loader_version=self.loader_version, java=java,
                selected_world=selected_world,
                status_callback=task.report_status,
                progress_callback=task.report_progress)
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
        choice = QMessageBox.question(self, '导出完成 · 要测试吗？',
            text + '\n\n要导入一个隔离测试实例并尝试启动、逐项诊断吗？'
                   '每次停用 Mod 都会征求确认；测试后可删除测试实例。'
                   '选“否”即可直接保留当前包，不保证它能够启动。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if choice != QMessageBox.StandardButton.Yes:
            self.accept()
            return
        self._import_for_test(result)

    def _find_server_home(self):
        widget = self.parentWidget()
        while widget is not None:
            if hasattr(widget, 'server_center') and hasattr(widget, '_server_tab_index'):
                return widget
            if hasattr(widget, 'home_panel'):
                return widget.home_panel
            widget = widget.parentWidget()
        # InstanceManagerDialog is an unparented overlay in the main window.
        for window in QApplication.topLevelWidgets():
            home = getattr(window, 'home_panel', None)
            if home is not None:
                return home
        return None

    def _import_for_test(self, result):
        home = self._find_server_home()
        if home is None:
            QMessageBox.warning(self, '无法进入测试',
                                '已保留导出的 ZIP，但找不到服务端页面，无法自动启动测试。')
            self.accept()
            return
        from server_packs import list_servers
        existing = {str(Path(row['packagePath']).resolve())
                    for row in list_servers(self.game_dir)}
        output = result['path']

        def work(task):
            from archive_inspection import inspect_archive
            from server_packs import import_server_pack
            scan = inspect_archive(output, status_callback=task.report_status,
                                   progress_callback=task.report_progress)
            return import_server_pack(output, self.game_dir, scan['sha256'],
                status_callback=task.report_status,
                progress_callback=task.report_progress,
                display_name=result['report']['name'])

        progress = QProgressDialog('正在导入隔离测试实例…', '取消', 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        task = BackgroundTask(work, self)
        self._task = task
        task.status.connect(progress.setLabelText)
        progress.canceled.connect(task.cancel)
        task.failed.connect(lambda message: (progress.close(),
            QMessageBox.warning(self, '无法导入测试实例',
                message + '\n原始候选 ZIP 已保留。')))
        task.cancelled_signal.connect(progress.close)
        task.succeeded.connect(lambda folder: self._start_imported_test(
            progress, home, folder, output, existing))
        task.start()

    def _start_imported_test(self, progress, home, folder, output, existing):
        progress.close()
        center = home.server_center
        try:
            server = center.select_package(folder)
        except ValueError as exc:
            QMessageBox.warning(self, '无法进入测试', str(exc))
            self.accept()
            return
        disposable = str(Path(folder).resolve()) not in existing
        home.tabs.setCurrentIndex(home._server_tab_index)
        def on_finished(summary):
            if summary['serverId'] != server['id']:
                return
            center.repair_finished.disconnect(on_finished)
            self._finalize_test(center, server, output, summary, disposable)
        center.repair_finished.connect(on_finished)
        self.accept()
        QTimer.singleShot(0, center.start_repair_test)

    def _finalize_test(self, center, server, output, summary, disposable):
        from server_pack_builder import apply_test_result_to_pack
        def work(_task):
            try:
                return {'path': apply_test_result_to_pack(output,
                    summary['disabled'], started=summary['outcome'] == 'ready')}
            except (OSError, ValueError, RuntimeError) as exc:
                return {'error': str(exc)}
        def done(result):
            if result.get('error'):
                QMessageBox.warning(center, '未能同步测试结果',
                    '原始候选 ZIP 和测试实例均已保留；请勿把 ZIP 当作修复后的版本。\n'
                    + result['error'])
            else:
                QMessageBox.information(center, '测试结束 · 导出包已更新',
                f"结果：{summary['outcome']}\n"
                f"测试中排除 {len(summary['disabled'])} 个 Mod。\n"
                f"导出文件：{result['path']}\n\n未通过测试时，它仍是候选包，不能保证可用。")
            if disposable:
                center.offer_test_instance_cleanup(server)
            else:
                QMessageBox.information(center, '已复用已有实例',
                    '测试使用的是之前已导入的同一服务端；不会建议删除你已有的实例。')
        center._run(work, done,
            '正在把测试结果写入导出包…')


def open_server_pack_builder(parent, *, instance_id, instance_dir, game_dir,
                             minecraft, loader, loader_version):
    dialog = ServerPackBuilderDialog(
        instance_id=instance_id, instance_dir=instance_dir, game_dir=game_dir,
        minecraft=minecraft, loader=loader, loader_version=loader_version,
        parent=parent)
    return dialog.exec()
