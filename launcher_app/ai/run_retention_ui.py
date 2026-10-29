"""Local run-log retention settings and explicit cleanup."""
from launcher_app.core.i18n import t
from PySide6.QtWidgets import QFormLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from launcher_app.ui.numeric_input import SettingsSpinBox
from launcher_app.ui.ui_switch import ToggleSwitch, setting_switch_row


class RunRetentionPanel(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        from launcher_app.ai.run_retention import _number
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        self.auto = ToggleSwitch(bool(settings.get('ai_run_log_auto_cleanup', True)))
        layout.addWidget(setting_switch_row(t('自动回收旧运行日志'), self.auto))
        form = QFormLayout()
        self.days = SettingsSpinBox()
        self.days.setRange(1, 3650)
        self.days.setSuffix(t(' 天'))
        self.days.setValue(_number(settings, 'ai_run_log_retention_days', 30, 3650))
        self.capacity = SettingsSpinBox()
        self.capacity.setRange(1, 102400)
        self.capacity.setSuffix(' MB')
        self.capacity.setValue(_number(settings, 'ai_run_log_max_mb', 100, 102400))
        form.addRow(t('保留时间'), self.days)
        form.addRow(t('容量上限'), self.capacity)
        layout.addLayout(form)
        hint = QLabel(t('超期或超出容量时，优先删除最旧的已结束运行日志。\n运行中、记录不完整的任务会保留；不清理聊天存档、备份或回滚记录。\n清理后无法恢复原始运行过程。自动清理在 AI 任务开始和结束时执行。'))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.clean = QPushButton(t('立即按规则清理'))
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.clean)
        layout.addWidget(self.status)
        self.clean.clicked.connect(self.cleanup)

    def values(self):
        return {'ai_run_log_auto_cleanup': self.auto.isChecked(),
                'ai_run_log_retention_days': self.days.value(),
                'ai_run_log_max_mb': self.capacity.value()}

    def cleanup(self):
        from launcher_app.core.background_tasks import BackgroundTask
        from launcher_app.ai.run_retention import cleanup_run_logs, cleanup_message
        from paths import data_dir
        settings = self.values()
        directory = data_dir('ai_runs')
        self.clean.setEnabled(False)
        self.status.setText(t('正在检查旧运行日志…'))
        self._task = BackgroundTask(lambda task: cleanup_run_logs(settings, directory), self)
        self._task.succeeded.connect(lambda result: self.status.setText(cleanup_message(result)))
        self._task.failed.connect(lambda error: self.status.setText(t('清理未完成：') + error))
        self._task.finished.connect(lambda: self.clean.setEnabled(True))
        self._task.start()
