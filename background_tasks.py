# -*- coding: utf-8 -*-
"""GUI 后台任务的统一生命周期。

耗时函数在 Python 线程执行；状态、进度、结果和错误通过 Qt 信号回到主线程。
取消为协作式：任务可读取 ``cancelled``，下载器后续接入分块取消时无需再改 UI 协议。
"""
from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal
from task_context import cancel_event, checkpoint, TaskCancelled


class BackgroundTask(QObject):
    status = Signal(str)
    progress = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()
    cancelled_signal = Signal()

    def __init__(self, work: Callable, parent: QObject | None = None):
        super().__init__(parent)
        self._work = work
        self._cancel = threading.Event()
        self._thread = None
        self._running = False

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def is_running(self) -> bool:
        return self._running

    def cancel(self) -> None:
        self._cancel.set()

    @staticmethod
    def _emit(signal, *args) -> None:
        """窗口先于守护线程关闭时，安静丢弃已无接收者的晚到信号。"""
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    def report_status(self, message) -> None:
        checkpoint()
        if not self.cancelled:
            self._emit(self.status, str(message))

    def report_progress(self, done, total) -> None:
        checkpoint()
        if not self.cancelled:
            self._emit(self.progress, int(done), int(total))

    def start(self) -> "BackgroundTask":
        if self._running:
            return self
        self._running = True

        def run():
            token = cancel_event.set(self._cancel)
            try:
                checkpoint()
                result = self._work(self)
                checkpoint()
                if not self.cancelled:
                    self._emit(self.succeeded, result)
            except TaskCancelled:
                self._emit(self.cancelled_signal)
            except Exception as exc:
                if not self.cancelled:
                    self._emit(self.failed, f"{type(exc).__name__}: {exc}")
            finally:
                cancel_event.reset(token)
                self._running = False
                self._emit(self.finished)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return self
