# -*- coding: utf-8 -*-
"""CPU / 主板温度采样——按平台可插拔(os_platform 模块)。

**为什么抽象**:原来的 `_cpu_temperature()` 只支持 Windows(WMI 兜底)和 psutil,
Linux / macOS 上退化;现在把"各平台怎么读温度"做成可插拔——按平台自动探测,
拿不到就返回 None(宁可不提示,不崩溃,与原逻辑一致)。

平台策略(按优先级):
- Windows : ① psutil ② PowerShell WMI(MSAcpi_ThermalZoneTemperature)
- Linux   : ① psutil ② `sensors` 命令(lm-sensors)解析
- macOS   : ① psutil ② `powermetrics`(需要 root,失败静默)

调用方只需 `from os_platform.temperature import cpu_temperature`,不关心平台。
"""
import re
import subprocess


def _read_psutil() -> float | None:
    """尽量用 psutil 读温度(跨平台,若已安装)。失败/无传感器 → None。"""
    try:
        import psutil
        temps = psutil.sensors_temperatures()
        if temps:
            for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz",
                        "soc_thermal", "k8temp", "zenpower", "cpu-thermal",
                        "pmu", "chipset"):
                for rec in temps.get(key, []):
                    if rec.current is not None:
                        return float(rec.current)
    except Exception:
        pass
    return None


def _read_windows_wmi() -> float | None:
    """Windows:PowerShell WMI 读热区温度(部分笔记本/台式才有)。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue "
             "| ForEach-Object { ($_.CurrentTemperature / 10.0) - 273.15 }) "
             "| Sort-Object -Descending | Select-Object -First 1"],
            capture_output=True, text=True, timeout=2)
        return _parse_float(out.stdout)
    except Exception:
        return None


def _read_linux_sensors() -> float | None:
    """Linux:解析 `sensors` 命令(lm-sensors)输出中的温度。"""
    try:
        out = subprocess.run(["sensors"], capture_output=True, text=True, timeout=3)
        text = (out.stdout or "") + (out.stderr or "")
        m = re.findall(r"([+-]?\d+(?:\.\d+)?)°C", text)
        for v in map(float, m):
            if 0.0 < v < 120.0:
                return v
    except Exception:
        pass
    return None


def _read_macos_powermetrics() -> float | None:
    """macOS:powermetrics 采样 CPU 温度(需 root;失败/无权限静默)。"""
    try:
        out = subprocess.run(
            ["powermetrics", "--samplers", "smc", "-n", "1", "-i", "200ms"],
            capture_output=True, text=True, timeout=5)
        text = (out.stdout or "") + (out.stderr or "")
        m = re.findall(r"CPU die temperature:\s*([+-]?\d+(?:\.\d+)?)\s*C", text)
        if m:
            return float(m[0])
    except Exception:
        pass
    return None


def _parse_float(stdout: str | None) -> float | None:
    """从命令 stdout 里挑出第一个合理的温度值(0~120 之间)。"""
    if not stdout:
        return None
    for line in stdout.splitlines():
        line = line.strip()
        try:
            v = float(line)
        except ValueError:
            continue
        if 0.0 < v < 120.0:
            return v
    return None


def _wsl_fallback() -> float | None:
    """WSL 内读温度:WSL 里 sensors/硬件直读通常不可用,返回 None(不干扰)。"""
    return None


def cpu_temperature() -> float | None:
    """读 CPU/主板温度(°C)。

    按平台自动探测;拿不到(无传感器/非本机/失败)→ 返回 None(调用方据此不提示)。
    """
    from .system import is_linux, is_macos, is_windows, is_wsl

    # ① psutil(若有,跨平台通用)优先
    v = _read_psutil()
    if v is not None:
        return v

    # ② 平台定制
    if is_windows():
        return _read_windows_wmi()
    if is_wsl():
        return _wsl_fallback()
    if is_linux():
        return _read_linux_sensors()
    if is_macos():
        return _read_macos_powermetrics()
    return None


# 兼容旧名
get_cpu_temperature = cpu_temperature
