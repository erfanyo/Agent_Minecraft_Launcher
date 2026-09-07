# -*- coding: utf-8 -*-
"""面向界面的后台任务控制器。

这里负责“同一时间只能有一个任务、刷新合并、关闭时取消”等生命周期；
窗口只负责把信号显示成文字、进度条和列表，不再直接管理线程对象。
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from background_tasks import BackgroundTask


class DownloadTaskController(QObject):
    """串行执行启动器下载任务，并暴露统一的 UI 信号。"""

    status = Signal(str)
    progress = Signal(int, int)
    completed = Signal(bool, str)
    cancelled = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._task: BackgroundTask | None = None
        self.last_worker = None
        self.state = 'idle'

    @property
    def is_running(self) -> bool:
        return self.state == 'running'

    def start(self, worker: Callable) -> bool:
        if self.is_running:
            return False
        self.last_worker = worker
        self.state = 'running'
        def run(current):
            errors = []
            def status(message):
                # Compatibility for legacy workers reporting final failures as text.
                if str(message).startswith("❌"):
                    errors.append(str(message))
                current.report_status(message)
            result = worker(status, current.report_progress)
            if errors or result is False:
                raise RuntimeError("\n".join(errors) or "下载没有完成，请查看详情")
            return result
        task = BackgroundTask(run, self)
        self._task = task
        task.status.connect(self.status)
        task.progress.connect(self.progress)
        task.succeeded.connect(lambda _result: self._finish(True, ""))
        task.failed.connect(lambda error: self._finish(False, error))
        task.cancelled_signal.connect(self._cancelled)
        task.start()
        return True

    def _finish(self, ok, error):
        self.state = 'success' if ok else 'failed'
        self.completed.emit(ok, error)

    def _cancelled(self):
        self.state = 'cancelled'
        self.cancelled.emit()

    def cancel(self) -> None:
        if self._task is not None:
            self._task.cancel()


class VersionManifestController(QObject):
    """加载版本清单；刷新期间再次请求时合并为随后的一次刷新。"""

    loaded = Signal(object)
    failed = Signal(str)
    loading_changed = Signal(bool)

    def __init__(self, loader: Callable, parent: QObject | None = None):
        super().__init__(parent)
        self._loader = loader
        self._task: BackgroundTask | None = None
        self._refresh_pending = False

    @property
    def is_loading(self) -> bool:
        return self._task is not None and self._task.is_running

    def refresh(self) -> bool:
        if self.is_loading:
            self._refresh_pending = True
            return False
        self.loading_changed.emit(True)
        task = BackgroundTask(lambda _task: self._loader(), self)
        self._task = task
        task.succeeded.connect(self.loaded)
        task.failed.connect(self.failed)
        task.finished.connect(self._finished)
        task.start()
        return True

    def _finished(self) -> None:
        self.loading_changed.emit(False)
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh()

    def cancel(self) -> None:
        self._refresh_pending = False
        if self._task is not None:
            self._task.cancel()
