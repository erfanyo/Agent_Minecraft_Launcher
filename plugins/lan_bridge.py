# -*- coding: utf-8 -*-
"""EasyTier 命令行桥接（可选插件）。

插件可按用户请求下载官方 easytier-core，或选择已安装的程序。
下载不会自动启动联机，也不把“生成房间名”误报为已经组网。
"""
import os
import random
import shutil
import string
import subprocess
import threading
import time
import base64

PLUGIN_ID = "lan_bridge"
PLUGIN_NAME = "EasyTier兼容"
PLUGIN_DESCRIPTION = "下载或选择 EasyTier 创建联机网络，可与使用 EasyTier 的其他启动器及独立客户端互联。"
PLUGIN_VERSION = "0.3.0"
PLUGIN_API_VERSION = 1
PLUGIN_DEFAULT_ENABLED = False

_configured_core = ""
_process = None
_elevated_pid = None
_process_lock = threading.Lock()
_download_lock = threading.Lock()
_session = None


def _parse_virtual_ip(output):
    """Read only the labelled local Virtual IP row, never public/peer addresses."""
    import re
    import ipaddress
    for line in output.splitlines():
        match = re.search(r'\bVirtual IP\s*[|│]\s*([0-9.]+(?:/\d+)?)', line)
        if match:
            try:
                ip = ipaddress.IPv4Interface(match[1]).ip
                if not ip.is_unspecified and not ip.is_loopback and not ip.is_multicast:
                    return str(ip)
            except ValueError:
                pass
    return ''


def read_virtual_ip(session=None):
    session = session or _session
    if session is None:
        return {'token': None, 'ip': '', 'message': '尚未启动房间'}
    if not _is_running():
        return {'token': session['token'], 'ip': '', 'message': 'EasyTier 已退出'}
    if not os.path.isfile(session['cli']):
        return {'token': session['token'], 'ip': '', 'message': '缺少同目录 easytier-cli，请自动下载完整程序包'}
    ok, output = _run([session['cli'], '--rpc-portal', session['rpc'], 'node', 'info'], timeout=3)
    ip = _parse_virtual_ip(output) if ok else ''
    return {'token': session['token'], 'ip': ip,
            'message': ('本机虚拟 IP 已就绪；尚未验证与好友连通' if ip else
                        '暂未获得虚拟 IP，请检查虚拟网卡或管理员授权' if ok else
                        '暂时无法查询本机状态，将自动重试；请确认 CLI 与核心版本一致')}


def _parse_network_devices(output):
    """Parse CLI JSON, not the truncated human-readable table."""
    import json
    rows = json.loads(output)
    if not isinstance(rows, list):
        raise ValueError('Unexpected peer list')
    devices = []
    for row in rows:
        if not isinstance(row, dict) or not {'hostname', 'cost'}.issubset(row):
            raise ValueError('Unexpected peer row')
        cost = str(row['cost'])
        kind = {'local': '本机', 'p2p': '直连', 'direct': '直连'}.get(cost.lower())
        if kind is None:
            kind = '中转' if cost.lower().startswith('relay') else cost or '未知'
        devices.append((str(row['hostname']) or '未命名设备',
                        str(row.get('ipv4') or row.get('cidr') or '未分配'),
                        kind, str(row.get('lat_ms') or '—')))
    return devices


def read_network_devices(session=None):
    session = session or _session
    result = {'token': session['token'] if session else None, 'devices': []}
    if session is None or not _is_running():
        return dict(result, message='房间未运行')
    if not os.path.isfile(session['cli']):
        return dict(result, message='缺少 easytier-cli，请自动下载完整程序包')
    ok, output = _run([session['cli'], '--rpc-portal', session['rpc'],
                       '-o', 'json', 'peer', 'list'], timeout=3)
    if not ok:
        return dict(result, message='设备列表暂时没读到，可以点“立即刷新”再试试。')
    try:
        devices = _parse_network_devices(output)
    except (ValueError, TypeError):
        return dict(result, message='无法识别设备列表，请确认 CLI 与核心版本一致。')
    return dict(result, devices=devices, message=(
        f'已更新 · {len(devices)} 个设备（含本机，如已就绪）' if devices else '查询成功，暂未发现设备'))


