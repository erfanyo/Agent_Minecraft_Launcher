"""Available-memory budgeting and sampled per-instance RSS history."""
import json
import os
import threading
import time
import uuid
import math

GIB = 1024 ** 3
_model_processes = {}
_game_processes = {}


def register_model_process(process):
    _model_processes[process.pid] = process


def process_usage(history_dir=None):
    """Owned processes only. External model providers remain in other applications."""
    import psutil
    def read(registry, games=False):
        total = 0
        for pid, entry in list(registry.items()):
            process, directory = entry if games else (entry, None)
            if process.poll() is not None:
                registry.pop(pid, None)
                continue
            if games and history_dir and os.path.normcase(os.path.abspath(directory)) != os.path.normcase(os.path.abspath(history_dir)):
                continue
            try:
                total += psutil.Process(pid).memory_info().rss
            except psutil.Error:
                return None
        return total
    return read(_model_processes), read(_game_processes, True)


def snapshot():
    try:
        import psutil
        memory = psutil.virtual_memory()
        return memory.total, memory.available
    except Exception:
        return None


def enabled_mod_count(game_dir):
    """Count enabled jar Mods only; this is a first-run estimate, not a demand model."""
    if not game_dir:
        return 0
    try:
        return sum(1 for name in os.listdir(os.path.join(game_dir, 'mods'))
                   if name.lower().endswith('.jar'))
    except OSError:
        return 0


def automatic_budget(total=None, available=None, history_peak_bytes=0, mods=0):
    """Return a conservative instance-aware Xmx plan.

    Normal mode leaves 15% of physical memory (at least 2 GiB) clear.  The
    only aggressive path is a <=16 GiB PC with a large pack / high measured
    history, where we retain 7% of physical memory rather than pretending the
    pack will fit in the normal budget.
    """
    if total is None or available is None:
        state = snapshot()
        if state is None:
            return {'gb': 2, 'basis': '无法读取系统内存，保守分配', 'aggressive': False}
        total, available = state
    total, available = max(0, int(total)), max(0, int(available))
    by_mods = max(2, math.ceil(max(0, int(mods)) / 25))
    by_history = math.ceil(max(0, int(history_peak_bytes)) * 1.15 / GIB) if history_peak_bytes else 0
    # A real measurement wins.  Mod count is only a first-run fallback; using
    # the larger of both would keep inflating an instance after it proved lean.
    desired = by_history if by_history else by_mods
    normal_cap = max(1, int((available - max(2 * GIB, total * .15)) // GIB))
    large_pack = mods >= 100 or history_peak_bytes >= 6 * GIB
    aggressive = total <= 16 * GIB and large_pack and desired > normal_cap
    reserve = total * (.07 if aggressive else .15)
    reserve = max(0, reserve if aggressive else max(reserve, 2 * GIB))
    cap = max(1, int((available - reserve) // GIB))
    value = max(1, min(16, desired, cap))
    if history_peak_bytes:
        basis = f'按历史峰值 {history_peak_bytes / GIB:.1f} GB 留出余量'
    else:
        basis = f'暂无历史，按 {mods} 个 Mod 估算（每 25 个 Mod 约 1 GB）'
    if aggressive:
        basis += '；内存紧张的大整合包模式，保留物理内存 7%'
    return {'gb': value, 'basis': basis, 'aggressive': aggressive,
            'desired_gb': desired, 'reserve_bytes': int(reserve)}


def automatic_gb(available=None, total=None, history_peak_bytes=0, mods=0):
    """Compatibility wrapper for callers that only need the selected GB."""
    if total is None and available is not None:
        # Existing callers only supplied availability; retain their unknown-total behavior.
        total = max(available, 8 * GIB)
    return automatic_budget(total, available, history_peak_bytes, mods)['gb']


def history_peak(directory):
    try:
        with open(os.path.join(directory, '.amcl_memory.json'), encoding='utf-8') as file:
            return max(0, int(json.load(file).get('rss_peak', 0)))
    except (OSError, ValueError, TypeError):
        return 0


def track_process(process, directory):
    """Observe only the launched Java process; daemon never keeps the launcher alive."""
    _game_processes[process.pid] = (process, directory)
    def work():
        try:
            import psutil
            target = psutil.Process(process.pid)
            peak = history_peak(directory)
            saved = peak
            last_save = 0
            def persist():
                nonlocal saved, last_save
                if peak <= saved or not os.path.isdir(directory):
                    return
                path = os.path.join(directory, '.amcl_memory.json')
                temporary = path + '.' + uuid.uuid4().hex + '.tmp'
                try:
                    with open(temporary, 'w', encoding='utf-8') as file:
                        json.dump({'rss_peak': max(peak, history_peak(directory)),
                                   'sample_interval_seconds': 2}, file)
                    os.replace(temporary, path)
                    saved, last_save = peak, time.monotonic()
                finally:
                    if os.path.exists(temporary):
                        os.remove(temporary)
            while process.poll() is None and target.is_running():
                try:
                    peak = max(peak, target.memory_info().rss)
                except psutil.NoSuchProcess:
                    break
                if time.monotonic() - last_save > 15:
                    persist()
                time.sleep(2)
            persist()
        except Exception:
            pass  # Metrics must never stop or prevent game launch.
    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread
