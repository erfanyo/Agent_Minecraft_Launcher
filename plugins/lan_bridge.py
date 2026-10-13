# -*- coding: utf-8 -*-
"""EasyTier 与 Terracotta 联机桥接（可选插件）。

插件可下载官方 EasyTier / Terracotta 程序，或选择已安装的程序。
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
from ui_feedback import copy_with_feedback

PLUGIN_ID = "lan_bridge"
PLUGIN_NAME = "联机"
PLUGIN_DESCRIPTION = "启用后自动下载陶瓦和 EasyTier；可用陶瓦大厅编号或虚拟局域网跨启动器联机。"
PLUGIN_VERSION = "0.5.0"
PLUGIN_API_VERSION = 1
PLUGIN_DEFAULT_ENABLED = False

_configured_core = ""
_process = None
_elevated_pid = None
_process_lock = threading.Lock()
_download_lock = threading.Lock()
_session = None
_terracotta_path = ""
_terracotta_port = None
_terracotta_process = None
_terracotta_lock = threading.RLock()
_terracotta_download_lock = threading.Lock()
_install_state = {'terracotta': '', 'easytier': ''}

# Additional nodes are passed to Terracotta's embedded EasyTier via its IPC.
TERRACOTTA_PUBLIC_NODES = (
    'tcp://us01.225284.xyz:11010',
    'tcp://dreamlife.indevs.in:11010',
)


def _save_join_address_to_selected_instance(page, address):
    """Store a guest endpoint in the active Minecraft instance server list."""
    from minecraft_servers import add_server
    window = page.window()
    while window is not None and not hasattr(window, 'home_panel'):
        window = window.parentWidget()
    if window is None:
        return '选择一个游戏实例后，可把地址加入它的多人游戏列表。'
    home = getattr(window, 'home_panel', None)
    inst = getattr(page, '_terracotta_instance', None)
    if inst is None:
        inst = home.current_instance() if home is not None else None
    if not inst or not inst.get('id'):
        return '选择一个游戏实例后，可把地址加入它的多人游戏列表。'
    game_dir = inst.get('game_dir') or window.game_dir_for(inst['id'])
    added = add_server(game_dir, 'Terracotta 大厅', address)
    return ('已加入当前实例的多人游戏列表；若游戏已打开，请重新进入多人游戏页面。'
            if added else '当前实例的多人游戏列表已有此地址。')


def _terracotta_request(route, params=None):
    global _terracotta_port
    import json
    import urllib.parse
    import urllib.request
    with _terracotta_lock:
        port = _terracotta_port
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise RuntimeError('Terracotta 尚未连接')
    query = '?' + urllib.parse.urlencode(params, doseq=True) if params else ''
    url = f'http://127.0.0.1:{port}/state/{route}{query}'
    try:
        with urllib.request.urlopen(url, timeout=4) as response:
            body = response.read(256 * 1024 + 1)
            if len(body) > 256 * 1024:
                raise ValueError('Terracotta 状态数据过大')
            return json.loads(body) if route == '' else None
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, ConnectionRefusedError) or getattr(reason, 'winerror', None) == 10061:
            with _terracotta_lock:
                if _terracotta_port == port:
                    _terracotta_port = None
            code = _terracotta_process.poll() if _terracotta_process is not None else None
            suffix = f'（进程退出码 {code}）' if code is not None else ''
            raise RuntimeError(f'本机陶瓦接口已关闭{suffix}。请查看陶瓦启动日志；这不是房主游戏端口拒绝连接。') from error
        raise


def terracotta_connect(path):
    """Use Terracotta's documented HMCL IPC mode, including its existing-instance path."""
    import json
    import tempfile
    path = os.path.abspath(os.path.expanduser(str(path or '').strip()))
    if not os.path.isfile(path):
        raise ValueError('请先选择 Terracotta 官方程序')
    global _terracotta_port, _terracotta_process
    with _terracotta_lock:
        if _terracotta_port:
            try:
                _terracotta_request('')
                return
            except Exception:
                _terracotta_port = None
        with tempfile.TemporaryDirectory(prefix='amcl-terracotta-') as temporary:
            port_file = os.path.join(temporary, 'port.json')
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            startup_log = os.path.join(os.path.dirname(path), 'amcl-terracotta-startup.log')
            with open(startup_log, 'ab') as output:
                # Official Windows 0.4.2 delegates --hmcl to --hmcl2 and exits.
                # Start that documented-in-source server entry directly so its
                # actual lifetime and exit code remain observable by AMCL.
                mode = '--hmcl2' if os.name == 'nt' else '--hmcl'
                process = subprocess.Popen([path, mode, port_file],
                                           stdout=output, stderr=subprocess.STDOUT,
                                           cwd=os.path.dirname(path), creationflags=flags)
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if os.path.isfile(port_file):
                    with open(port_file, 'r', encoding='utf-8') as stream:
                        port = json.load(stream).get('port')
                    if not isinstance(port, int) or not 1 <= port <= 65535:
                        raise ValueError('Terracotta 返回了无效的本地端口')
                    _terracotta_port = port
                    _terracotta_process = process if process.poll() is None else None
                    _terracotta_request('')
                    return
                if process.poll() is not None and os.name != 'nt':
                    break
                time.sleep(0.1)
        raise RuntimeError(f'Terracotta 未能启动（退出码 {process.poll()}）；启动日志：{startup_log}')


def terracotta_state():
    return _terracotta_request('')


def terracotta_host(player='', public_nodes=None):
    params = {'public_nodes': list(TERRACOTTA_PUBLIC_NODES if public_nodes is None else public_nodes)}
    if player:
        params['player'] = player
    _terracotta_request('scanning', params)


def terracotta_join(room, player='', public_nodes=None):
    room = str(room or '').strip()
    if not room or len(room) > 256:
        raise ValueError('请输入有效的 Terracotta 大厅编号')
    _terracotta_request('guesting', {'room': room, 'public_nodes': list(TERRACOTTA_PUBLIC_NODES if public_nodes is None else public_nodes), **({'player': player} if player else {})})


def terracotta_leave():
    _terracotta_request('ide')


def download_terracotta(destination, report=lambda message: None):
    global _terracotta_path
    _terracotta_download_lock.acquire()
    try:
        if _terracotta_path and os.path.isfile(_terracotta_path):
            return _terracotta_path
        _terracotta_path = _download_terracotta(destination, report)
        return _terracotta_path
    finally:
        _terracotta_download_lock.release()


def _download_terracotta(destination, report):
    """Install the unmodified official binary from a verified GitHub release asset."""
    import hashlib
    import json
    import platform
    import re
    import tarfile
    import tempfile
    import urllib.request
    import uuid

    system = {'Windows': 'windows', 'Linux': 'linux'}.get(platform.system())
    machine = {'amd64': 'x86_64', 'x86_64': 'x86_64',
               'arm64': 'arm64', 'aarch64': 'arm64'}.get(platform.machine().lower())
    if not system or not machine:
        raise ValueError('此平台暂不支持插件内下载；请从官方发布页下载并选择程序。')

    def request(url):
        return urllib.request.urlopen(urllib.request.Request(
            url, headers={'User-Agent': 'AMCL-Terracotta',
                          'Accept': 'application/vnd.github+json'}), timeout=30)

    report('正在读取 Terracotta 官方发布信息…')
    with request('https://api.github.com/repos/burningtnt/Terracotta/releases/latest') as response:
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('发布信息大小异常。')
    release = json.loads(raw)
    version = str(release.get('tag_name') or '').removeprefix('v')
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9]+)*', version):
        raise ValueError('官方发布版本号无法识别。')
    name = f'terracotta-{version}-{system}-{machine}-pkg.tar.gz'
    asset = next((item for item in release.get('assets', []) if item.get('name') == name), None)
    if asset is None:
        raise ValueError('官方发布中没有匹配本机的程序包。')
    url = str(asset.get('browser_download_url') or '')
    digest = str(asset.get('digest') or '')
    expected_url = f'https://github.com/burningtnt/Terracotta/releases/download/{release["tag_name"]}/{name}'
    if url != expected_url or not re.fullmatch(r'sha256:[a-fA-F0-9]{64}', digest):
        raise ValueError('官方发布信息缺少可验证的下载地址或 SHA-256。')
    if not isinstance(asset.get('size'), int) or not 0 < asset['size'] <= 100 * 1024 * 1024:
        raise ValueError('程序包大小异常。')

    os.makedirs(destination, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.terracotta-download-', dir=destination) as stage:
        archive_path = os.path.join(stage, 'package.tar.gz')
        calculated = hashlib.sha256()
        done = 0
        with request(url) as response, open(archive_path, 'wb') as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                done += len(chunk)
                if done > 100 * 1024 * 1024:
                    raise ValueError('下载包过大，已停止。')
                output.write(chunk)
                calculated.update(chunk)
                report(f'正在下载 Terracotta… {done // (1024 * 1024)} MB')
        if done != asset['size'] or calculated.hexdigest() != digest.split(':', 1)[1].lower():
            raise ValueError('Terracotta 下载不完整或 SHA-256 校验失败。')
        report('校验通过，正在提取程序…')
        executable = 'terracotta.exe' if system == 'windows' else 'terracotta'
        versioned_executable = f'terracotta-{version}-{system}-{machine}' + ('.exe' if system == 'windows' else '')
        with tarfile.open(archive_path, 'r:gz') as archive:
            matches = [member for member in archive.getmembers()
                       if member.isfile() and member.name.replace('\\', '/').rsplit('/', 1)[-1].lower()
                       in (executable, versioned_executable)]
            if len(matches) != 1 or matches[0].size > 100 * 1024 * 1024:
                raise ValueError('程序包中未找到唯一的 Terracotta 可执行文件。')
            source = archive.extractfile(matches[0])
            if source is None:
                raise ValueError('无法读取 Terracotta 可执行文件。')
            staged_binary = os.path.join(stage, executable)
            with source, open(staged_binary, 'wb') as output:
                shutil.copyfileobj(source, output)
            # 官方 Windows 包携带 VC 运行库，必须与 EXE 放在同一目录。
            libraries = []
            if system == 'windows':
                binary_dir = matches[0].name.replace('\\', '/').rpartition('/')[0]
                for member in archive.getmembers():
                    parent, _, filename = member.name.replace('\\', '/').rpartition('/')
                    if (not member.isfile() or parent != binary_dir
                            or not re.fullmatch(r'[A-Za-z0-9_.-]+\.dll', filename, re.IGNORECASE)):
                        continue
                    if not 0 < member.size <= 100 * 1024 * 1024:
                        raise ValueError('程序包中的运行库大小异常。')
                    if filename.lower() in {name.lower() for name in libraries}:
                        raise ValueError('程序包包含重名运行库。')
                    library = archive.extractfile(member)
                    if library is None:
                        raise ValueError('无法读取 Terracotta 运行库。')
                    with library, open(os.path.join(stage, filename), 'wb') as output:
                        shutil.copyfileobj(library, output)
                    libraries.append(filename)
        if system != 'windows':
            os.chmod(staged_binary, 0o755)
        final = os.path.join(destination, f'{version}-{system}-{machine}-{uuid.uuid4().hex[:8]}')
        os.mkdir(final)
        final_binary = os.path.join(final, executable)
        os.replace(staged_binary, final_binary)
        for filename in libraries:
            os.replace(os.path.join(stage, filename), os.path.join(final, filename))
        return final_binary


def _add_terracotta_ui(layout, page, api):
    from PySide6.QtCore import Qt, QTimer, QObject, Signal
    from PySide6.QtWidgets import (QApplication, QFileDialog, QMessageBox, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QPushButton, QWidget, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QComboBox, QListWidget, QListWidgetItem)
    from ui_style import set_style, panel_style, card_btn_style, muted_color

    layout.addWidget(QLabel('Terracotta · 跨启动器大厅编号'))
    info = QLabel('房主先在游戏中开放局域网，再创建大厅。访客输入大厅编号，连接成功后会把本机地址加入当前实例的多人游戏列表。陶瓦自带 EasyTier 核心，无需在 EasyTier 页面另建网络。')
    info.setWordWrap(True)
    layout.addWidget(info)
    credit = QLabel('Terracotta © burningtnt · AGPL-3.0-or-later · <a href="https://github.com/burningtnt/Terracotta">项目主页 / 查看源码</a>')
    credit.setOpenExternalLinks(True)
    credit.setWordWrap(True)
    layout.addWidget(credit)

    node_row = QHBoxLayout()
    node_row.addWidget(QLabel('公共节点：'))
    node_choice = QComboBox()
    node_presets = [
        ('美国 + 上海（备用节点）', list(TERRACOTTA_PUBLIC_NODES)),
        ('美国', [TERRACOTTA_PUBLIC_NODES[0]]),
        ('上海', [TERRACOTTA_PUBLIC_NODES[1]]),
        ('仅陶瓦原有节点', []),
    ]
    for label, nodes in node_presets:
        node_choice.addItem(label, nodes)
    saved_nodes = api.get_config('terracotta_public_nodes', list(TERRACOTTA_PUBLIC_NODES))
    if isinstance(saved_nodes, list):
        for index, (_, nodes) in enumerate(node_presets):
            if nodes == saved_nodes:
                node_choice.setCurrentIndex(index)
                break
    node_choice.currentIndexChanged.connect(lambda: api.set_config('terracotta_public_nodes', node_choice.currentData()))
    node_row.addWidget(node_choice, 1)
    layout.addLayout(node_row)
    node_hint = QLabel('房主与访客请选同一组节点；备用节点会补充到陶瓦原有节点中。连接中更改需退出大厅后重新连接。')
    node_hint.setWordWrap(True)
    layout.addWidget(node_hint)

    top = QHBoxLayout()
    top.setSpacing(12)
    layout.addLayout(top)
    room_card, manage_card = QWidget(), QWidget()
    for card in (room_card, manage_card):
        set_style(card, panel_style)
        top.addWidget(card, 1)
    room_layout, manage_layout = QVBoxLayout(room_card), QVBoxLayout(manage_card)
    def section_title(text):
        label = QLabel(text)
        font = label.font()
        font.setPointSizeF(max(12.0, font.pointSizeF() + 2))
        font.setBold(True)
        label.setFont(font)
        return label
    room_layout.addWidget(section_title('大厅信息'))
    instance_row = QHBoxLayout()
    instance_row.addWidget(QLabel('实例：'))
    instance_choice = QComboBox()
    instance_choice.addItem('未检测到已启动实例', None)
    from instances import scan_instances
    instance_metadata = {instance['id']: instance for instance in scan_instances()}
    detected_running = {'ids': set(), 'busy': False}

    def running_owner():
        owner = page.window()
        while owner is not None and not hasattr(owner, '_running_instances'):
            owner = owner.parentWidget()
        return owner

    def refresh_running_instances():
        owner = running_owner()
        running = sorted(set(getattr(owner, '_running_instances', set())) | detected_running['ids'])
        if not instance_choice.isEnabled():
            return running
        previous = instance_choice.currentData()
        previous_id = previous.get('id') if previous else None
        listed = [instance_choice.itemData(index)['id']
                  for index in range(1, instance_choice.count())]
        if listed == running:
            for index in range(1, instance_choice.count()):
                data = instance_choice.itemData(index)
                instance_choice.setItemData(index, instance_metadata.get(data['id'], data))
            return running
        home = getattr(owner, 'home_panel', None)
        selected = home.current_instance() if home is not None else None
        preferred = previous_id if previous_id in running else (
            selected.get('id') if selected and selected.get('id') in running else
            running[0] if len(running) == 1 else None)
        instance_choice.clear()
        instance_choice.addItem('请选择已启动实例' if running else '未检测到已启动实例', None)
        for instance_id in running:
            instance = instance_metadata.get(instance_id, {'id': instance_id})
            instance_choice.addItem(str(instance.get('name') or instance_id), instance)
            if instance_id == preferred:
                instance_choice.setCurrentIndex(instance_choice.count() - 1)
        return running
    instance_row.addWidget(instance_choice, 1)
    room_layout.addLayout(instance_row)
    instance_hint = QLabel('自动检测已启动的本地实例。访客地址写入所选实例；多开时请只对目标实例开放局域网，陶瓦自动扫描端口。')
    instance_hint.setWordWrap(True)
    set_style(instance_hint, lambda: f'color: {muted_color()}; font-size: 11px;')
    room_layout.addWidget(instance_hint)
    port_status = QLabel('局域网端口：正在检测…')
    port_status.setWordWrap(True)
    set_style(port_status, lambda: f'color: {muted_color()}; font-size: 11px;')
    room_layout.addWidget(port_status)

    def update_port_status():
        selected = instance_choice.currentData() or {}
        ports = selected.get('lan_ports', [])
        if ports:
            port_status.setText('局域网端口：' + '、'.join(map(str, ports)))
        elif selected.get('port_detection_unavailable'):
            port_status.setText('局域网端口：无法读取进程端口，仍可由陶瓦扫描。')
        else:
            port_status.setText('局域网端口：暂未检测到；已开放时仍可继续创建大厅。')

    instance_choice.currentIndexChanged.connect(update_port_status)
    manage_layout.addWidget(section_title('大厅管理'))
    root = page.window()
    while root is not None and not hasattr(root, 'settings'):
        root = root.parentWidget()
    from settings import load_settings
    current_settings = getattr(root, 'settings', None) or load_settings()
    default_name = str(current_settings.get('username') or 'Player')
    if current_settings.get('login_method') == 'microsoft':
        default_name = str((current_settings.get('ms_credentials') or {}).get('username') or default_name)
    displayed_name = getattr(getattr(root, 'home_panel', None), '_name', '')
    if displayed_name and displayed_name != '未登录正版':
        default_name = str(displayed_name)
    nickname = QLineEdit(str(api.get_config('terracotta_player', default_name) or default_name))
    nickname.setMaxLength(64)
    nickname.setPlaceholderText('大厅昵称（给其他联机成员看）')
    nickname_row = QHBoxLayout()
    nickname_row.addWidget(QLabel('大厅昵称：'))
    nickname_row.addWidget(nickname, 1)
    room_layout.addLayout(nickname_row)
    nickname.editingFinished.connect(lambda: api.set_config('terracotta_player', nickname.text().strip()))
    connection = QLabel('尚未加入大厅')
    connection.setWordWrap(True)
    manage_layout.addWidget(connection)
    log_button = QPushButton('查看陶瓦日志')
    log_button.setEnabled(bool(_terracotta_port))
    def open_log():
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        if _terracotta_port:
            QDesktopServices.openUrl(QUrl(f'http://127.0.0.1:{_terracotta_port}/log?fetch=true'))
    log_button.clicked.connect(open_log)
    path_row = QHBoxLayout()
    path = QLineEdit(_terracotta_path)
    path.setPlaceholderText('选择 Terracotta 官方程序')
    choose = QPushButton('选择程序')
    download = QPushButton('插件内下载')
    path_row.addWidget(path, 1)
    path_row.addWidget(choose)
    path_row.addWidget(download)
    manage_layout.addLayout(path_row)
    for control in (path, choose, download):
        control.hide()
    room_row = QHBoxLayout()
    room = QLineEdit()
    room.setPlaceholderText('访客输入房主分享的大厅编号')
    copy_room = QPushButton('复制大厅编号')
    copy_room.setEnabled(False)
    room_row.addWidget(room, 1)
    room_layout.addLayout(room_row)
    room.hide()
    hall_code = QLineEdit()
    hall_code.setReadOnly(True)
    hall_code.setPlaceholderText('大厅编号')
    hall_code_row = QHBoxLayout()
    hall_code_row.addWidget(hall_code, 1)
    hall_code_row.addWidget(copy_room)
    room_layout.addLayout(hall_code_row)
    hall_code.hide()
    copy_room.hide()
    join_mode = {'value': False}
    disconnect_notice = {'value': ''}
    cancel_join = QPushButton('返回')
    cancel_join.hide()
    buttons = QHBoxLayout()
    host = QPushButton('创建大厅')
    join = QPushButton('加入大厅')
    leave = QPushButton('退出大厅')
    for button in (host, cancel_join, join):
        buttons.addWidget(button)
    manage_layout.addWidget(leave)
    buttons.addStretch()
    room_layout.addLayout(buttons)
    address_row = QHBoxLayout()
    address = QLineEdit()
    address.setReadOnly(True)
    address.setPlaceholderText('加入成功后显示本机游戏地址')
    copy_address = QPushButton('复制地址')
    copy_address.setEnabled(False)
    address_row.addWidget(address, 1)
    address_row.addWidget(copy_address)
    manage_layout.addLayout(address_row)
    status = QLabel(_install_state['terracotta'] or '创建或加入大厅时会自动准备 Terracotta。')
    status.setWordWrap(True)
    manage_layout.addStretch()
    layout.addWidget(status)
    members_title = section_title('大厅成员 · 尚未连接')
    layout.addWidget(members_title)
    members = QListWidget()
    members.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    members.setMinimumHeight(160)
    layout.addWidget(members, 1)
    for control in (host, cancel_join, join, leave, copy_room, copy_address, log_button, choose, download):
        set_style(control, card_btn_style)
    footer = QHBoxLayout()
    footer.addStretch()
    log_button.setFlat(True)
    set_style(log_button, lambda: (
        f'QPushButton {{ color: {muted_color()};'
        ' background: transparent; border: none; font-size: 11px; padding: 3px 5px; }'
        ' QPushButton:hover { text-decoration: underline; }'))
    footer.addWidget(log_button)
    layout.addLayout(footer)

    copy_room.clicked.connect(lambda: copy_with_feedback(copy_room, hall_code.text().strip()))
    copy_address.clicked.connect(lambda: copy_with_feedback(copy_address, address.text().strip()))
    address.textChanged.connect(lambda value: copy_address.setEnabled(bool(value.strip())))

    busy = {'value': False}
    polling = {'value': False}
    saved_address = {'value': ''}
    phase = {'stage': '', 'since': time.monotonic()}
    leave.hide()

    def show_recovery():
        for control in (path, choose, download):
            control.show()

    def hide_recovery():
        for control in (path, choose, download):
            control.hide()
    class Signals(QObject):
        result = Signal(object)
        running_instances = Signal(object)
        polled = Signal(object)
        progress = Signal(str)
        installed = Signal(str)
        auto_installed = Signal(str)
        download_failed = Signal(str)
    signals = Signals(page)
    page._terracotta_signals = signals

    def running_detected(clients):
        detected_running['busy'] = False
        clients = [client for client in clients if client.get('window_visible', True)]
        detected_running['ids'] = {client['id'] for client in clients}
        for client in clients:
            instance_metadata[client['id']] = dict(instance_metadata.get(client['id'], {}), **client)
        refresh_running_instances()
        update_port_status()

    signals.running_instances.connect(running_detected)

    def scan_running_processes():
        owner = running_owner()
        if owner is None or detected_running['busy']:
            return
        current = scan_instances()
        instance_metadata.update({instance['id']: instance for instance in current})
        directories = {instance['id']: owner.game_dir_for(instance['id']) for instance in current}
        detected_running['busy'] = True

        def work():
            from instances import detect_running_clients
            try:
                clients = detect_running_clients(directories, inspect_ports=True)
            except Exception:
                clients = []
            try:
                signals.running_instances.emit(clients)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()

    def show_state(state):
        if not isinstance(state, dict):
            status.setText('Terracotta 返回了无法识别的状态')
            return
        stage = str(state.get('state') or '')
        if stage != phase['stage']:
            phase.update(stage=stage, since=time.monotonic())
        active = stage.startswith(('host-', 'guest-'))
        if active:
            join_mode['value'] = False
            join.setText('加入大厅')
        nickname.setReadOnly(active)
        instance_choice.setEnabled(not active)
        host.setVisible(not active and not join_mode['value'])
        join.setVisible(not active)
        room.setVisible(not active and join_mode['value'])
        cancel_join.setVisible(not active and join_mode['value'])
        hall_code.setVisible(active)
        copy_room.setVisible(active)
        leave.setVisible(active)
        leave.setText('解散大厅' if stage.startswith('host-') else '退出大厅')
        code = str(state.get('room') or '')
        if code:
            hall_code.setText(code)
        elif not active:
            hall_code.clear()
        if stage == 'waiting':
            saved_address['value'] = ''
        profiles = state.get('profiles')
        profiles = [p for p in profiles if isinstance(p, dict)] if isinstance(profiles, list) else []
        previous_scroll = members.verticalScrollBar().value()
        members.clear()
        roles = {'HOST': '房主', 'LOCAL': '本机', 'GUEST': '加入者'}
        for profile in profiles:
            row_widget = QWidget()
            row_layout = QVBoxLayout(row_widget)
            row_layout.setContentsMargins(10, 6, 10, 6)
            row_layout.setSpacing(3)
            name_label = QLabel(str(profile.get('name') or '未命名'))
            name_label.setTextFormat(Qt.TextFormat.PlainText)
            row_layout.addWidget(name_label)
            details = QLabel(f"{roles.get(profile.get('kind'), '成员')} | {profile.get('vendor') or '未知'}")
            details.setTextFormat(Qt.TextFormat.PlainText)
            details.setWordWrap(True)
            set_style(details, lambda: f'color: {muted_color()}; font-size: 11px;')
            row_layout.addWidget(details)
            item = QListWidgetItem()
            item.setSizeHint(row_widget.sizeHint())
            members.addItem(item)
            members.setItemWidget(item, row_widget)
        members.verticalScrollBar().setValue(previous_scroll)
        members_title.setText(f'大厅成员 · {len(profiles)} 人' if profiles else
                              ('大厅成员 · 正在获取信息' if stage.startswith(('host-', 'guest-')) else '大厅成员 · 尚未连接'))
        log_button.setEnabled(bool(_terracotta_port))
        copy_room.setEnabled(stage in ('host-ok', 'guest-ok') and bool(hall_code.text().strip()))
        address.setText(str(state.get('url') or '') if stage == 'guest-ok' else '')
        messages = {
            'waiting': '已就绪，可创建或加入大厅。',
            'host-scanning': '正在查找游戏开放的局域网端口…',
            'host-starting': '已找到游戏，正在建立大厅…',
            'host-ok': '大厅已就绪，请分享大厅编号。',
            'guest-connecting': '正在查找并连接大厅…',
            'guest-starting': '大厅码有效，正在通过陶瓦内置 EasyTier 连接房主…',
            'guest-ok': '已连接；在 Minecraft 多人游戏中连接大厅管理区的地址。',
        }
        message = 'Terracotta：' + messages.get(stage, str(state.get('message') or stage or '未知状态'))
        guest_address = address.text().strip()
        if stage == 'guest-ok' and guest_address and guest_address != saved_address['value']:
            try:
                save_message = _save_join_address_to_selected_instance(page, guest_address)
                message += '\n' + save_message
                if not save_message.startswith('选择一个游戏实例'):
                    saved_address['value'] = guest_address
            except Exception as exc:
                message += f'\n无法写入多人游戏列表：{exc}'
        errors = {0: '无法连接房主，检查房主是否仍在大厅及网络是否可达',
                  1: '房主连接已断开', 2: '陶瓦内置 EasyTier 进程异常退出',
                  3: '房主的陶瓦内置 EasyTier 进程异常退出',
                  4: '游戏局域网服务连接断开，请重新开放局域网',
                  5: '大厅服务返回了无法识别的数据'}
        if stage == 'exception':
            message = '陶瓦连接失败：' + errors.get(state.get('type'), '未知错误，请查看陶瓦日志')
            if state.get('_amcl_left'):
                message += '\n已自动退出大厅，可以重新创建或加入。'
                disconnect_notice['value'] = message
                members_title.setText('大厅成员 · 已退出')
        elif stage == 'waiting' and disconnect_notice['value']:
            message = disconnect_notice['value']
        elapsed = int(time.monotonic() - phase['since'])
        if stage in ('guest-connecting', 'guest-starting', 'host-starting'):
            message += f'（{elapsed} 秒）'
            if elapsed >= 30:
                message += '\n连接耗时较长：请确认房主仍在大厅、已开放局域网，并检查双方防火墙 / 网络限制。'
        difficulty = {'UNKNOWN': '检测中', 'EASIEST': '容易', 'SIMPLE': '较容易', 'MEDIUM': '一般', 'TOUGH': '困难'}
        connection.setText(message + ('\n网络连接难度：' + difficulty.get(state.get('difficulty'), '未知') if 'difficulty' in state else ''))
        status.setText(message)

    def ready(result):
        busy['value'] = False
        for button in (host, join, leave, choose):
            button.setEnabled(True)
        if isinstance(result, Exception):
            status.setText('Terracotta：' + str(result))
            connection.setText('无法读取陶瓦状态：' + str(result))
            members_title.setText('大厅成员 · 状态读取失败')
            if not _terracotta_path or not os.path.isfile(_terracotta_path):
                show_recovery()
        else:
            show_state(result)
    signals.result.connect(ready)
    signals.progress.connect(status.setText)

    def installed(binary):
        global _terracotta_path
        busy['value'] = False
        _terracotta_path = binary
        path.setText(binary)
        api.set_config('terracotta_binary', binary)
        download.setEnabled(True)
        choose.setEnabled(True)
        for button in (host, join, leave):
            button.setEnabled(True)
        status.setText('Terracotta 已下载并通过 SHA-256 校验；可直接创建或加入大厅。')
        hide_recovery()
    signals.installed.connect(installed)

    def auto_installed(binary):
        global _terracotta_path
        _terracotta_path = binary
        path.setText(binary)
        api.set_config('terracotta_binary', binary)
        hide_recovery()
    signals.auto_installed.connect(auto_installed)

    def download_failed(message):
        busy['value'] = False
        download.setEnabled(True)
        choose.setEnabled(True)
        for button in (host, join, leave):
            button.setEnabled(True)
        status.setText('下载失败：' + message)
        show_recovery()
    signals.download_failed.connect(download_failed)

    def start_download():
        if busy['value']:
            return
        busy['value'] = True
        download.setEnabled(False)
        choose.setEnabled(False)
        for button in (host, join, leave):
            button.setEnabled(False)
        destination = api.data_path('terracotta')
        def work():
            try:
                binary = download_terracotta(destination, signals.progress.emit)
                signals.installed.emit(binary)
            except Exception as exc:
                try:
                    signals.download_failed.emit(str(exc))
                except RuntimeError:
                    pass
        threading.Thread(target=work, daemon=True).start()

    def fetch_state():
        state = terracotta_state()
        if isinstance(state, dict) and state.get('state') == 'exception':
            terracotta_leave()
            state = dict(state, _amcl_left=True)
        return state

    def run(action):
        if busy['value']:
            return
        if action == 'host':
            refresh_running_instances()
            selected_instance = instance_choice.currentData()
            if not (selected_instance or {}).get('lan_ports'):
                reminder = QMessageBox(page)
                reminder.setWindowTitle('创建大厅')
                reminder.setText('暂未检测到目标实例的局域网端口；这不代表游戏未启动。')
                reminder.setInformativeText('请先进入世界。Minecraft 26：世界选项 → 局域网 → 开；旧版：Esc → 对局域网开放。已经开放时可继续，由陶瓦扫描动态端口。多开时建议只对目标实例开放。')
                proceed = reminder.addButton('继续创建大厅', QMessageBox.ButtonRole.AcceptRole)
                reminder.addButton('返回', QMessageBox.ButtonRole.RejectRole)
                reminder.exec()
                if reminder.clickedButton() is not proceed:
                    return
        busy['value'] = True
        for button in (host, join, leave, choose):
            button.setEnabled(False)
        disconnect_notice['value'] = ''
        if action != 'poll':
            status.setText('Terracotta：正在处理…')
        selected_path, code = path.text().strip(), room.text().strip()
        player = nickname.text().strip()
        public_nodes = list(node_choice.currentData() or [])
        if action in ('host', 'join'):
            selected_instance = instance_choice.currentData()
            page._terracotta_instance = dict(selected_instance) if selected_instance else None
        if action in ('host', 'join'):
            api.set_config('terracotta_player', player)
        def work():
            try:
                binary_path = selected_path
                if action != 'leave' and not os.path.isfile(binary_path):
                    signals.progress.emit('正在自动准备 Terracotta…')
                    binary_path = download_terracotta(api.data_path('terracotta'), signals.progress.emit)
                    signals.auto_installed.emit(binary_path)
                terracotta_connect(binary_path)
                if action == 'host':
                    terracotta_host(player, public_nodes)
                elif action == 'join':
                    terracotta_join(code, player, public_nodes)
                elif action == 'leave':
                    terracotta_leave()
                result = fetch_state()
            except Exception as exc:
                result = exc
            try:
                signals.result.emit(result)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()

    def poll_ready(result):
        polling['value'] = False
        # 操作进行中时不使用可能早于操作的状态快照。
        if busy['value']:
            return
        if isinstance(result, Exception):
            if _terracotta_port is None:
                show_state({'state': 'waiting'})
            connection.setText('无法读取陶瓦状态：' + str(result))
            members_title.setText('大厅成员 · 状态读取失败')
        else:
            show_state(result)
    signals.polled.connect(poll_ready)

    def poll_state():
        if busy['value'] or polling['value']:
            return
        polling['value'] = True
        def work():
            try:
                result = fetch_state()
            except Exception as exc:
                result = exc
            try:
                signals.polled.emit(result)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()

    def choose_binary():
        global _terracotta_path
        selected, _ = QFileDialog.getOpenFileName(page, '选择 Terracotta 官方程序', path.text(), '程序 (*.exe);;所有文件 (*)')
        if selected:
            _terracotta_path = selected
            path.setText(selected)
            api.set_config('terracotta_binary', selected)
            status.setText('程序已选择；创建或加入大厅时启动 Terracotta。')
            hide_recovery()

    choose.clicked.connect(choose_binary)
    download.clicked.connect(start_download)
    host.clicked.connect(lambda: run('host'))
    def choose_join():
        if not join_mode['value']:
            join_mode['value'] = True
            host.hide()
            room.show()
            cancel_join.show()
            join.setText('确认加入')
            room.setFocus()
        elif not room.text().strip():
            status.setText('请输入大厅编号。')
            room.setFocus()
        else:
            run('join')
    def cancel_joining():
        join_mode['value'] = False
        room.hide()
        cancel_join.hide()
        host.show()
        join.setText('加入大厅')
    join.clicked.connect(choose_join)
    cancel_join.clicked.connect(cancel_joining)
    leave.clicked.connect(lambda: run('leave'))
    seen_install = {'message': ''}
    def refresh_install():
        if _terracotta_path and os.path.isfile(_terracotta_path) and not path.hasFocus():
            path.setText(_terracotta_path)
        message = _install_state['terracotta']
        if message and message != seen_install['message']:
            seen_install['message'] = message
            if _terracotta_port is None and not busy['value']:
                status.setText(message)
                if '失败' in message:
                    show_recovery()
    timer = QTimer(page)
    timer.setInterval(2500)
    def tick():
        if page.isVisible():
            refresh_install()
            scan_running_processes()
            refresh_running_instances()
        # 大厅断线后的清理也要在用户切换页面、关闭联机浮窗时继续。
        if _terracotta_port:
            poll_state()
    timer.timeout.connect(tick)
    timer.start()
    QTimer.singleShot(0, tick)


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
    global _configured_core
    _download_lock.acquire()
    try:
        if _configured_core and os.path.isfile(_configured_core):
            return _configured_core
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
            _configured_core = os.path.join(final, relative)
            return _configured_core
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


def _start_auto_install(api):
    """After the plugin is enabled, fetch missing runtimes without blocking startup."""
    def work():
        global _terracotta_path, _configured_core
        if _terracotta_path and os.path.isfile(_terracotta_path):
            _install_state['terracotta'] = '陶瓦已就绪'
        else:
            try:
                _install_state['terracotta'] = '正在自动下载陶瓦…'
                binary = download_terracotta(api.data_path('terracotta'))
                _terracotta_path = binary
                api.set_config('terracotta_binary', binary)
                _install_state['terracotta'] = '陶瓦已下载并校验'
            except Exception as exc:
                _install_state['terracotta'] = f'陶瓦自动下载失败：{exc}'
        found = _find_core()
        if found:
            _install_state['easytier'] = 'EasyTier 已就绪'
        else:
            try:
                _install_state['easytier'] = '正在自动下载 EasyTier…'
                binary = download_core(api.data_path('easytier'))
                _configured_core = binary
                api.set_config('easytier_core', binary)
                _install_state['easytier'] = 'EasyTier 已下载并校验'
            except Exception as exc:
                _install_state['easytier'] = f'EasyTier 自动下载失败：{exc}'
    threading.Thread(target=work, name='amcl-online-install', daemon=True).start()


def register(api):
    global _configured_core, _terracotta_path
    _configured_core = str(api.get_config("easytier_core", "") or "")
    _terracotta_path = str(api.get_config("terracotta_binary", "") or "")
    _install_state.update(terracotta='', easytier='')

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

    def build_easytier_page():
        from PySide6.QtCore import QTimer, QObject, Signal, Qt
        from PySide6.QtWidgets import QApplication, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView

        page = QWidget()
        page.setObjectName('easyTierSettingsPage')
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        page.setStyleSheet('QWidget#easyTierSettingsPage { background: transparent; }')
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(QLabel("EasyTier 虚拟局域网"))
        info = QLabel("启动房间时会自动准备 EasyTier。启动/停止时可能弹出 UAC 授权，停止只影响本插件启动的进程。")
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
        path_row.addWidget(core_path, 1)
        layout.addLayout(path_row)
        path_buttons = QHBoxLayout()
        path_buttons.addWidget(choose)
        path_buttons.addWidget(download)
        path_buttons.addStretch()
        layout.addLayout(path_buttons)
        for control in (core_path, choose, download):
            control.hide()
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
        downloading = {'value': False}
        pending_start = {'value': False}

        def show_recovery():
            for control in (core_path, choose, download):
                control.show()

        def hide_recovery():
            for control in (core_path, choose, download):
                control.hide()

        def download_done(path):
            global _configured_core

            downloading['value'] = False
            _configured_core = path
            core_path.setText(path)
            api.set_config('easytier_core', path)
            download.setEnabled(True)
            choose.setEnabled(True)
            status.setText('下载完成，SHA-256 校验通过；程序路径已保存。点击“启动房间”才会联机。')
            hide_recovery()
            if pending_start['value']:
                pending_start['value'] = False
                start_room()

        def download_error(message):
            downloading['value'] = False
            download.setEnabled(True)
            choose.setEnabled(True)
            status.setText('下载失败：' + message + '\n可以重试；若 GitHub 连不上，换个网络或手动选择程序。')
            pending_start['value'] = False
            show_recovery()

        signals.progress.connect(status.setText)
        signals.done.connect(download_done)
        signals.error.connect(download_error)

        def start_download():
            if downloading['value']:
                return
            destination = api.data_path('easytier')
            downloading['value'] = True
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
        room_fields.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
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
            copy.clicked.connect(lambda checked=False, field=control, button=copy: copy_with_feedback(button, field.text()))
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
        copy_room.clicked.connect(lambda: copy_with_feedback(copy_room,
            f"房间名：{room_name.text()}\n密钥：{room_secret.text()}"))
        layout.addWidget(copy_room)

        def refresh():
            if _configured_core and os.path.isfile(_configured_core) and not core_path.hasFocus():
                core_path.setText(_configured_core)
            current = easytier_status()
            if current["installed"]:
                status.setText(f"EasyTier: ✅ 已找到 {current['path']}" + ("（运行中）" if current["running"] else ""))
                hide_recovery()
            else:
                status.setText(_install_state['easytier'] or "EasyTier: ❌ 未找到；可重试下载或手动选择程序")
                if '失败' in _install_state['easytier']:
                    show_recovery()

        def choose_core():
            global _configured_core
            selected, _ = QFileDialog.getOpenFileName(page, "选择 easytier-core", core_path.text(), "程序 (*.exe);;所有文件 (*)")
            if selected:
                _configured_core = selected
                core_path.setText(selected)
                api.set_config("easytier_core", selected)
                refresh()

        def start_room():
            if not _find_core():
                pending_start['value'] = True
                status.setText('正在自动准备 EasyTier…')
                start_download()
                return
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
        install_timer = QTimer(page)
        install_timer.setInterval(2000)
        seen_install = {'value': (_configured_core, _install_state['easytier'])}
        def refresh_install():
            current = (_configured_core, _install_state['easytier'])
            if (page.isVisible() and _session is None and not downloading['value']
                    and current != seen_install['value']):
                seen_install['value'] = current
                refresh()
        install_timer.timeout.connect(refresh_install)
        install_timer.start()
        layout.addStretch()
        return page

    def build_terracotta_page():
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QVBoxLayout, QWidget
        page = QWidget()
        page.setObjectName('terracottaSettingsPage')
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        page.setStyleSheet('QWidget#terracottaSettingsPage { background: transparent; }')
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 12, 16, 12)
        _add_terracotta_ui(layout, page, api)
        layout.addStretch()
        return page

    def build_settings_page():
        from PySide6.QtWidgets import QTabWidget
        from ui_style import set_style, tab_style
        tabs = QTabWidget()
        set_style(tabs, tab_style)
        tabs.addTab(build_terracotta_page(), '陶瓦联机')
        tabs.addTab(build_easytier_page(), 'EasyTier 设置')
        return tabs

    api.register_settings_page(build_settings_page)
    if hasattr(api, 'register_center_page'):
        api.register_center_page('online', 'terracotta', '陶瓦联机', build_terracotta_page)
        api.register_center_page('online', 'easytier', 'EasyTier 设置', build_easytier_page)
    _start_auto_install(api)
