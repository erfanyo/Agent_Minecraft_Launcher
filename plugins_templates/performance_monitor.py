"""性能监控插件 (performance_monitor)
监听游戏日志并注册一个 AI 工具, 可查询实时 FPS / 警告 / 运行状态。
加载后需重启启动器生效。"""
import re
import time
from collections import deque

_log = deque(maxlen=400)
_state = {"on": False, "start": 0.0}

_FPS = [re.compile(r"(\d+) fps", re.I), re.compile(r"fps:\s*(\d+)", re.I)]
_WARN = ("warn", "warning", "exception", "error", "crash",
         "out of memory", "failed", "timeout")


def _fps(line):
    for p in _FPS:
        m = p.search(line)
        if m:
            return int(m.group(1))
    return None


def _is_warn(line):
    low = line.lower()
    return any(w in low for w in _WARN)


def _on_start(ctx, info):
    _state["on"] = True
    _state["start"] = time.time()
    _log.append("[perf] game start %s" % time.strftime("%H:%M:%S"))


def _on_stop(ctx, info):
    _state["on"] = False
    _log.append("[perf] game stop")


def _on_log(ctx, line):
    if not line:
        return
    line = line.rstrip("\n")
    f = _fps(line)
    if f is not None:
        _log.append("[fps] %d" % f)
    elif _is_warn(line):
        _log.append("[warn] " + line[:200])


def _tool_status(_p, _tools=None):
    """查询当前游戏 FPS / 内存 / 运行状态。"""
    out = {"game_running": _state["on"]}
    if _state["on"]:
        out["uptime_sec"] = int(time.time() - _state["start"])
    snaps = list(_log)
    fps = [s for s in snaps if s.startswith("[fps]")]
    warn = [s for s in snaps if s.startswith("[warn]")]
    if fps:
        out["last_fps"] = int(fps[-1].split()[-1])
        out["fps_samples"] = len(fps)
    if warn:
        out["recent_warnings"] = [w.replace("[warn] ", "") for w in warn[-5:]]
    out["buffer_size"] = len(snaps)
    return out


def register(api):
    api.register_hook("on_game_start", _on_start)
    api.register_hook("on_game_stop", _on_stop)
    api.register_hook("on_game_log", _on_log)
    api.register_tool("game_perf_status", _tool_status,
                      {"name": "游戏性能监控",
                       "desc": "查询当前游戏 FPS / 内存 / 警告 / 运行状态"})
