"""Detached Minecraft server host with a localhost-only command channel."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path, value):
    path = Path(path)
    handle = tempfile.NamedTemporaryFile(
        mode='w', encoding='utf-8', newline='\n',
        prefix=path.name + '-', suffix='.pending', dir=path.parent, delete=False)
    pending = Path(handle.name)
    try:
        with handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(pending, 0o600)
        except OSError:
            pass
        os.replace(pending, path)
    finally:
        try:
            pending.unlink(missing_ok=True)
        except OSError:
            pass


def _read_request(path):
    path = Path(path).resolve(strict=True)
    if path.stat().st_size > 256 * 1024:
        raise ValueError('host request is too large')
    value = json.loads(path.read_text(encoding='utf-8'))
    root = Path(value['root']).resolve(strict=True)
    java = Path(value['java']).resolve(strict=True)
    arguments = value.get('arguments')
    if not java.is_file() or not isinstance(arguments, list) or not arguments:
        raise ValueError('invalid server launch request')
    if any(not isinstance(item, str) or '\x00' in item for item in arguments):
        raise ValueError('invalid server argument')
    token = value.get('token')
    session_id = value.get('sessionId')
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError('invalid host token')
    if not isinstance(session_id, str) or not session_id.isalnum():
        raise ValueError('invalid session id')
    runtime = root / '.amcl-runtime'
    if runtime.is_symlink() or not runtime.is_dir():
        raise ValueError('invalid runtime directory')
    return value, root, java, arguments, runtime


def _reply(connection, payload):
    connection.sendall((json.dumps(payload, ensure_ascii=False) + '\n').encode('utf-8'))


def run_host(request_path):
    request = Path(request_path)
    value, root, java, arguments, runtime = _read_request(request)
    try:
        request.unlink()
    except OSError:
        pass
    state_path = runtime / 'host.json'
    logs = runtime / 'logs'
    logs.mkdir(exist_ok=True)
    if logs.is_symlink():
        raise ValueError('invalid log directory')
    log_relative = f'.amcl-runtime/logs/{value["sessionId"]}.log'
    log_path = root / Path(log_relative)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', 0))
    listener.listen(8)
    listener.settimeout(0.4)
    environment = os.environ.copy()
    for key in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS', 'CLASSPATH'):
        environment.pop(key, None)
    with log_path.open('ab', buffering=0) as output:
        output.write(
            f'\n[AMCL] 会话开始：{_utc_now()}\n'.encode('utf-8'))
        process = subprocess.Popen(
            [str(java), *arguments], cwd=root, env=environment,
            stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT,
            creationflags=(getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                           | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)),
        )
        state = {
            'schemaVersion': 1,
            'sessionId': value['sessionId'],
            'pid': process.pid,
            'hostPid': os.getpid(),
            'port': listener.getsockname()[1],
            'token': value['token'],
            'logPath': log_relative,
            'startedAt': _utc_now(),
            'running': True,
        }
        _write_json(state_path, state)
        while process.poll() is None:
            try:
                connection, _address = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                connection.settimeout(1.0)
                try:
                    raw = b''
                    while b'\n' not in raw and len(raw) <= 16 * 1024:
                        chunk = connection.recv(4096)
                        if not chunk:
                            break
                        raw += chunk
                    message = json.loads(raw.split(b'\n', 1)[0].decode('utf-8'))
                    if message.get('token') != value['token']:
                        _reply(connection, {'ok': False, 'error': 'unauthorized'})
                        continue
                    action = message.get('action')
                    if action == 'status':
                        _reply(connection, {'ok': True, 'running': process.poll() is None,
                                            'pid': process.pid})
                    elif action == 'command':
                        command = message.get('command')
                        if (not isinstance(command, str) or not command.strip()
                                or len(command) > 4096
                                or any(char in command for char in ('\r', '\n', '\x00'))):
                            _reply(connection, {'ok': False, 'error': 'invalid command'})
                            continue
                        if process.stdin is None:
                            raise RuntimeError('server input is unavailable')
                        process.stdin.write((command.strip() + '\n').encode('utf-8'))
                        process.stdin.flush()
                        _reply(connection, {'ok': True})
                    else:
                        _reply(connection, {'ok': False, 'error': 'unknown action'})
                except Exception as exc:
                    try:
                        _reply(connection, {'ok': False, 'error': str(exc)})
                    except OSError:
                        pass
        code = process.wait()
        output.write(f'\n[AMCL] 服务端已退出：{code} · {_utc_now()}\n'.encode('utf-8'))
    listener.close()
    state.update({'running': False, 'exitCode': code, 'endedAt': _utc_now()})
    _write_json(state_path, state)
    return code


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 2 and args[0] == '--config':
        return run_host(args[1])
    if len(args) == 1:
        return run_host(args[0])
    raise SystemExit('usage: server_host.py [--config] REQUEST')


if __name__ == '__main__':
    raise SystemExit(main())
