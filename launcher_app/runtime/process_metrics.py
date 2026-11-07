"""Best-effort process priority, CPU, memory and temperature sampling."""
import os
import time

_PRIORITY_NORMAL = 0x00000020

_PRIORITY_BELOW_NORMAL = 0x00004000

_PRIORITY_IDLE = 0x00000040

_CPU_HOT_C = 85.0

_MEM_LOW_MB = 1024.0

def _set_process_priority_class(pid: int, priority_class: int) -> bool:
    """设置进程优先级(仅 Windows;非 Windows 忽略)。返回是否成功。"""
    if os.name != "nt" or not pid:
        return False
    try:
        import ctypes
        PROCESS_SET_INFORMATION = 0x0200
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            ctypes.windll.kernel32.SetPriorityClass(handle, priority_class)
            return True
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return False

def _process_cpu_percent(pid: int, last: dict) -> float | None:
    """估算 pid 进程的 CPU 占用率(≈%,可>100 表示多核并行占用)。
    last 为字典,存上一次采样的 (cpu 累计 100ns, 时间戳),跨样本求增量;
    首次采样/间隔过短/非 Windows → 返回 None。失败静默。"""
    if os.name != "nt" or not pid:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD),
                        ("dwHighDateTime", wintypes.DWORD)]

        def _u64(ft: FILETIME) -> int:
            return (ft.dwHighDateTime << 32) + ft.dwLowDateTime

        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            ct_, et_, kt_, ut_ = FILETIME(), FILETIME(), FILETIME(), FILETIME()
            ok = ctypes.windll.kernel32.GetProcessTimes(
                handle, ctypes.byref(ct_), ctypes.byref(et_),
                ctypes.byref(kt_), ctypes.byref(ut_))
            if not ok:
                return None
            cpu = _u64(kt_) + _u64(ut_)          # 累计 CPU 时间,单位 100ns
            now = time.time()
            if last.get("cpu") is not None:
                dcpu = cpu - last["cpu"]
                dt = now - last["t"]
                if dt > 0.2 and dcpu >= 0:
                    # FILETIME=100ns;每核每秒钟 1e7 个 tick
                    pct = (dcpu / dt) / 1e7 * 100.0
                    last["cpu"] = cpu
                    last["t"] = now
                    n = os.cpu_count() or 1
                    return max(0.0, min(pct, 100.0 * n))
            last["cpu"] = cpu
            last["t"] = now
            return None
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return None

def _cpu_temperature() -> float | None:
    """采样 CPU/主板温度(°C)。委托给 platform.temperature 的跨平台可插拔实现
    (Windows: psutil→WMI;Linux: psutil→sensors;macOS: psutil→powermetrics)。
    取不到 → None(不干扰,宁可不提示)。"""
    try:
        from os_platform.temperature import cpu_temperature
        return cpu_temperature()
    except Exception:
        return None

def _system_available_memory_mb() -> float | None:
    """可用物理内存(MB)。Windows 用 GlobalMemoryStatusEx;失败 → None(不干扰)。"""
    if os.name != "nt":
        return None
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return m.ullAvailPhys / (1024.0 * 1024.0)
        return None
    except Exception:
        return None