def _select_download_asset(release, system, machine):
    """Only official core ZIPs, never GUI installers or executables from arbitrary URLs."""
    import re
    os_name = {'Windows': 'windows', 'Linux': 'linux', 'Darwin': 'macos'}.get(system)
    arch = {'amd64': 'x86_64', 'x86_64': 'x86_64', 'arm64': 'aarch64', 'aarch64': 'aarch64'}.get(machine.lower())
    if system == 'Windows':
        arch = 'arm64' if arch == 'aarch64' else 'i686' if machine.lower() in {'x86', 'i386', 'i686'} else arch
    if not os_name or not arch:
        raise ValueError('暂不支持此系统自动下载，请手动选择程序。')
    for asset in release.get('assets', []):
        name = asset.get('name', '')
        if re.fullmatch(r'easytier-' + os_name + '-' + arch + r'-v[0-9][A-Za-z0-9._-]*\.zip', name):
            url = asset.get('browser_download_url', '')
            digest = asset.get('digest', '') or ''
            if not url.startswith('https://github.com/EasyTier/EasyTier/releases/download/'):
                raise ValueError('下载地址不是 EasyTier 官方发布地址。')
            if not re.fullmatch(r'sha256:[a-fA-F0-9]{64}', digest):
                raise ValueError('官方发布信息缺少 SHA-256，已停止自动下载；可前往官方页面核对后手动安装。')
            return asset
    raise ValueError('官方发布中没有匹配此系统的核心程序，请手动选择。')


def _extract_core(archive_path, destination, executable):
    import zipfile
    import stat
    from pathlib import PurePosixPath
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > 3000 or sum(m.file_size for m in members) > 600 * 1024 * 1024:
            raise ValueError('压缩包展开大小异常，已停止。')
        for member in members:
            path = PurePosixPath(member.filename.replace('\\', '/'))
            if path.is_absolute() or '..' in path.parts or ':' in str(path) or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError('压缩包含不安全路径，已停止。')
        archive.extractall(destination)
    matches = []
    for root, dirs, files in os.walk(destination):
        if executable in files:
            matches.append(os.path.join(root, executable))
    if len(matches) != 1:
        raise ValueError('下载包中未找到唯一的 EasyTier 核心程序。')
    if os.name != 'nt':
        os.chmod(matches[0], 0o755)
        cli = os.path.join(os.path.dirname(matches[0]), 'easytier-cli')
        if os.path.isfile(cli):
            os.chmod(cli, 0o755)
    return matches[0]


def download_core(destination, report=lambda message: None):
    import hashlib
    import json
    import platform
    import tempfile
    import urllib.request
    if not _download_lock.acquire(blocking=False):
        raise ValueError('另一页已经在下载 EasyTier，请稍等。')
    try:
        def request(url):
            return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'AMCL-EasyTier', 'Accept': 'application/vnd.github+json'}), timeout=30)
        report('正在读取 EasyTier 官方发布信息…')
        with request('https://api.github.com/repos/EasyTier/EasyTier/releases/latest') as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError('发布信息大小异常。')
            release = json.loads(raw)
        asset = _select_download_asset(release, platform.system(), platform.machine())
        os.makedirs(destination, exist_ok=True)
        # TemporaryDirectory only cleans this invocation's private staging folder.
        with tempfile.TemporaryDirectory(prefix='.download-', dir=destination) as stage:
            archive_path = os.path.join(stage, 'core.zip')
            digest = hashlib.sha256()
            done = 0
            with request(asset['browser_download_url']) as response, open(archive_path, 'wb') as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > 250 * 1024 * 1024:
                        raise ValueError('下载包过大，已停止。')
                    output.write(chunk)
                    digest.update(chunk)
                    report(f'正在下载 EasyTier… {done // (1024 * 1024)} MB')
            if digest.hexdigest() != asset['digest'].split(':', 1)[1].lower():
                raise ValueError('SHA-256 校验失败，请重试下载。')
            if asset.get('size') and done != asset['size']:
                raise ValueError('下载不完整，请重试。')
            report('校验通过，正在解压…')
            unpacked = os.path.join(stage, 'unpacked')
            os.mkdir(unpacked)
            core = _extract_core(archive_path, unpacked, 'easytier-core.exe' if platform.system() == 'Windows' else 'easytier-core')
            relative = os.path.relpath(core, unpacked)
            # A unique directory preserves existing/custom installations and running binaries.
            import uuid
            final = os.path.join(destination, asset['name'][:-4] + '-' + uuid.uuid4().hex[:8])
            os.rename(unpacked, final)
            return os.path.join(final, relative)
    finally:
        _download_lock.release()
