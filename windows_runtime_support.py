"""Repair Windows prerequisites needed by downloaded Java distributions."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os

from downloader import download_file


VC_REDIST_URLS = {
    "x64": "https://aka.ms/vc14/vc_redist.x64.exe",
    "aarch64": "https://aka.ms/vc14/vc_redist.arm64.exe",
}
_SUCCESS_CODES = {0, 1638, 3010}


def missing_vc_runtime(error: str) -> bool:
    """Return whether Java failed in the characteristic missing-runtime form."""
    low = (error or "").lower()
    return ("could not find java.dll" in low
            or "could not find java se runtime environment" in low)


def _trusted_signature(path: str) -> tuple[bool, str]:
    """Validate the installer's Authenticode chain using Windows WinVerifyTrust."""
    if os.name != "nt":
        return False, "当前系统不是 Windows"

    class Guid(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8),
        ]

    class WinTrustFileInfo(ctypes.Structure):
        _fields_ = [
            ("cbStruct", wintypes.DWORD), ("pcwszFilePath", wintypes.LPCWSTR),
            ("hFile", wintypes.HANDLE), ("pgKnownSubject", ctypes.POINTER(Guid)),
        ]

    class WinTrustData(ctypes.Structure):
        _fields_ = [
            ("cbStruct", wintypes.DWORD), ("pPolicyCallbackData", wintypes.LPVOID),
            ("pSIPClientData", wintypes.LPVOID), ("dwUIChoice", wintypes.DWORD),
            ("fdwRevocationChecks", wintypes.DWORD), ("dwUnionChoice", wintypes.DWORD),
            ("pFile", ctypes.POINTER(WinTrustFileInfo)), ("dwStateAction", wintypes.DWORD),
            ("hWVTStateData", wintypes.HANDLE), ("pwszURLReference", wintypes.LPCWSTR),
            ("dwProvFlags", wintypes.DWORD), ("dwUIContext", wintypes.DWORD),
            ("pSignatureSettings", wintypes.LPVOID),
        ]

    action = Guid(0x00AAC56B, 0xCD44, 0x11D0,
                  (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE))
    file_info = WinTrustFileInfo(
        ctypes.sizeof(WinTrustFileInfo), os.path.abspath(path), None, None)
    trust_data = WinTrustData()
    trust_data.cbStruct = ctypes.sizeof(WinTrustData)
    trust_data.dwUIChoice = 2       # WTD_UI_NONE
    trust_data.dwUnionChoice = 1    # WTD_CHOICE_FILE
    trust_data.pFile = ctypes.pointer(file_info)
    trust_data.dwProvFlags = 0x1000  # WTD_CACHE_ONLY_URL_RETRIEVAL
    wintrust = ctypes.WinDLL("wintrust", use_last_error=True)
    wintrust.WinVerifyTrust.argtypes = [wintypes.HWND, ctypes.POINTER(Guid), ctypes.c_void_p]
    wintrust.WinVerifyTrust.restype = ctypes.c_long
    status = int(wintrust.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(trust_data)))
    return status == 0, "" if status == 0 else f"Windows 信任检查返回 0x{status & 0xffffffff:08X}"


def _run_elevated_installer(path: str) -> tuple[int | None, str]:
    """Show one normal Windows UAC prompt and wait for the official installer."""
    if os.name != "nt":
        return None, "当前系统不是 Windows"

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", wintypes.LPVOID),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIconOrMonitor", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = os.path.abspath(path)
    info.lpParameters = "/install /quiet /norestart"
    info.nShow = 1
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.get_last_error()
        if code == 1223:
            return None, "用户取消了系统授权"
        return None, f"无法启动微软运行库安装程序（Windows 错误 {code}）"
    try:
        kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)):
            return None, f"无法读取安装结果（Windows 错误 {ctypes.get_last_error()}）"
        return int(exit_code.value), ""
    finally:
        kernel32.CloseHandle(info.hProcess)


def install_vc_runtime(cache_dir: str, arch: str = "x64",
                       progress_callback=None, status_callback=None) -> tuple[bool, str]:
    """Download Microsoft's signed VC runtime, elevate once, and install quietly."""
    if os.name != "nt":
        return False, "该修复只适用于 Windows"
    url = VC_REDIST_URLS.get(arch)
    if not url:
        return False, f"暂不支持 {arch} 架构的微软运行库自动安装"
    os.makedirs(cache_dir, exist_ok=True)
    installer = os.path.join(cache_dir, f"vc_redist.{arch}.exe")
    if status_callback:
        status_callback("Java 缺少 Windows 运行组件，正在下载微软官方修复程序…")
    try:
        download_file(url, installer, progress_callback=progress_callback)
        valid, detail = _trusted_signature(installer)
        if not valid:
            try:
                os.remove(installer)
            except OSError:
                pass
            return False, f"微软修复程序签名验证失败{f'：{detail}' if detail else ''}"
        if status_callback:
            status_callback("请在系统提示中选择“是”，AMCL 会修复组件后继续安装 Java。")
        code, detail = _run_elevated_installer(installer)
        if code not in _SUCCESS_CODES:
            return False, detail or f"微软运行库安装失败（退出码 {code}）"
        return True, "若 Windows 提示需要重启，可先继续尝试；仍失败时再重启。"
    except Exception as error:
        return False, f"微软运行库修复失败：{type(error).__name__}: {error}"
