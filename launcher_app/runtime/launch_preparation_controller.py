"""Qt task adapter for launch preparation; no widgets or main-window access."""
from PySide6.QtCore import QObject, Signal, Slot
from launcher_app.core.background_tasks import BackgroundTask


class LaunchPreparationController(QObject):
    status = Signal(str)
    progress = Signal(object, object)
    prepared = Signal(object, object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, current_game_root, parent=None):
        super().__init__(parent)
        self._current_game_root = current_game_root
        self._task = None
        self._request = None

    @property
    def busy(self):
        return self._task is not None

    def create_task(self, request):
        """Create without starting, so the caller can publish task UI first."""
        if self.busy:
            raise RuntimeError('启动准备任务尚未结束')
        task = BackgroundTask(lambda current: request.prepare(
            status_cb=current.report_status, progress_cb=current.report_progress), self)
        self._task, self._request = task, request
        task.status.connect(self.status)
        task.progress.connect(self.progress)
        task.failed.connect(self.failed)
        task.cancelled_signal.connect(self.cancelled)
        task.succeeded.connect(self._prepared)
        task.finished.connect(self._finished)
        return task

    @Slot(object)
    def _prepared(self, plan):
        if self._task is None:
            return
        if self._task.cancelled:
            self.cancelled.emit()
            return
        if self._current_game_root() != self._request.game_root:
            self.failed.emit('游戏目录已经变了，请重新点击启动')
            return
        self.prepared.emit(plan, self._request.version)

    @Slot()
    def _finished(self):
        if self._task is not None:
            self._task.deleteLater()
        self._task = None
        self._request = None

    def cancel(self):
        if self._task is not None:
            self._task.cancel()
