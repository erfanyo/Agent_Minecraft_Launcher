# -*- coding: utf-8 -*-
"""Minecraft 子进程与日志流控制器。"""
from __future__ import annotations

import os
import queue
import subprocess
import threading

from PySide6.QtCore import QObject, QTimer, Signal

_PROCESS_EXIT = object()


class GameProcessController(QObject):
    line_received = Signal(str)
    exited = Signal(int)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.process = None
        self._lines = queue.Queue()
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._drain)
        self._accept_events = True

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, command: list[str], java_exe: str, cwd: str, independent=False):
        from instance_maintenance import assert_not_maintaining
        assert_not_maintaining()
        if self.is_running:
            raise RuntimeError("游戏进程已经在运行")
        cmd = list(command)
        javaw = os.path.join(os.path.dirname(java_exe), "javaw.exe")
        if os.path.isfile(javaw):
            cmd = [javaw] + cmd[1:]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        import tempfile
        output = tempfile.TemporaryFile(mode='w+b') if independent else None
        try:
            process = subprocess.Popen(
            cmd,
            stdout=output if independent else subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            creationflags=creationflags,
            )
        except Exception:
            if output:
                output.close()
            raise
        self.process = process
        self._accept_events = True
        self._lines = queue.Queue()
        if independent:
            # Child inherits a file handle, not a pipe whose reader dies with AMCL.
            # Qt logs are unavailable in this mode; Minecraft still writes latest.log.
            output.close()
            threading.Thread(target=self._wait_only, args=(process,), daemon=True).start()
        else:
            threading.Thread(target=self._read, args=(process,), daemon=True).start()
        self._timer.start()
        return process

    def _wait_only(self, process):
        code = process.wait()
        if self._accept_events:
            self._lines.put((_PROCESS_EXIT, code))

    def _read(self, process) -> None:
        stream = process.stdout
        if stream is not None:
            for line in stream:
                # 启动器关闭后仍持续排空 PIPE，防止 Minecraft 被写满的管道卡住；
                # 但不再积压无需显示的日志。
                if self._accept_events:
                    self._lines.put(line.rstrip())
        code = process.wait()
        if self._accept_events:
            self._lines.put((_PROCESS_EXIT, code))

    def _drain(self) -> None:
        while True:
            try:
                line = self._lines.get_nowait()
            except queue.Empty:
                return
            if isinstance(line, tuple) and line and line[0] is _PROCESS_EXIT:
                self._timer.stop()
                if self._accept_events:
                    self.exited.emit(int(line[1]))
                return
            if self._accept_events:
                self.line_received.emit(line)

    def detach(self) -> None:
        """关闭启动器时停止 UI 转发，不结束仍在运行的 Minecraft。"""
        self._accept_events = False
        self._timer.stop()
