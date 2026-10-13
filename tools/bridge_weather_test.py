"""Deterministic /ai weather responder. No model, launcher or account access.

Run against a dedicated test world's .bridge directory. The game must already
be in that world; stop other AI responders. Modern TCP and legacy file bridges
are supported. A passing result verifies command feedback, not rendered weather.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import socket
import tempfile
import time

PROMPT = '天气改为雨天'
COMMAND = 'weather rain'
MAX_JSON = 1024 * 1024


def read_json(path):
    try:
        if path.is_symlink() or path.stat().st_size > MAX_JSON:
            return None
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def write_json(path, value):
    if path.is_symlink():
        raise ValueError('Refusing to overwrite a symlink')
    handle, temporary = tempfile.mkstemp(prefix='.weather-test-', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def wait_request(directory, started_ms, timeout, *, prompt=PROMPT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        request = read_json(directory / 'ai_request.json')
        if (request and request.get('text') == prompt
                and type(request.get('seq')) is int and request['seq'] > 0
                and type(request.get('ts')) in (int, float)
                and started_ms <= request['ts'] <= time.time() * 1000 + 5000):
            return request
        time.sleep(.05)
    raise TimeoutError('No fresh matching /ai request; enter the test world and submit /ai ' + prompt)


def validate_request(request):
    if type(request.get('protocol_version')) is not int or request['protocol_version'] < 2:
        raise ValueError('Bridge protocol v2 required; install the current test JAR')
    player = request.get('player')
    if not isinstance(player, str) or not player.strip() or player == 'console':
        raise ValueError('An online player identity is required; console execution is not this test')
    if request.get('exec_mode', 'player') != 'player':
        raise ValueError('Use /ai without --console; permission must be checked as the player')
    return player


def validate_result(result, seq, *, legacy=False):
    if result.get('error'):
        raise RuntimeError('Bridge rejected the command: ' + str(result['error']))
    if type(result.get('seq')) is not int or result['seq'] != seq:
        raise ValueError('Command response sequence does not match')
    if type(result.get('success')) is not bool or not isinstance(result.get('result'), str):
        raise ValueError('Incomplete command execution result')
    if not legacy and result.get('command', '').lstrip('/') != COMMAND:
        raise ValueError('Command response refers to another command')
    return result


def command_tcp(directory, player, seq, port, timeout):
    token_path = directory / 'token.txt'
    if token_path.is_symlink() or token_path.stat().st_size > 4096:
        raise ValueError('Invalid bridge token file')
    token = token_path.read_text(encoding='utf-8').strip()
    if not token:
        raise ValueError('Empty bridge token')
    request = {'seq': seq, 'command': COMMAND, 'as_player': player, 'token': token}
    with socket.create_connection(('127.0.0.1', port), timeout=timeout) as client:
        client.settimeout(timeout)
        client.sendall((json.dumps(request) + '\n').encode('utf-8'))
        data = bytearray()
        while b'\n' not in data:
            chunk = client.recv(8192)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > MAX_JSON:
                raise ValueError('Bridge response too large')
    if not data:
        raise RuntimeError('Bridge returned no TCP result')
    result = json.loads(bytes(data).split(b'\n')[0].decode('utf-8'))
    if not isinstance(result, dict):
        raise ValueError('Bridge result is not an object')
    return validate_result(result, seq)


def command_file(directory, player, seq, timeout):
    write_json(directory / 'command_request.json',
               {'seq': seq, 'command': '/' + COMMAND, 'as_player': player})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = read_json(directory / 'command_reply.json')
        if result and result.get('seq') == seq:
            return validate_result(result, seq, legacy=True)
        time.sleep(.05)
    raise TimeoutError('No matching legacy command_reply.json')


def run_case(directory, *, expect='success', transport='auto', port=26100,
             request_timeout=120, result_timeout=15, started_ms=None):
    if expect not in ('success', 'denied') or transport not in ('auto', 'tcp', 'file'):
        raise ValueError('Invalid expected result or transport')
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink() or directory.is_junction():
        raise ValueError('Provide an existing ordinary .bridge directory')
    directory = directory.resolve()
    started_ms = time.time() * 1000 if started_ms is None else started_ms
    request = wait_request(directory, started_ms, request_timeout)
    player = validate_request(request)
    if transport == 'auto':
        transport = 'tcp' if (directory / 'token.txt').exists() else 'file'
    seq = time.time_ns()
    if transport == 'tcp':
        result = command_tcp(directory, player, seq, port, result_timeout)
    else:
        result = command_file(directory, player, seq, result_timeout)
    previous = read_json(directory / 'ai_reply.json')
    if (previous and previous.get('seq') == request['seq']
            and type(previous.get('ts')) in (int, float) and previous['ts'] >= started_ms):
        raise RuntimeError('Another AI responder wrote this reply; stop launcher AI and retry')
    reply = {'seq': request['seq'], 'text': ('测试：命令执行成功。' if result['success'] else
             '测试：命令被拒绝或执行失败。') + '\n' + result['result'], 'ts': int(time.time() * 1000)}
    write_json(directory / 'ai_reply.json', reply)
    consumed_deadline = time.monotonic() + min(result_timeout, 5)
    while (directory / 'ai_reply.json').exists() and time.monotonic() < consumed_deadline:
        time.sleep(.05)
    consumed = not (directory / 'ai_reply.json').exists()
    expected = expect == 'success'
    passed = result['success'] == expected and bool(result['result'].strip()) and consumed
    return {'passed': passed, 'expect': expect, 'transport': transport,
            'aiSeq': request['seq'], 'commandSeq': seq, 'player': player,
            'permissionLevel': request.get('permission_level'),
            'serverType': request.get('server_type'), 'command': COMMAND,
            'execution': result, 'replyConsumed': consumed, 'worldWeatherVerified': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge-dir', required=True, type=Path)
    parser.add_argument('--expect', choices=('success', 'denied'), default='success')
    parser.add_argument('--transport', choices=('auto', 'tcp', 'file'), default='auto')
    parser.add_argument('--port', type=int, default=26100)
    parser.add_argument('--request-timeout', type=float, default=120)
    parser.add_argument('--result-timeout', type=float, default=15)
    parser.add_argument('--report', type=Path, default=Path('.tmp/bridge-weather-result.json'))
    args = parser.parse_args(argv)
    print('Waiting for /ai ' + PROMPT, flush=True)
    try:
        report = run_case(args.bridge_dir, expect=args.expect, transport=args.transport,
                          port=args.port, request_timeout=args.request_timeout, result_timeout=args.result_timeout)
    except (OSError, ValueError, RuntimeError) as error:
        report = {'passed': False, 'error': str(error), 'worldWeatherVerified': False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.report, report)
    print(('PASS' if report['passed'] else 'FAIL') + ': ' + str(args.report), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