# 取自 EasyTier 官方 README 的共享节点示例；后续可扩展为用户自建节点。
_shared_peer = "tcp://public.easytier.cn:11010"


def _find_core() -> str:
    if _configured_core and os.path.isfile(_configured_core):
        return _configured_core
    for name in ("easytier-core", "easytier-core.exe"):
        found = shutil.which(name)
        if found:
            return found
    for path in (
        "C:/Program Files/EasyTier/easytier-core.exe",
        "C:/EasyTier/easytier-core.exe",
        os.path.expanduser("~/.local/bin/easytier-core"),
    ):
        if os.path.isfile(path):
            return path
    return ""


def detect(kind: str = "easytier") -> dict:
    """检测支持的 CLI；ZeroTier 保留为检测项，组网入口当前只实现 EasyTier。"""
    kind = (kind or "easytier").lower()
    if kind == "easytier":
        path = _find_core()
    elif kind == "zerotier":
        path = shutil.which("zerotier-cli") or shutil.which("zerotier-cli.bat") or ""
    else:
        path = ""
    return {"installed": bool(path), "path": path}


def _run(command, timeout=10):
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                                creationflags=flags)
        return result.returncode == 0, (result.stdout or result.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def _is_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_elevated(file_path: str, arguments: list[str]) -> int | None:
    """经 UAC 启动程序，并返回子进程 PID；用户拒绝 UAC 时返回 None。"""
    ps_args = ", ".join(_ps_quote(arg) for arg in arguments)
    script = (
        f"$p = Start-Process -FilePath {_ps_quote(file_path)} "
        f"-ArgumentList @({ps_args}) -Verb RunAs -WindowStyle Hidden -PassThru; $p.Id"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return int((result.stdout or "").strip()) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _elevated_stop(pid: int) -> bool:
    script = (
        "$p = Start-Process -FilePath 'taskkill.exe' "
        f"-ArgumentList @('/PID', '{int(pid)}', '/T', '/F') "
        "-Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit $p.ExitCode"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            timeout=20, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _elevated_process_exists(pid: int | None) -> bool:
    if not pid or os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode == 0 and f'"{pid}"' in (result.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return False


def _is_running() -> bool:
    global _elevated_pid
    if _process is not None and _process.poll() is None:
        return True
    if _elevated_process_exists(_elevated_pid):
        return True
    _elevated_pid = None
    return False


def easytier_status() -> dict:
    item = detect("easytier")
    with _process_lock:
        running = _is_running()
    return {**item, "running": running}


def setup_easytier(room_name: str, secret: str) -> dict:
    """启动 EasyTier 核心进程；成功只代表本机进程已运行，不承诺已与好友连通。"""
    global _process, _elevated_pid, _session
    room_name, secret = str(room_name or "").strip(), str(secret or "").strip()
    if not room_name or not secret:
        return {"ok": False, "error": "房间名和密钥不能为空"}
    if any(char.isspace() for char in room_name + secret):
        return {"ok": False, "error": "房间名和密钥不能含空白字符"}
    core = _find_core()
    if not core:
        return {"ok": False, "error": "未找到 easytier-core；请在插件设置中选择它的程序文件"}
    ok, _ = _run([core, "--version"])
    if not ok:
        return {"ok": False, "error": "easytier-core 无法执行"}
    with _process_lock:
        if _is_running():
            return {"ok": False, "error": "EasyTier 已在运行，请先停止当前房间"}
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        # 不使用 --no-tun：Minecraft 的直接连接需要可路由到虚拟 IP 的系统网卡。
        import socket
        import uuid
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            rpc = f'127.0.0.1:{probe.getsockname()[1]}'
        _session = None
        arguments = ["--network-name", room_name, "--network-secret", secret,
                     "--dhcp", "true", "--rpc-portal", rpc, "-p", _shared_peer]
        if os.name == "nt" and not _is_admin():
            _elevated_pid = _run_elevated(core, arguments)
            _process = None
            if not _elevated_pid:
                return {"ok": False, "error": "未获得管理员授权；创建虚拟网卡需要在 UAC 弹窗中确认"}
        else:
            _process = subprocess.Popen(
                [core, *arguments], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
            _elevated_pid = None
    time.sleep(0.35)
    if not _is_running():
        return {"ok": False, "error": "EasyTier 启动后立即退出；请检查管理员权限、虚拟网卡和程序版本"}
    _session = {'token': uuid.uuid4().hex, 'rpc': rpc,
                'cli': os.path.join(os.path.dirname(core), 'easytier-cli.exe' if os.name == 'nt' else 'easytier-cli')}
    return {
        "ok": True,
        "room_key": f"{room_name} / {secret}",
        "virtual_ip": "正在查询本机虚拟 IP…",
        "note": f"本机 EasyTier 已启动，使用共享节点 {_shared_peer}",
    }


def stop_easytier() -> bool:
    global _process, _elevated_pid, _session
    with _process_lock:
        if _process is not None and _process.poll() is None:
            _process.terminate()
            try:
                _process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                _process.kill()
        if _elevated_pid is not None and not _elevated_stop(_elevated_pid):
            # 由普通启动器拉起的管理员进程，需要再次经 UAC 停止。
            return False
        _process = None
        _elevated_pid = None
        _session = None
    return True


def register(api):
    global _configured_core
    _configured_core = str(api.get_config("easytier_core", "") or "")

    def lan_status(args: dict):
        kind = (args or {}).get("kind", "easytier")
        item = detect(kind)
        suffix = "，运行中" if kind == "easytier" and easytier_status()["running"] else ""
        return ("✅ 已装 " if item["installed"] else "❌ 未装 ") + f"{kind}:{item['path'] or '未找到'}{suffix}"

    def lan_setup(args: dict):
        result = setup_easytier((args or {}).get("room_name", "AMCL-room"), (args or {}).get("secret", ""))
        if result.get("ok"):
            # 保留旧 UI 适配器识别的前缀。
            return f"房间已生成并启动:{result['room_key']} 虚拟IP:{result['virtual_ip']}"
        return f"失败:{result.get('error', '')}"

    api.register_tool(
        name="lan_status", description="检测 EasyTier 或 ZeroTier 命令行工具是否已安装。",
        parameters={"type": "object", "properties": {"kind": {"type": "string", "description": "easytier / zerotier"}}},
        handler=lan_status,
    )
    api.register_tool(
        name="lan_setup", description="启动本机 EasyTier 虚拟局域网房间，返回需分享的房间名与密钥。",
        parameters={"type": "object", "properties": {"room_name": {"type": "string"}, "secret": {"type": "string"}}, "required": ["secret"]},
        handler=lan_setup, write=True, confirm=True,
    )

    def build_settings_page():
        from PySide6.QtCore import QTimer, QObject, Signal, Qt
        from PySide6.QtWidgets import QApplication, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView

        page = QWidget()
        page.setObjectName('easyTierSettingsPage')
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        page.setStyleSheet('QWidget#easyTierSettingsPage { background: transparent; }')
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(QLabel("EasyTier兼容"))
        info = QLabel("可自动下载官方核心到 AMCL 文件夹，或选择已有程序。下载不会启动联机；启动/停止时可能弹出 UAC 授权，停止只影响本插件启动的进程。")
        info.setWordWrap(True)
        layout.addWidget(info)
        compatibility = QLabel(
            "朋友不用换启动器：支持与使用 EasyTier 的其他启动器、独立 EasyTier 客户端联机。"
            "双方使用相同的网络名称（这里的房间名）和密钥，并确保 EasyTier 版本、网络配置兼容且节点可达。"
            "组网后，在 Minecraft 中连接房主的虚拟 IP 和游戏端口；游戏版本及 Mod 也要匹配。")
        compatibility.setWordWrap(True)
        layout.addWidget(compatibility)
        path_row = QHBoxLayout()
        core_path = QLineEdit(_configured_core)
        core_path.setPlaceholderText("easytier-core.exe 路径（留空则自动检测）")
        choose = QPushButton("选择程序")
        download = QPushButton("自动下载 EasyTier")
        path_row.addWidget(core_path, 1); path_row.addWidget(choose); path_row.addWidget(download)
        layout.addLayout(path_row)
        status = QLabel("检测中…")
        status.setWordWrap(True)
        layout.addWidget(status)
        class DownloadSignals(QObject):
            progress = Signal(str)
            done = Signal(str)
            error = Signal(str)
            node = Signal(object)
        signals = DownloadSignals(page)
        page._download_signals = signals

        def download_done(path):
            global _configured_core
            _configured_core = path
            core_path.setText(path)
            api.set_config('easytier_core', path)
            download.setEnabled(True)
            choose.setEnabled(True)
            status.setText('下载完成，SHA-256 校验通过；程序路径已保存。点击“启动房间”才会联机。')

        def download_error(message):
            download.setEnabled(True)
            choose.setEnabled(True)
            status.setText('下载失败：' + message + '\n可以重试；若 GitHub 连不上，换个网络或手动选择程序。')

        signals.progress.connect(status.setText)
        signals.done.connect(download_done)
        signals.error.connect(download_error)

        def start_download():
            destination = api.data_path('easytier')
            download.setEnabled(False)
            choose.setEnabled(False)
            def emit(signal, message):
                try:
                    signal.emit(message)
                except RuntimeError:
                    pass
            def work():
                try:
                    path = download_core(destination, lambda msg: emit(signals.progress, msg))
                    emit(signals.done, path)
                except Exception as exc:
                    emit(signals.error, str(exc))
            threading.Thread(target=work, daemon=True).start()
        download.clicked.connect(start_download)
        button_row = QHBoxLayout()
        start = QPushButton("启动房间")
        stop = QPushButton("停止房间")
        button_row.addWidget(start); button_row.addWidget(stop); button_row.addStretch()
        layout.addLayout(button_row)
        room_name, room_secret, virtual_ip = QLineEdit(), QLineEdit(), QLineEdit()
        room_fields = QFormLayout()
        room_fields.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        for title, control in (("房间名：", room_name), ("密钥：", room_secret), ("虚拟 IP：", virtual_ip)):
            control.setReadOnly(True)
            control.setPlaceholderText("启动房间后显示")
            field_row = QWidget()
            field_layout = QHBoxLayout(field_row)
            field_layout.setContentsMargins(0, 0, 0, 0)
            copy = QPushButton("复制")
            copy.setEnabled(False)
            def can_copy(value, is_ip=control is virtual_ip):
                if not is_ip:
                    return bool(value.strip())
                import ipaddress
                try:
                    ipaddress.ip_address(value.strip())
                    return True
                except ValueError:
                    return False
            control.textChanged.connect(lambda value, button=copy, validate=can_copy: button.setEnabled(validate(value)))
            copy.clicked.connect(lambda checked=False, field=control: QApplication.clipboard().setText(field.text()))
            field_layout.addWidget(control, 1)
            field_layout.addWidget(copy)
            room_fields.addRow(title, field_row)
        room_secret.setProperty("ai_pin_sensitive", True)
        layout.addLayout(room_fields)
        ip_status = QLabel('本机地址尚未就绪；好友连通状态需另外确认。')
        ip_status.setWordWrap(True)
        layout.addWidget(ip_status)
        peers_header = QHBoxLayout()
        peers_header.addWidget(QLabel('网络中的设备'))
        peers_header.addStretch()
        refresh_peers = QPushButton('立即刷新')
        peers_header.addWidget(refresh_peers)
        layout.addLayout(peers_header)
        peers_hint = QLabel('每 5 秒自动刷新。这是 EasyTier 网络设备，不是 Minecraft 在线玩家。')
        peers_hint.setWordWrap(True)
        layout.addWidget(peers_hint)
        peers = QTableWidget(0, 4)
        peers.setHorizontalHeaderLabels(['设备名', '虚拟 IP', '连接方式', '延迟（ms）'])
        peers.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        peers.verticalHeader().hide()
        peers.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        peers.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        peers.setMinimumHeight(150)
        layout.addWidget(peers)
        peers_status = QLabel('尚未启动房间')
        peers_status.setWordWrap(True)
        layout.addWidget(peers_status)
        polling = {'busy': False}
        def node_ready(result):
            polling['busy'] = False
            refresh_peers.setEnabled(True)
            current_token = _session['token'] if _session else None
            if result.get('token') != current_token:
                return
            virtual_ip.setText(result.get('ip') or '')
            virtual_ip.setPlaceholderText('暂未获取')
            ip_status.setText(result['message'])
            network = result.get('network', {})
            devices = network.get('devices', [])
            peers.setRowCount(len(devices))
            for row, device in enumerate(devices):
                for col, value in enumerate(device):
                    item = QTableWidgetItem(value)
                    item.setToolTip(value)
                    peers.setItem(row, col, item)
            peers_status.setText(network.get('message', '设备列表读取失败'))
        signals.node.connect(node_ready)
        def poll_ip():
            if polling['busy'] or not page.isVisible():
                return
            if _session is None:
                virtual_ip.clear()
                ip_status.setText('尚未启动房间')
                peers.setRowCount(0)
                peers_status.setText('尚未启动房间')
                return
            polling['busy'] = True
            refresh_peers.setEnabled(False)
            peers_status.setText('正在刷新…')
            session = _session
            def work():
                try:
                    result = read_virtual_ip(session)
                    result['network'] = read_network_devices(session)
                except Exception:
                    result = {'token': session['token'], 'ip': '', 'message': '本机状态读取失败'}
                try:
                    signals.node.emit(result)
                except RuntimeError:
                    pass
            threading.Thread(target=work, daemon=True).start()
        poll_timer = QTimer(page)
        poll_timer.setInterval(5000)
        poll_timer.timeout.connect(poll_ip)
        poll_timer.start()
        refresh_peers.clicked.connect(poll_ip)
        copy_room = QPushButton("一键复制房间信息")
        copy_room.setToolTip("复制房间名和密钥，请只分享给要一起联机的朋友。")
        copy_room.setEnabled(False)
        def update_copy_room():
            copy_room.setEnabled(bool(room_name.text() and room_secret.text()))
        room_name.textChanged.connect(update_copy_room)
        room_secret.textChanged.connect(update_copy_room)
        copy_room.clicked.connect(lambda: QApplication.clipboard().setText(
            f"房间名：{room_name.text()}\n密钥：{room_secret.text()}"))
        layout.addWidget(copy_room)

        def refresh():
            current = easytier_status()
            if current["installed"]:
                status.setText(f"EasyTier: ✅ 已找到 {current['path']}" + ("（运行中）" if current["running"] else ""))
            else:
                status.setText("EasyTier: ❌ 未找到；请自行下载 easytier-core 后在上方选择程序")

        def choose_core():
            global _configured_core
            selected, _ = QFileDialog.getOpenFileName(page, "选择 easytier-core", core_path.text(), "程序 (*.exe);;所有文件 (*)")
            if selected:
                _configured_core = selected
                core_path.setText(selected)
                api.set_config("easytier_core", selected)
                refresh()

        def start_room():
            room = "AMCL-" + "".join(random.choices(string.ascii_lowercase, k=5))
            secret = "".join(random.choices(string.ascii_letters + string.digits, k=12))
            result = setup_easytier(room, secret)
            if result.get("ok"):
                room_name.setText(room)
                room_secret.setText(secret)
                virtual_ip.setText(result["virtual_ip"])
                status.setText("✅ 本机进程已启动，正在查询虚拟 IP；这不代表已与好友连通。")
                poll_ip()
            else:
                status.setText("❌ " + result.get("error", "启动失败"))

        def stop_room():
            if stop_easytier():
                room_name.clear()
                room_secret.clear()
                virtual_ip.clear()
                peers.setRowCount(0)
                peers_status.setText('房间已停止')
                status.setText("已停止本插件启动的 EasyTier 房间。")
            else:
                status.setText("❌ 未能停止 EasyTier；请在 UAC 弹窗中允许操作后重试。")

        choose.clicked.connect(choose_core)
        start.clicked.connect(start_room)
        stop.clicked.connect(stop_room)
        QTimer.singleShot(0, refresh)
        layout.addStretch()
        return page

    api.register_settings_page(build_settings_page)
    if hasattr(api, 'register_center_page'):
        api.register_center_page('online', 'settings', 'EasyTier 设置', build_settings_page)
