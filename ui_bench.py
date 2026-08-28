# -*- coding: utf-8 -*-
"""启动基线探针(阶段 0):offscreen 下测量 启动耗时 / 内存(RSS) 各阶段耗时。

与 ci_smoke.py 同一套思路:QT_QPA_PLATFORM=offscreen,可在无显示器 / CI 三平台跑。
只构造 UI,不调用 load_versions()(网络)、不进 app.exec(),保证确定性。

用法:
    python ui_bench.py            # 单次
    python ui_bench.py --runs 3   # 跑 N 次(每轮独立进程),取中位数更稳
输出:JSON(机器可读)+ 人读摘要。
"""
import argparse
import gc
import json
import os
import sys
import time


def _setup_env():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)


def _rss_mb() -> float:
    """当前进程常驻内存(MB)。零第三方依赖:psutil → ctypes → /proc 逐级兜底。"""
    gc.collect()
    # 首选 psutil(若已安装)
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        pass
    # Windows:GetProcessMemoryInfo(psapi)——需显式 argtypes/restype,否则 HANDLE 被截断为 32 位
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            class _PMC(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            pmc = _PMC(); pmc.cb = ctypes.sizeof(_PMC)
            if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
                return pmc.WorkingSetSize / (1024 * 1024)
        except Exception:
            pass
    # Linux:/proc/self/status VmRSS
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    return -1.0


def run_once() -> dict:
    out = {"python": sys.version.split()[0]}

    # 1) 核心 import(PySide6 + main 顶层)
    t0 = time.perf_counter()
    from PySide6.QtWidgets import QApplication
    import main  # 触发模块级:settings/theme_icon/i18n 等 import 链
    out["import_core_s"] = round(time.perf_counter() - t0, 4)

    # 2) QApplication + 全局调色板
    t1 = time.perf_counter()
    app = QApplication.instance() or QApplication(sys.argv)
    from ui_style import apply_global_dark_palette
    apply_global_dark_palette(app)
    out["qapp_s"] = round(time.perf_counter() - t1, 4)

    # 3) 主窗口构造(全 tab:版本首页/资源中心/联机/设置/插件/AI dock)
    t2 = time.perf_counter()
    win = main.MainWindow()
    out["mainwindow_s"] = round(time.perf_counter() - t2, 4)
    out["rss_after_construct_mb"] = round(_rss_mb(), 1)

    # 4) show + 首帧
    t3 = time.perf_counter()
    win.show()
    app.processEvents()
    out["show_s"] = round(time.perf_counter() - t3, 4)
    out["rss_after_show_mb"] = round(_rss_mb(), 1)

    out["total_s"] = round(time.perf_counter() - t0, 4)
    out["total_from_qapp_s"] = round(out["qapp_s"] + out["mainwindow_s"] + out["show_s"], 4)
    return out


def main() -> int:
    _setup_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1, help="重复轮数(每轮独立进程,取中位数)")
    args = ap.parse_args()

    # 单轮:直接跑
    if args.runs <= 1:
        res = run_once()
        print(json.dumps(res, ensure_ascii=False, indent=2))
        _summary(res)
        return 0

    # 多轮:spawn 自身子进程各跑一次,取中位数
    import subprocess
    import statistics
    samples = []
    for i in range(args.runs):
        r = subprocess.run(
            [sys.executable, __file__],
            capture_output=True, text=True, timeout=180,
        )
        try:
            data = json.loads(r.stdout.strip().splitlines()[-1])
            samples.append(data)
        except Exception:
            print(f"[warn] 第 {i + 1} 轮解析失败:{r.stderr[:200]}", file=sys.stderr)
    if not samples:
        print("BENCH FAIL: 无有效样本", file=sys.stderr)
        return 1

    keys = ["import_core_s", "qapp_s", "mainwindow_s", "show_s",
            "total_s", "rss_after_construct_mb", "rss_after_show_mb"]
    med = {}
    for k in keys:
        vals = sorted(s[k] for s in samples if k in s)
        med[k] = round(statistics.median(vals), 4)
    print(json.dumps({"runs": args.runs, "median": med}, ensure_ascii=False, indent=2))
    _summary(med)
    return 0


def _summary(d: dict) -> None:
    print("---- 摘要 ----")
    for k in ("import_core_s", "qapp_s", "mainwindow_s", "show_s", "total_s"):
        if k in d:
            print(f"  {k:<22} {d[k]} s")
    for k in ("rss_after_construct_mb", "rss_after_show_mb"):
        if k in d:
            print(f"  {k:<22} {d[k]} MB")


if __name__ == "__main__":
    sys.exit(main())
