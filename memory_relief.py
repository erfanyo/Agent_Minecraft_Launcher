"""Explicit, one-shot Windows working-set relief. No termination or cache purge."""
import os
import sys


def pressure(available, heap_gb, desired_gb=0):
    from memory_policy import GIB
    if available is None:
        return 0
    demand = max(heap_gb, desired_gb) * GIB
    if available < demand + GIB // 2:
        return 2
    return 1 if available < demand + 2 * GIB else 0


def visible_game_window(pid):
    if os.name != 'nt':
        return False
    import ctypes
    from ctypes import wintypes
    found = []
    user = ctypes.windll.user32
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    @callback_type
    def visit(hwnd, data):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True
    user.EnumWindows(visit, 0)
    return bool(found)


def run_elevated():
    if os.name != 'nt':
        return False
    import base64
    import subprocess
    program = sys.executable
    args = ['--amcl-memory-relief', str(os.getpid())]
    if not getattr(sys, 'frozen', False):
        args.insert(0, os.path.join(os.path.dirname(__file__), 'main.py'))
    # Start-Process joins argument arrays, so quote each Windows argument first.
    command_line = subprocess.list2cmdline(args)
    quote = lambda s: "'" + s.replace("'", "''") + "'"
    script = ("try { $p=Start-Process -FilePath " + quote(program) +
              ' -ArgumentList ' + quote(command_line) +
              " -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ErrorAction Stop; exit $p.ExitCode } catch { exit 1 }")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                             base64.b64encode(script.encode('utf-16le')).decode()],
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=90,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def main(caller_pid):
    import ctypes
    import psutil
    from ctypes import wintypes
    kernel, api = ctypes.windll.kernel32, ctypes.windll.psapi
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    api.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
    def session(pid):
        value = wintypes.DWORD()
        if not kernel.ProcessIdToSessionId(pid, ctypes.byref(value)):
            raise OSError('Session unavailable')
        return value.value
    caller = psutil.Process(int(caller_pid))
    owner, sid = caller.username(), session(caller.pid)
    count = 0
    for process in psutil.process_iter(['pid', 'name', 'username']):
        try:
            if process.pid in (caller.pid, os.getpid()) or process.info['username'] != owner or session(process.pid) != sid:
                continue
            if process.info['name'].lower() in {'java.exe', 'javaw.exe', 'lsass.exe', 'csrss.exe', 'winlogon.exe', 'dwm.exe'}:
                continue
            handle = kernel.OpenProcess(0x0400 | 0x0100, False, process.pid)
            if handle:
                try:
                    count += bool(api.EmptyWorkingSet(handle))
                finally:
                    kernel.CloseHandle(handle)
        except (psutil.Error, OSError):
            continue
    return 0 if count else 2
