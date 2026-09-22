"""Server pack management, separate from client profiles and account login."""
from pathlib import Path
from PySide6.QtCore import Qt, QUrl, QTimer, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QListWidgetItem, QLabel, QFileDialog, QMessageBox, QPlainTextEdit,
    QDialog, QDialogButtonBox, QInputDialog, QLineEdit, QProgressBar, QTextBrowser)
from background_tasks import BackgroundTask
from archive_inspection import inspect_archive
from server_packs import list_servers, import_server_pack
from server_launch import build_launch_plan, eula_accepted
from server_eula import accept_minecraft_eula, fetch_minecraft_eula
from server_host_client import (managed_status, send_server_command,
                                start_managed_server)
import paths


def select_server_java(plan, report, settings, runtime_dir,
                       status_callback=None, progress_callback=None):
    """Choose/download a compatible runtime using the same policy as clients."""
    from java_manager import (ensure_java, java_version_probe,
                              minecraft_java_range)
    status = status_callback or (lambda _: None)
    mc = plan.get('minecraftVersion') or (report or {}).get('minecraftVersion') or ''
    declared = plan.get('requiredJava') or (report or {}).get('requiredJava')
    if mc:
        minimum, maximum = minecraft_java_range(mc)
    else:
        minimum, maximum = int(declared or 17), None
        status('无法确认 Minecraft 版本，暂按 Java 17 选择运行时。')
    required = max(minimum, int(declared or minimum))
    if maximum is not None and required > maximum:
        raise RuntimeError(
            f'服务端声明的 Java {required} 与 Minecraft {mc} 的兼容范围冲突。')
    preferred = str((settings.get('java_paths') or {}).get(str(required)) or '').strip()
    if preferred and Path(preferred).is_file():
        major, error = java_version_probe(preferred)
        if not error and major >= required and (maximum is None or major <= maximum):
            status(f'使用 Java 管理中设置的 Java {major}。')
            return preferred, (major, '')
        status('设置中的 Java 不可用或与该服务端不兼容，改用自动选择。')
    java = ensure_java(
        runtime_dir, required,
        progress_callback=progress_callback,
        status_callback=status,
        max_major=maximum,
        prefer_managed=(maximum == 8),
    )
    result = java_version_probe(java)
    if result[1] or not result[0]:
        raise RuntimeError(result[1] or '自动选择的 Java 无法运行')
    return java, result


