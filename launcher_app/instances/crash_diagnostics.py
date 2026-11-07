"""Minecraft 崩溃识别与诊断材料收集。"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class GameRunEvidence:
    """Capture the launched directory and time; later selection/settings may change."""
    game_dir: str
    started_at: float

    def has_crash(self):
        return detect_crash(self.game_dir, self.started_at)

    def report(self, exit_code):
        return collect_crash_report(self.game_dir, exit_code, started_at=self.started_at)


CRASH_MARKERS = (
    "---- minecraft crash report ----",
    "a fatal error has been detected",
    "failed to start the minecraft server",
    "outofmemoryerror",
    "java.lang.nullpointer",
)


def detect_crash(game_dir: str, started_at: float = 0) -> bool:
    crash_dir = os.path.join(game_dir, "crash-reports")
    if os.path.isdir(crash_dir):
        try:
            for name in os.listdir(crash_dir):
                path = os.path.join(crash_dir, name)
                if os.path.isfile(path) and os.path.getmtime(path) >= float(started_at or 0):
                    return True
        except OSError:
            pass

    log_path = os.path.join(game_dir, "logs", "latest.log")
    try:
        if os.path.getmtime(log_path) < float(started_at or 0):
            return False
        with open(log_path, "rb") as file:
            file.seek(0, os.SEEK_END)
            file.seek(max(0, file.tell() - 16000))
            tail = file.read().decode("utf-8", errors="replace").lower()
    except OSError:
        return False
    return any(marker in tail for marker in CRASH_MARKERS)


def collect_crash_report(game_dir: str, exit_code: int,
                         log_lines: int = 60, crash_chars: int = 2000,
                         *, started_at: float = 0) -> str:
    parts = [f"游戏进程异常退出(退出码 {exit_code})。"]
    log_path = os.path.join(game_dir, "logs", "latest.log")
    try:
        if os.path.getmtime(log_path) < float(started_at or 0):
            raise OSError('日志早于本次运行')
        with open(log_path, encoding="utf-8", errors="replace") as file:
            lines = file.read().splitlines()
        parts.append(f"【最新日志(尾部 {log_lines} 行)】\n" + "\n".join(lines[-log_lines:]))
    except OSError:
        pass

    crash_dir = os.path.join(game_dir, "crash-reports")
    try:
        files = []
        for name in os.listdir(crash_dir):
            path = os.path.join(crash_dir, name)
            if os.path.isfile(path):
                stamp = os.path.getmtime(path)
                if stamp >= float(started_at or 0):
                    files.append((stamp, name))
        files.sort(reverse=True)
        if files:
            with open(os.path.join(crash_dir, files[0][1]),
                      encoding="utf-8", errors="replace") as file:
                parts.append("【最新崩溃报告(摘要)】\n" + file.read(crash_chars))
    except OSError:
        pass
    from launcher_app.core.log_privacy import redact_text
    from settings import load_settings
    return redact_text("\n\n".join(parts), load_settings())
