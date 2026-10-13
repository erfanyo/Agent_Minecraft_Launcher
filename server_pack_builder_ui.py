"""Qt workflow for building a reviewable server candidate from a client instance."""
from __future__ import annotations

from ui_notifications import task_notice, task_warning, inline_notice, inline_warning, action_question
from task_center import task_question
import os
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QVBoxLayout, QPlainTextEdit)

from background_tasks import BackgroundTask
from export_paths import compose_zip_destination
from server_pack_builder import build_candidate_server_pack, supported_conversion
from ui_style import card_btn_style, hint_style, set_style, progress_bar_style


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
        # A top-level window with no native owner can go behind the launcher.
        super().__init__(None)
        self._owner_context = parent
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self._test_active = False
        self._workflow_active = False
        self._test_center = None
        self._test_server_id = None
        self.instance_id = instance_id
        self.instance_dir = instance_dir
        self.game_dir = game_dir
        self.minecraft = minecraft
        self.loader = loader or ''
        self.loader_version = loader_version or ''
        self._task = None
        self.setWindowTitle('导出为服务端')
        self.resize(660, 470)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        title = QLabel('<b>客户端实例 → 服务端</b>')
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
        form.addRow('服务端名称：', self.name_edit)
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
        self.browse_btn = browse
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_dir_edit, 1)
        output_row.addWidget(browse)
        form.addRow('保存目录：', output_row)
        self.output_name_edit = QLineEdit(self.instance_id + '-server.zip')
        self.output_name_edit.setPlaceholderText('服务端文件名')
        form.addRow('文件名：', self.output_name_edit)
        layout.addLayout(form)

        layout.addWidget(QLabel('服务端准备完成后可选择启动测试，最后再生成 ZIP。'))
        warning = QLabel(
            '注意：无法判断适用端的 Mod 会保留；疑似含 Token、Webhook、RCON 密码的配置只会在报告中标记文件名，'
            '不会读取或显示密钥值。第一次启动仍应查看日志并人工复核。')
        warning.setWordWrap(True)
        warning.setStyleSheet(hint_style())
        layout.addWidget(warning)
        layout.addStretch()

        self.progress_label = QLabel('')
        self.progress_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        set_style(self.progress_bar, progress_bar_style)
        self.progress_bar.setRange(0, 1000)
        self.progress_label.hide()
        self.progress_bar.hide()
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress_bar)
        self.test_summary_label = QLabel('')
        self.test_summary_label.setWordWrap(True)
        self.test_summary_label.hide()
        self.test_mods_log = QPlainTextEdit()
        self.test_mods_log.setReadOnly(True)
        self.test_mods_log.setMaximumHeight(130)
        self.test_mods_log.setPlaceholderText('测试中停用的 Mod 会显示在这里。')
        self.test_mods_log.hide()
        layout.addWidget(self.test_summary_label)
        layout.addWidget(self.test_mods_log)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton('取消')
        self.cancel_btn = cancel
        self.start_btn = QPushButton('开始转换')
        for button in (cancel, self.start_btn):
            set_style(button, card_btn_style)
        cancel.clicked.connect(self._cancel_or_close)
        self.start_btn.clicked.connect(self._start)
        buttons.addWidget(cancel)
        buttons.addWidget(self.start_btn)
        layout.addLayout(buttons)

        ok, reason = supported_conversion(self.loader, self.minecraft)
        if not ok:
            self.start_btn.setEnabled(False)
            self.start_btn.setToolTip(reason)
            inline_notice(self, '当前实例暂不支持自动转换', reason)

    def _browse(self):
        start = self.output_dir_edit.text().strip()
        if not Path(start).is_dir():
            start = str(Path(start).parent) if start else self.game_dir
        path = QFileDialog.getExistingDirectory(self, '选择服务端保存目录', start)
        if path:
            self.output_dir_edit.setText(path)

    def _cancel_or_close(self):
        from task_center import task_center_for
        hub = task_center_for(self)
        task_id = getattr(self, '_status_task_id', None)
        if hub and task_id and hub.cancel_confirmation(task_id):
            hub.finish_task(task_id, 'cancelled', '已取消，准备目录保留。')
            return
        if self._test_active and self._test_center is not None:
            self.cancel_btn.setEnabled(False)
            self._test_center.interrupt_repair_test()
        elif self._task is not None and self._task.is_running:
            self._task.cancel()
            self.cancel_btn.setEnabled(False)
            self.progress_label.setText('正在取消，请稍候…')
        else:
            if hub and task_id:
                hub.details.hide()
            else:
                self.reject()

    def _bind_progress(self, task, message):
        self._task = task
        from task_center import task_center_for
        hub = task_center_for(self)
        if hub and getattr(self, '_status_task_id', None):
            hub.attach_background(task, self._status_task_id, finish=False)
            hub.update_task(self._status_task_id, message=message, state='running')
        self.progress_label.setText(message)
        self.progress_label.show()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self.start_btn.setEnabled(False)
        self.cancel_btn.setText('取消任务')
        self.cancel_btn.setEnabled(True)
        for control in (self.name_edit, self.world_combo, self.output_dir_edit,
                        self.output_name_edit, self.browse_btn):
            control.setEnabled(False)
        task.status.connect(self.progress_label.setText)
        task.progress.connect(self._update_progress)
        task.finished.connect(lambda: self._progress_finished(task))

    def _update_progress(self, done, total):
        if total <= 0:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(min(1000, max(0, int(done * 1000 / total))))

    def _progress_finished(self, task):
        if self._task is not task or self._test_active:
            return
        self.cancel_btn.setText('关闭')
        self.cancel_btn.setEnabled(True)
        self.start_btn.setEnabled(not self._workflow_active and supported_conversion(self.loader, self.minecraft)[0])
        for control in (self.name_edit, self.world_combo, self.output_dir_edit,
                        self.output_name_edit, self.browse_btn):
            control.setEnabled(not self._workflow_active)
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(0)

    def reject(self):
        from task_center import task_center_for
        hub = task_center_for(self)
        if hub and getattr(self, '_status_task_id', None):
            hub.details.hide()
            return
        if self._test_active:
            self._cancel_or_close()
            return
        if self._task is not None and self._task.is_running:
            return
        super().reject()

    def closeEvent(self, event):
        from task_center import task_center_for
        hub = task_center_for(self)
        if hub and getattr(self, '_status_task_id', None):
            hub.details.hide()
            event.ignore()
            return
        if self._test_active:
            self._cancel_or_close()
            event.ignore()
            return
        if self._task is not None and self._task.is_running:
            event.ignore()
            return
        super().closeEvent(event)

    def _start(self):
        if self._workflow_active:
            return
        if self._task is not None and self._task.is_running:
            return
        name = self.name_edit.text().strip()
        if not name:
            inline_notice(self, '信息不完整', '请填写服务端名称。')
            return
        try:
            output = compose_zip_destination(
                self.output_dir_edit.text(), self.output_name_edit.text())
        except ValueError as exc:
            inline_notice(self, '导出位置不完整', str(exc))
            return
        if Path(output).exists():
            inline_notice(self, '文件已存在', '请选择一个尚不存在的新文件名。')
            return
        selected_world = self.world_combo.currentData()
        def work(task):
            java = _select_java(self.game_dir, self.minecraft, task)
            result = build_candidate_server_pack(
                self.instance_dir, output, name=name, minecraft=self.minecraft,
                loader=self.loader, loader_version=self.loader_version, java=java,
                selected_world=selected_world,
                status_callback=task.report_status,
                progress_callback=task.report_progress,
                prepare_only=True, game_dir=self.game_dir)
            return result

        task = BackgroundTask(work, self)
        self._bind_progress(task, '正在准备转换…')
        task.failed.connect(lambda message: (self.progress_label.setText('转换失败：' + message),
            inline_warning(self, '转换失败', message)))
        task.cancelled_signal.connect(lambda: self.progress_label.setText('转换已取消；未完成的临时目录会自动清理。'))
        task.succeeded.connect(self._finished)
        task.start()

    def _finished(self, result):
        self._workflow_active = True
        self._prepared = result
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(1000)
        self.progress_label.setText('服务端准备完成，尚未打包。')
        report = result['report']
        excluded = sum(1 for row in report['mods'] if row['action'] == 'excluded')
        message = (f'已按明确声明排除 {excluded} 个客户端 Mod，服务端文件已准备好。\n\n'
            '现在进行隔离启动测试吗？测试会根据明确的客户端类报错，自动停用未标注的客户端 Mod，'
            '并循环启动验证。你仍需明确同意 Minecraft EULA。\n'
            '测试结束后再生成 ZIP；跳过测试则直接打包，并标注尚未测试。')
        from task_center import task_center_for
        hub = task_center_for(self)
        if hub and getattr(self, '_status_task_id', None):
            def continue_export(choice):
                if choice is None:
                    self._workflow_active = False
                    self.progress_label.setText('已取消等待确认，准备目录保留。')
                elif choice:
                    self._import_for_test(result)
                else:
                    self._package_prepared(result, {'outcome': 'untested', 'disabled': []})
            hub.request_confirmation(self._status_task_id, '服务端准备完成', message,
                [('开始测试', True), ('直接打包', False)], continue_export)
            return
        choice = action_question(self, '准备完成 · 要测试吗？', message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if choice == QMessageBox.StandardButton.Yes:
            self._import_for_test(result)
        else:
            self._package_prepared(result, {'outcome': 'untested', 'disabled': []})

    def _find_server_home(self):
        widget = self._owner_context
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
            task_warning(self, '无法进入测试', '找不到服务端页面，将按未测试状态打包。')
            self._package_prepared(result, {'outcome': 'untested', 'disabled': []})
            return
        center = home.server_center
        if getattr(center, '_busy', False) or center._repair is not None:
            task_warning(self, '暂时无法进入测试',
                '另一个服务端任务仍在进行，本次将按未测试状态打包。')
            self._package_prepared(result, {'outcome': 'untested', 'disabled': []})
            return
        try:
            server = center.select_package(result['folder'])
        except ValueError as exc:
            task_warning(self, '无法进入测试', str(exc))
            self._package_prepared(result, {'outcome': 'untested', 'disabled': []})
            return
        self._test_active = True
        self._test_center = center
        self._test_server_id = server['id']
        if getattr(self, '_status_task_id', None):
            self._previous_center_task_id = getattr(center, '_status_task_id', None)
            center._status_task_id = self._status_task_id
            center._status_managed_workflow = True
        self.test_summary_label.show()
        self.test_mods_log.show()
        self.progress_bar.setRange(0, 0)
        self.cancel_btn.setText('中断测试')
        self.cancel_btn.setEnabled(True)
        self.start_btn.setEnabled(False)
        self.progress_label.setText('正在准备第 1 轮测试…')
        self.test_summary_label.setText('已启动 0 轮 · 测试中已停用 0 个 Mod')
        center.repair_progress.connect(self._show_test_progress)
        def on_finished(summary):
            if summary['serverId'] != server['id']:
                return
            center.repair_finished.disconnect(on_finished)
            center.repair_progress.disconnect(self._show_test_progress)
            self._test_active = False
            self._show_test_progress(dict(summary, stage=(
                '测试通过，正在准备打包…' if summary['outcome'] == 'ready' else
                '测试已中断，正在保存候选服务端…' if summary['outcome'] == 'cancelled' else
                '测试未通过，正在准备候选服务端…')))
            self._package_prepared(result, summary, center=center, server=server)
        center.repair_finished.connect(on_finished)
        QTimer.singleShot(0, lambda: center.start_repair_test(auto_exclude=True))

    def _show_test_progress(self, state):
        if state.get('serverId') != self._test_server_id:
            return
        disabled = state.get('disabled', [])
        self.progress_label.setText(state.get('stage', '正在测试…'))
        from task_center import task_center_for
        hub = task_center_for(self)
        if hub and getattr(self, '_status_task_id', None):
            hub.update_task(self._status_task_id, message=state.get('stage', '正在测试…'), state='running', total=0)
        self.test_summary_label.setText(
            f"已启动 {state.get('rounds', 0)} 轮 · 测试中已停用 {len(disabled)} 个 Mod")
        self.test_mods_log.setPlainText('\n'.join('已停用：' + name for name in disabled))
        self.test_mods_log.verticalScrollBar().setValue(self.test_mods_log.verticalScrollBar().maximum())

    def _package_prepared(self, prepared, summary, *, center=None, server=None):
        from server_pack_builder import archive_prepared_server
        def work(task):
            # Stop the test before packaging so configs and selected saves are stable.
            from server_center import ServerCenter
            ServerCenter._stop_test_processes(Path(prepared['folder'], 'server'))
            return archive_prepared_server(prepared, summary['disabled'],
                outcome=summary['outcome'], status_callback=task.report_status,
                progress_callback=task.report_progress)
        def done(output):
            label = '候选服务端' if summary['outcome'] not in ('ready', 'untested') else '服务端'
            note = ('启动测试通过，仍需进服验证玩法。' if summary['outcome'] == 'ready' else
                    '未执行启动测试。' if summary['outcome'] == 'untested' else '测试未通过，需要继续修复。')
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(1000)
            self.progress_label.setText(f'{label}已生成：{output}')
            from task_center import task_center_for
            hub = task_center_for(self)
            if hub and getattr(self, '_status_task_id', None):
                hub.finish_task(self._status_task_id, message=f'{label}已打包：{output}\n{note}')
            else:
                task_notice(self, '导出完成',
                    f'{label}已打包：\n{output}\n\n测试中排除 {len(summary["disabled"])} 个 Mod。\n{note}')
            if center is not None:
                center._status_managed_workflow = False
                center.offer_test_instance_cleanup(server)
                center._status_task_id = getattr(self, '_previous_center_task_id', None)
            else:
                from server_center import ServerCenter
                try:
                    ServerCenter._delete_test_instance(
                        {'id': Path(prepared['folder']).name, 'path': str(Path(prepared['folder'], 'server'))},
                        Path(prepared['folder']))
                except (OSError, ValueError, RuntimeError) as exc:
                    task_warning(self, '临时目录未清理',
                        f'ZIP 已生成，准备目录仍保留：{prepared["folder"]}\n{exc}')
            self.cancel_btn.setText('关闭')
        task = BackgroundTask(work, self)
        self._bind_progress(task, '正在停止测试服务端并生成 ZIP…')
        task.succeeded.connect(done)
        task.failed.connect(lambda message: task_warning(self, '打包失败',
            message + '\n准备的服务端目录已保留：' + prepared['folder']))
        task.cancelled_signal.connect(lambda: self.progress_label.setText(
            '打包已取消，准备目录已保留：' + prepared['folder']))
        task.start()


def open_server_pack_builder(parent, *, instance_id, instance_dir, game_dir,
                             minecraft, loader, loader_version):
    from task_center import task_center_for
    import hashlib
    hub = task_center_for(parent)
    task_id = 'server-export-' + hashlib.sha256(
        os.path.normcase(os.path.abspath(instance_dir)).encode('utf-8')).hexdigest()[:20]
    if hub and task_id in hub.tasks:
        record = hub.tasks[task_id]
        if record.state in ('running', 'idle') or hub.tabs.indexOf(record.page) >= 0:
            hub.show_task(task_id)
            return record.page
    dialog = ServerPackBuilderDialog(
        instance_id=instance_id, instance_dir=instance_dir, game_dir=game_dir,
        minecraft=minecraft, loader=loader, loader_version=loader_version,
        parent=parent)
    dialogs = getattr(parent, '_server_builder_dialogs', [])
    dialogs.append(dialog)
    parent._server_builder_dialogs = dialogs
    dialog.finished.connect(lambda _code: dialogs.remove(dialog) if dialog in dialogs else None)
    if hub:
        dialog._status_managed_workflow = True
        task_id = hub.begin_task('导出服务端 · ' + instance_id, task_id=task_id,
                                 page=dialog, cancel=dialog._cancel_or_close)
        hub.update_task(task_id, state='idle')
        hub.show_task(task_id)
    else:
        dialog.show()
    return dialog