class MinecraftEulaDialog(QDialog):
    """Keep acceptance locked until the official text reaches its end."""
    def __init__(self, payload, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Minecraft 服务端最终用户许可协议')
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        intro = QLabel(
            '启动 Minecraft 服务端前，需要由你本人同意 Mojang / Microsoft 的 EULA。'
            '下面显示的是刚从官方网站加载的正文；AMCL 不是协议的一方，也不能代你同意。')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.text = QTextBrowser()
        self.text.setPlainText(payload['text'])
        layout.addWidget(self.text, 1)
        source = QLabel(f'<a href="{payload["url"]}">在浏览器中打开官方 EULA</a>')
        source.setOpenExternalLinks(True)
        layout.addWidget(source)
        self.hint = QLabel('请阅读并滑到正文底部，之后才能同意。')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.accept_button = buttons.addButton(
            '我已阅读并同意，继续启动', QDialogButtonBox.ButtonRole.AcceptRole)
        self.accept_button.setEnabled(False)
        buttons.rejected.connect(self.reject)
        self.accept_button.clicked.connect(self.accept)
        layout.addWidget(buttons)
        bar = self.text.verticalScrollBar()
        bar.valueChanged.connect(self._update_accept)
        bar.rangeChanged.connect(lambda _minimum, _maximum: self._update_accept())
        QTimer.singleShot(0, self._update_accept)

    def _update_accept(self, *_args):
        bar = self.text.verticalScrollBar()
        reached = bar.maximum() == 0 or bar.value() >= bar.maximum()
        self.accept_button.setEnabled(reached)
        if reached:
            self.hint.setText(
                '已阅读到末尾。只有点击右下角按钮后，才会为这个服务端写入同意记录。')


class ServerCenter(QWidget):
    count_changed = Signal(int)
    selection_changed = Signal(object)
    running_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._attached_session = None
        self._log_path = None
        self._log_offset = 0
        self._last_running = False
        layout = QVBoxLayout(self)
        hint = QLabel('选择服务端后，启动、目录、Mod 和管理操作会出现在左侧；这里保留列表、任务进度和控制台。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        # Kept as a public busy-state anchor for background tasks. The visible
        # action lives in VersionHome's left command panel.
        self.import_btn = QPushButton('导入服务端压缩包')
        self.import_btn.clicked.connect(self.choose_import)
        self.import_btn.hide()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._selection_changed)
        self.list.itemDoubleClicked.connect(lambda _: self.launch())
        layout.addWidget(self.list)
        self.task_status = QLabel('就绪')
        self.task_status.setWordWrap(True)
        layout.addWidget(self.task_status)
        self.task_progress = QProgressBar()
        self.task_progress.setRange(0, 1000)
        self.task_progress.setValue(0)
        self.task_progress.hide()
        layout.addWidget(self.task_progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(20000)
        layout.addWidget(self.log)
        command_row = QHBoxLayout()
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText('输入服务端指令，例如：say 服务器将在 5 分钟后重启')
        self.command_input.setClearButtonEnabled(True)
        self.command_input.returnPressed.connect(self.send_command)
        self.command_button = QPushButton('发送')
        self.command_button.clicked.connect(self.send_command)
        command_row.addWidget(self.command_input, 1)
        command_row.addWidget(self.command_button)
        layout.addLayout(command_row)
        self.command_input.setEnabled(False)
        self.command_button.setEnabled(False)
        self._session_timer = QTimer(self)
        self._session_timer.setInterval(600)
        self._session_timer.timeout.connect(self._poll_session)
        self._session_timer.start()

    def refresh(self):
        current = self.selected()
        current_id = current.get('id') if current else None
        self.list.blockSignals(True)
        self.list.clear()
        servers = list_servers(paths.GAME_DIR)
        restore = None
        for server in servers:
            report = server['report']
            prefix = '候选 · ' if server.get('candidate') else ''
            item = QListWidgetItem(f"{prefix}{server['name']} · {report.get('minecraftVersion') or '版本待确认'} · {report.get('loader', 'unknown')}")
            item.setData(Qt.ItemDataRole.UserRole, server)
            self.list.addItem(item)
            if server.get('id') == current_id:
                restore = item
        self.list.setCurrentItem(restore or (self.list.item(0) if servers else None))
        self.list.blockSignals(False)
        self.count_changed.emit(len(servers))
        self._attach_selected()
        self.selection_changed.emit(self.selected())

    def _selection_changed(self, current, _previous):
        self._attach_selected()
        self.selection_changed.emit(
            current.data(Qt.ItemDataRole.UserRole) if current is not None else None)

    def selected(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def is_running(self, server=None):
        server = server or self.selected()
        if not server:
            return False
        state = managed_status(server['path'])
        return bool(state and state.get('running'))

    def _attach_selected(self):
        server = self.selected()
        state = managed_status(server['path']) if server else None
        session = state.get('sessionId') if state else None
        if session != self._attached_session:
            self._attached_session = session
            self._log_path = state.get('logFile') if state else None
            self._log_offset = 0
            self.log.clear()
            if session:
                self.log.appendPlainText(
                    f"已连接服务端会话 {session[:8]} · 启动于 {state.get('startedAt', '未知时间')}")
        running = bool(state and state.get('running'))
        self._set_running_state(running)
        self._read_session_log()

    def _set_running_state(self, running):
        running = bool(running)
        self.command_input.setEnabled(running)
        self.command_button.setEnabled(running)
        self._session_timer.setInterval(600 if running else 4000)
        if running != self._last_running:
            self._last_running = running
            self.running_changed.emit(running)
        if running:
            self.task_status.setText('服务端正在后台运行；关闭启动器不会停服。')
        elif self._attached_session:
            self.task_status.setText('服务端已退出；这里保留本次会话日志。')

    def _poll_session(self):
        server = self.selected()
        if not server:
            self._set_running_state(False)
            return
        state = managed_status(server['path'])
        if state and state.get('sessionId') != self._attached_session:
            self._attach_selected()
            return
        self._set_running_state(bool(state and state.get('running')))
        self._read_session_log()

    def _read_session_log(self):
        if not self._log_path:
            return
        try:
            path = Path(self._log_path)
            if not path.is_file() or path.is_symlink():
                return
            size = path.stat().st_size
            if size < self._log_offset:
                self._log_offset = 0
            with path.open('rb') as stream:
                stream.seek(self._log_offset)
                data = stream.read(1024 * 1024)
                self._log_offset = stream.tell()
            if data:
                self.log.appendPlainText(data.decode('utf-8', errors='replace').rstrip())
                self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        except OSError as exc:
            self.task_status.setText(f'读取服务端日志失败：{exc}')

    def send_command(self):
        command = self.command_input.text().strip()
        server = self.selected()
        if not command or not server:
            return
        try:
            send_server_command(server['path'], command)
        except (OSError, ValueError, RuntimeError) as exc:
            self._set_running_state(False)
            QMessageBox.warning(self, '指令没有发出', str(exc))
            return
        self.log.appendPlainText(f'> {command}')
        self.command_input.clear()

    def export_runtime(self):
        server = self.selected()
        if not server or getattr(self, '_busy', False):
            return
        if self.is_running(server):
            QMessageBox.information(self, '请先停止服务端', '停止后再导出，避免文件在导出过程中变化。')
            return
        if QMessageBox.question(self, '导出运行库和 Mod',
                '将导出运行库、Mod 和 amcl-server-pack.json。\n\n'
                '不包含配置、世界、白名单、日志、server.properties、EULA 或客户端文件。\n'
                '这不是完整整合包备份；依赖自定义配置的包还需人工整理配置后才能分发。继续？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        from export_destination_ui import choose_zip_destination
        destination = choose_zip_destination(
            self, '导出服务端运行包', Path(paths.GAME_DIR, 'exports'),
            f"{server.get('id') or 'amcl-server'}-runtime.zip")
        if not destination:
            return
        from server_export import export_runtime_pack
        self._run(lambda _: export_runtime_pack(server['path'], destination),
                  lambda path: self.log.appendPlainText(f'运行包已导出（不含配置和世界）：{path}'))

    def install_runtime(self):
        server = self.selected()
        if not server or getattr(self, '_busy', False):
            return
        if self.is_running(server):
            QMessageBox.information(self, '请先停止服务端', '运行期间不能补全运行库。')
            return
        raw_report = server['report']
        from server_install import inferred_runtime_identity
        report = inferred_runtime_identity(raw_report)
        loader = report['loader']
        mc = report['minecraftVersion']
        version = report['loaderVersion']
        # Reliable scan results should not make the user repeat three choices.
        # Ask only for fields that could not be derived from the package.
        if loader not in ('forge', 'neoforge'):
            loader, ok = QInputDialog.getItem(
                self, '补全运行库 · 信息待确认', '无法自动确认加载器，请选择：',
                ['forge', 'neoforge'], 0, False)
            if not ok:
                return
        if not mc:
            mc, ok = QInputDialog.getText(
                self, '补全运行库 · 信息待确认', 'Minecraft 版本：')
            if not ok:
                return
            mc = mc.strip()
        if not version:
            version, ok = QInputDialog.getText(
                self, '补全运行库 · 信息待确认',
                '加载器版本（例如 Forge 43.3.8）：')
            if not ok:
                return
            version = version.strip()
        from server_install import installer_source, install_server_runtime
        try:
            source = installer_source(loader, mc, version)
        except ValueError as exc:
            QMessageBox.warning(self, '版本填写有误', str(exc))
            return
        if QMessageBox.question(self, '确认补全服务端',
                f'MC {mc} / {loader} {version}\n来源：{source}\n\n'
                'AMCL 将自动选择兼容 Java；本机没有时会下载启动器管理的运行时。\n'
                '随后下载、校验并运行官方安装器，只补缺失运行库。\n'
                '不会执行包内脚本，不覆盖已有不同内容，不修改世界和配置。继续？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        def install(task):
            from settings import load_settings
            java, java_result = select_server_java(
                {'minecraftVersion': mc, 'requiredJava': report.get('requiredJava')},
                report, load_settings(), paths.RUNTIME_DIR,
                status_callback=task.report_status,
                progress_callback=task.report_progress)
            plan = install_server_runtime(
                server['path'], loader, mc, version, java, task.report_status)
            return plan, java_result[0]
        self._run(install,
                  lambda result: self.log.appendPlainText(
                      f"运行库补全完成（自动使用 Java {result[1]}），可点击启动：{result[0]['entry']}"))

    def show_mods(self):
        server = self.selected()
        if not server or getattr(self, '_busy', False):
            return
        def scan(_):
            from mod_deps import read_mod_metadata
            labels = {'client': '仅客户端 · 不应放入服务端', 'server': '仅服务端',
                      'both': '双端可加载（元数据声明）', 'unknown': '适用端未知'}
            lines = []
            for file in sorted(Path(server['path'], 'mods').glob('*.jar')):
                if file.is_symlink():
                    continue
                info = read_mod_metadata(str(file)) or {}
                lines.append(f"{info.get('name', file.name)} — {labels[info.get('environment', 'unknown')]}\n{file.name}")
            return '\n\n'.join(lines) or '没有找到 Mod。'
        def display(text):
            dialog = QDialog(self)
            dialog.setWindowTitle('服务端 Mod · 适用端')
            dialog.resize(680, 460)
            layout = QVBoxLayout(dialog)
            hint = QLabel('未知不代表不兼容；双端可加载不代表玩家必须安装。不会自动删除 Mod。')
            hint.setWordWrap(True)
            layout.addWidget(hint)
            body = QPlainTextEdit(text)
            body.setReadOnly(True)
            layout.addWidget(body)
            dialog.exec()
        self._run(scan, display)

    def show_candidate_report(self):
        server = self.selected()
        if not server:
            return
        from server_packs import read_candidate_report
        try:
            report = read_candidate_report(server)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, '无法读取审核报告', str(exc))
            return
        if not report:
            QMessageBox.information(self, '没有候选报告', '这个服务端不是由自动转换流程生成的。')
            return
        from server_pack_report import report_text
        dialog = QDialog(self)
        dialog.setWindowTitle('候选服务端审核报告')
        dialog.resize(760, 620)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(report_text(report))
        layout.addWidget(text, 1)
        close = QPushButton('关闭')
        close.clicked.connect(dialog.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        dialog.exec()

    def open_folder(self):
        server = self.selected()
        if server:
            QDesktopServices.openUrl(QUrl.fromLocalFile(server['path']))

    def choose_launch_jar(self):
        server = self.selected()
        if not server or getattr(self, '_busy', False):
            return
        current = server.get('launchJar')
        start = str(Path(server['path'], current)) if current else server['path']
        path, _ = QFileDialog.getOpenFileName(
            self, '选择服务端启动 JAR（取消则不更改）', start, 'Java Archive (*.jar)')
        if not path:
            return
        try:
            from server_packs import set_server_launch_jar
            relative = set_server_launch_jar(server, path)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, '无法使用这个 JAR', str(exc))
            return
        self.task_status.setText(f'启动入口已设为：{relative}')
        self.log.appendPlainText(f'启动入口已设为：{relative}')
        self.selection_changed.emit(server)

    def use_automatic_launch_entry(self):
        server = self.selected()
        if not server or getattr(self, '_busy', False):
            return
        try:
            from server_packs import set_server_launch_jar
            set_server_launch_jar(server, None)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, '无法恢复自动识别', str(exc))
            return
        self.task_status.setText('已恢复自动识别 Forge / NeoForge / Fabric 启动入口。')
        self.selection_changed.emit(server)

    def choose_import(self):
        window = self.window()
        skill_manager = getattr(window, 'skill_mgr', None)
        if skill_manager is not None and skill_manager.is_enabled('smart_import'):
            from smart_import_ui import start_smart_import
            start_smart_import(window)
            return
        path, _ = QFileDialog.getOpenFileName(self, '选择服务端压缩包', '', 'ZIP (*.zip)')
        if path:
            self.scan_import(path)

    def scan_import(self, path):
        if getattr(self, '_busy', False):
            QMessageBox.information(self, '正在处理服务端任务', '请等待当前任务结束后，再拖入下一个服务端包。')
            return
        game_dir = paths.GAME_DIR
        self._run(lambda task: inspect_archive(path, status_callback=task.report_status,
                      progress_callback=lambda done, total: self._report_progress(task, done, total)),
                  lambda report: self._preview(path, game_dir, report), '正在扫描压缩包…')

    @staticmethod
    def _report_progress(task, done, total):
        # Qt Signal(int) is 32-bit; archive byte counts may exceed 2 GiB.
        task.report_progress(min(1000, int(done * 1000 // max(1, total))), 1000)

    def _run(self, work, done, label='正在处理任务…'):
        self._busy = True
        self.import_btn.setEnabled(False)
        self.task_status.setText(label)
        self.task_progress.setRange(0, 0)
        self.task_progress.show()
        self.log.appendPlainText(label)
        task = BackgroundTask(work, self)
        task.status.connect(self.log.appendPlainText)
        task.status.connect(self.task_status.setText)
        def update_progress(value, total):
            self.task_progress.setRange(0, total)
            self.task_progress.setValue(value)
        task.progress.connect(update_progress)
        def finish(message):
            self._busy = False
            self.import_btn.setEnabled(True)
            self.task_status.setText(message)
            self.task_progress.setRange(0, 1000)
            self.task_progress.hide()
            self.log.appendPlainText(message)
        def failure(message):
            finish('处理失败：' + message)
            QMessageBox.warning(self, '服务端任务失败', message)
        def success(result):
            finish('当前处理步骤已完成。')
            try:
                done(result)
            except Exception as exc:
                failure(f'{type(exc).__name__}: {exc}')
        # Reset before success callback, which may start the next task.
        task.succeeded.connect(success)
        task.failed.connect(failure)
        task.cancelled_signal.connect(lambda: finish('任务已取消，未完成的导入不会加入列表。'))
        self._task = task
        task.start()

    def _preview(self, path, game_dir, report):
        self.task_status.setText('扫描完成，等待确认导入。')
        self.log.appendPlainText('扫描完成，等待确认导入。')
        message = (f"文件：{report['fileCount']} 个，展开约 {report['expandedBytes'] / 1024**2:.1f} MiB\n"
                   f"根目录：{report['packageRoot'] or '(压缩包根部)'}\n"
                   f"服务端目录：{report.get('serverRoot') or '(包根部)'}\n"
                   f"客户端目录：{report.get('clientRoot') or '(未声明)'}\n"
                   f"识别：{report['loader']} / MC {report['minecraftVersion'] or '未知'}\n"
                   f"Java：{report['requiredJava'] or '待确认'}\n\n"
                   '路径、重复文件、链接、大小限制和文件完整性检查已通过。\n'
                   '这不等于病毒扫描，JAR 和 Mod 仍是可执行代码，请确认来源可信。\n'
                   '包内脚本不会执行，清单中的启动命令不会执行。继续导入？')
        if report.get('contentProfile') == 'runtime-and-mods':
            message = ('注意：这是运行库＋Mod 包，不含配置、世界和服务器设置。\n'
                       '导入成功不代表原整合包的玩法配置已恢复。\n\n' + message)
        elif report.get('contentProfile') == 'server-content':
            message = ('注意：这是从客户端导出的服务端内容包，不含服务端运行库。\n'
                       '导入后需补全运行库并检查 Mod 兼容性；清单中的版本仅供确认。\n\n' + message)
        if QMessageBox.question(self, '确认导入服务端', message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            self.task_status.setText('已取消导入，未添加服务端。')
            self.log.appendPlainText('已取消导入，未添加服务端。')
            return
        def imported(folder):
            self.task_status.setText('服务端导入完成。')
            self.log.appendPlainText(f'导入完成：{folder}')
            self.refresh()
        self._run(lambda task: import_server_pack(path, game_dir, report['sha256'],
                      status_callback=task.report_status,
                      progress_callback=lambda done, total: self._report_progress(task, done, total)),
                  imported, '正在导入服务端…')

    def launch(self):
        if getattr(self, '_busy', False):
            return
        server = self.selected()
        if not server:
            return
        if self.is_running(server):
            QMessageBox.information(self, '服务端', '已有服务端在运行，请先停止。')
            return
        root = Path(server['path'])
        try:
            plan = build_launch_plan(root, selected_jar=server.get('launchJar'))
            accepted = eula_accepted(root)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '服务端尚不能启动', str(exc))
            return
        if not accepted:
            self._run(
                lambda task: fetch_minecraft_eula(),
                lambda payload: self._show_eula(server, root, plan, payload),
                '正在从 Minecraft 官网加载 EULA…')
            return
        self._prepare_launch(server, root, plan)

    def _show_eula(self, server, root, plan, payload):
        dialog = MinecraftEulaDialog(payload, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.task_status.setText('未同意 EULA，服务端没有启动。')
            return
        try:
            if build_launch_plan(root, selected_jar=server.get('launchJar')) != plan:
                raise ValueError('启动配置在阅读协议期间发生变化，请重新启动。')
            accept_minecraft_eula(root)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '无法保存 EULA 选择', str(exc))
            return
        self.log.appendPlainText('你已明确同意 Minecraft EULA；已为当前服务端写入 eula=true。')
        self.task_status.setText('EULA 已同意，正在准备启动。')
        self._prepare_launch(server, root, plan)

    def _prepare_launch(self, server, root, plan):
        from settings import load_settings
        self._run(
            lambda task: select_server_java(
                plan, server.get('report') or {}, load_settings(), paths.RUNTIME_DIR,
                status_callback=task.report_status,
                progress_callback=lambda done, total: self._report_progress(task, done, total)),
            lambda prepared: self._confirm_launch(
                server, root, plan, prepared[0], prepared[1]),
            '正在自动选择兼容 Java…')

    def _confirm_launch(self, server, root, plan, java, result):
        from java_manager import minecraft_java_warning
        major, error = result
        if error or not major:
            QMessageBox.warning(self, 'Java 无法使用', error or '无法识别 Java 版本')
            return
        mc = plan.get('minecraftVersion') or server['report'].get('minecraftVersion')
        warning = minecraft_java_warning(mc, major) if mc else '无法确认 MC 版本，请自行核对 Java 兼容性。'
        required = plan.get('requiredJava') or server['report'].get('requiredJava')
        if required and major < required:
            QMessageBox.warning(self, 'Java 版本过低', f'需要至少 Java {required}，当前是 Java {major}。')
            return
        if QMessageBox.question(self, '启动服务端',
                f"入口：{plan['entry']}\nJava：{major}\n{warning}\n"
                '将执行服务端及包内 Mod，请仅运行可信来源的包。继续？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            if build_launch_plan(root, selected_jar=server.get('launchJar')) != plan or not eula_accepted(root):
                raise ValueError('启动配置在确认期间发生变化，请重新启动。')
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '启动配置变化', str(exc))
            return
        self._run(
            lambda task: start_managed_server(root, java, plan['arguments']),
            lambda state: self._host_started(server, state),
            '正在启动后台服务端…')

    def _host_started(self, server, state):
        self._attached_session = None
        self._attach_selected()
        self.log.appendPlainText(
            f"服务端已交给后台托管（PID {state.get('pid')}）；关闭 AMCL 不会停止服务端。")

    def stop(self):
        server = self.selected()
        if not server:
            return
        try:
            send_server_command(server['path'], 'stop')
            self.log.appendPlainText('> stop\n已发送安全停止指令，等待保存世界并退出。')
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, '无法停止服务端', str(exc))
