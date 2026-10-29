"""Safe launcher-side connection to the detached Minecraft server host."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time


def _runtime_dir(root, create=False):
    root = Path(root).resolve(strict=True)
    runtime = root / '.amcl-runtime'
    if runtime.exists() and (runtime.is_symlink() or not runtime.is_dir()):
        raise ValueError('.amcl-runtime 不是普通目录')
    if create:
        runtime.mkdir(exist_ok=True)
    return root, runtime


def _read_state(root):
    try:
        root, runtime = _runtime_dir(root)
    except FileNotFoundError:
        return None  # A selected server may have been removed while the UI timer is running.
    path = runtime / 'host.json'
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 256 * 1024:
        return None
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
        relative = state.get('logPath', '')
        log_path = (root / relative).resolve(strict=False)
        log_path.relative_to(root)
        if (state.get('schemaVersion') != 1 or not isinstance(state.get('port'), int)
                or not 1 <= state['port'] <= 65535
                or not isinstance(state.get('token'), str)
                or len(state['token']) < 32):
            return None
        state['logFile'] = str(log_path)
        return state
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _request(state, action, *, timeout=0.8, **values):
    message = {'token': state['token'], 'action': action, **values}
    with socket.create_connection(('127.0.0.1', state['port']), timeout=0.35) as connection:
        connection.settimeout(timeout)
        connection.sendall((json.dumps(message, ensure_ascii=False) + '\n').encode('utf-8'))
        data = b''
        while b'\n' not in data and len(data) <= 16 * 1024:
            chunk = connection.recv(4096)
            if not chunk:
                break
            data += chunk
    response = json.loads(data.split(b'\n', 1)[0].decode('utf-8'))
    if not response.get('ok'):
        raise RuntimeError(response.get('error') or '服务端托管进程拒绝了请求')
    return response


def managed_status(root, probe=True):
    state = _read_state(root)
    if not state:
        return None
    running = bool(state.get('running'))
    if running and probe:
        try:
            running = bool(_request(state, 'status').get('running'))
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError):
            running = False
    state['running'] = running
    return state


def force_stop_server(root, expected_session, expected_pid):
    """Only end the exact session the user confirmed, including older hosts."""
    state = managed_status(root)
    if not state or not state.get('running'):
        return
    if state.get('sessionId') != expected_session or state.get('pid') != expected_pid:
        raise RuntimeError('服务端会话已变化，请重新确认。')
    try:
        _request(state, 'force_stop', timeout=8)
        return
    except RuntimeError as exc:
        if 'unknown action' not in str(exc):
            raise
    # Compatibility with a host launched before the force_stop API existed.
    import psutil
    from datetime import datetime
    process = psutil.Process(expected_pid)
    started = datetime.fromisoformat(state['startedAt']).timestamp()
    if (abs(process.create_time() - started) > 10
            or Path(process.cwd()).resolve() != Path(root).resolve()
            or process.name().lower() not in ('java', 'java.exe', 'javaw.exe')):
        raise RuntimeError('进程身份无法确认，未执行强制结束。')
    latest = _read_state(root)
    if not latest or latest.get('sessionId') != expected_session:
        raise RuntimeError('服务端会话已变化，未执行强制结束。')
    process.terminate()
    try:
        process.wait(timeout=5)
    except psutil.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def abort_failed_server_startup(root):
    state = managed_status(root)
    if state and state.get('running'):
        _request(state, 'abort_failed_startup')


def send_server_command(root, command):
    state = managed_status(root)
    if not state or not state['running']:
        raise RuntimeError('当前服务端没有运行，或已无法连接。')
    _request(state, 'command', command=command)
    return state


def _host_command(request_path):
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--amcl-server-host', str(request_path)]
    return [sys.executable, '-u', str(Path(__file__).resolve().parents[2] / 'main.py'),
            '--amcl-server-host', str(request_path)]


def start_managed_server(root, java, arguments, timeout=8.0):
    root, runtime = _runtime_dir(root, create=True)
    current = managed_status(root)
    if current and current['running']:
        raise RuntimeError('这个服务端已经在运行。')
    java = Path(java).resolve(strict=True)
    if not java.is_file():
        raise ValueError('Java 可执行文件不存在')
    session_id = secrets.token_hex(12)
    request = {
        'root': str(root),
        'java': str(java),
        'arguments': list(arguments),
        'token': secrets.token_urlsafe(32),
        'sessionId': session_id,
    }
    handle = tempfile.NamedTemporaryFile(
        mode='w', encoding='utf-8', newline='\n',
        prefix='host-request-', suffix='.json', dir=runtime, delete=False)
    request_path = Path(handle.name)
    with handle:
        json.dump(request, handle, ensure_ascii=False)
        handle.write('\n')
    try:
        os.chmod(request_path, 0o600)
    except OSError:
        pass
    kwargs = {
        'stdin': subprocess.DEVNULL,
        'stdout': subprocess.DEVNULL,
        'stderr': subprocess.DEVNULL,
        'close_fds': True,
    }
    if os.name == 'nt':
        # CREATE_NO_WINDOW is ignored when combined with DETACHED_PROCESS.
        kwargs['creationflags'] = (getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x00000200)
                                   | getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000))
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        kwargs['startupinfo'] = startup
    else:
        kwargs['start_new_session'] = True
    host_process = subprocess.Popen(_host_command(request_path), cwd=root, **kwargs)
    # Reap the detached helper while AMCL stays open, without coupling the
    # helper lifetime to this daemon thread or to the launcher window.
    threading.Thread(target=host_process.wait, daemon=True,
                     name='amcl-server-host-reaper').start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = managed_status(root)
        if state and state.get('sessionId') == session_id and state['running']:
            return state
        time.sleep(0.08)
    try:
        request_path.unlink(missing_ok=True)
    except OSError:
        pass
    raise RuntimeError('服务端托管进程没有按时启动，请查看启动器日志。')
