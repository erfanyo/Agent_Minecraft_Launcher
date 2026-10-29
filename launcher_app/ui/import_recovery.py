"""Restore unfinished imports into the status ball without dismiss-on-close."""
import hashlib
from pathlib import Path
from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QMessageBox
from launcher_app.core.background_tasks import BackgroundTask
from launcher_app.core.i18n import t
from launcher_app.resources import import_recovery as recovery
from launcher_app.ui.ui_style import set_style, current_color, text_color, card_btn_style


class ImportRecoveryController(QObject):
    def __init__(self, window, center, *, autostart=True):
        super().__init__(window)
        self.window, self.center = window, center
        self.records = {}
        self.scan_task = None
        self.retry_tasks = {}
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)
        if autostart:
            self.timer.start()
            QTimer.singleShot(0, self.refresh)

    def refresh(self):
        if self.scan_task and self.scan_task.is_running:
            return
        import paths
        game_dir = paths.GAME_DIR
        task = BackgroundTask(lambda _: recovery.pending(game_dir), self)
        self.scan_task = task
        task.succeeded.connect(self.apply)
        task.finished.connect(task.deleteLater)
        task.start()

    def apply(self, records):
        present = set()
        for record in records:
            key = 'import-incomplete-' + hashlib.sha256(record['instance'].encode()).hexdigest()[:20]
            present.add(key)
            self.records[key] = record
            if key not in self.center.tasks:
                page = QWidget()
                page.setObjectName('import_recovery_page')
                set_style(page, lambda: f'QWidget#import_recovery_page {{ background:{current_color("bg0")}; color:{text_color()}; }}')
                layout = QVBoxLayout(page)
                label = QLabel(t('整合包导入未完成；关闭窗口不会清除此提醒。'))
                label.setWordWrap(True)
                layout.addWidget(label)
                location = QLabel(record['instance'])
                location.setWordWrap(True)
                location.setTextFormat(Qt.TextFormat.PlainText)
                layout.addWidget(location)
                detail = QLabel()
                detail.setWordWrap(True)
                detail.setTextFormat(Qt.TextFormat.PlainText)
                page._recovery_status = detail
                layout.addWidget(detail)
                retry = QPushButton(t('补齐文件并重试'))
                retry.clicked.connect(lambda checked=False, k=key: self.resume(k))
                ignore = QPushButton(t('手动忽略此提醒'))
                set_style(retry, card_btn_style)
                set_style(ignore, card_btn_style)
                ignore.clicked.connect(lambda checked=False, k=key: self.ignore(k))
                layout.addWidget(retry); layout.addWidget(ignore); layout.addStretch()
                self.center.begin_task(record['name'], task_id=key, page=page)
            self.center.update_task(key, state='incomplete')
        for key in list(self.records):
            if key not in present:
                if key in self.retry_tasks and self.retry_tasks[key].is_running:
                    continue
                self.center.finish_task(key, 'idle')
                self.records.pop(key)

    def ignore(self, key):
        record = self.records.get(key)
        if not record:
            return
        try:
            recovery.ignore(record['instance'])
        except (OSError, ValueError) as error:
            QMessageBox.warning(self.window, t('导入未完成'), str(error))
            return
        self.center.finish_task(key, 'idle', t('已忽略提醒；实例仍未确认完整。'))
        self.status(key, t('已忽略提醒；实例仍未确认完整。'))
        for button in self.center.tasks[key].page.findChildren(QPushButton):
            button.setEnabled(False)
        # Do not leave the same import's transient download error pinning an X.
        marker = str(Path(record['instance'], '.amcl-cf-missing.json'))
        for other in self.center.tasks.values():
            if other.state == 'failed' and marker in other.message:
                self.center.finish_task(other.id, 'idle')
        self.refresh()

    def status(self, key, message):
        self.center.update_task(key, message=message)
        record = self.center.tasks.get(key)
        if record and hasattr(record.page, '_recovery_status'):
            record.page._recovery_status.setText(record.message)

    def resume(self, key):
        record = self.records.get(key)
        if not record or (key in self.retry_tasks and self.retry_tasks[key].is_running):
            return
        # Hash-bound retained source, original destination and fixed instance ID.
        # No arbitrary command, page-provided path, or falsely completed marker.
        from PySide6.QtCore import QStandardPaths
        downloads = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        def work(task):
            if not recovery.verify_source(record):
                raise ValueError(t('原包不可用或已变化，请从本地重新导入。'))
            import json
            from launcher_app.resources.cf_manual import REPORT_NAME, receive_downloads
            report = Path(record['instance'], REPORT_NAME)
            if report.is_file():
                missing = json.loads(report.read_text(encoding='utf-8'))
                receive_downloads(record['instance'], missing, [downloads])
            from launcher_app.resources.modpack import import_modpack
            return import_modpack(record['source'], record['game_dir'],
                instance_id=record['name'], status_callback=task.report_status,
                progress_callback=task.report_progress)
        task = BackgroundTask(work, self)
        self.retry_tasks[key] = task
        task.finished.connect(task.deleteLater)
        task.status.connect(lambda message: self.status(key, message))
        task.progress.connect(lambda done, total: self.center.update_task(key, done=done, total=total))
        def failed(error):
            self.center.update_task(key, state='incomplete', message=error)
            self.status(key, error)
            from launcher_app.resources.cf_manual import show_missing_dialog
            show_missing_dialog(self.window, error, lambda: self.resume(key))
        task.failed.connect(failed)
        def completed(_):
            self.center.finish_task(key, 'completed')
            self.window.refresh_instances()
            self.refresh()
        task.succeeded.connect(completed)
        self.center.update_task(key, state='incomplete')
        task.start()
