# -*- coding: utf-8 -*-
"""EasyTier 命令行桥接（可选插件）。

插件只管理用户自行安装的 easytier-core：检测路径、启动一个受控进程、停止该进程。
不下载二进制、不把端口暴露到公网，也不把“生成房间名”误报为已经组网。
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
PLUGIN_NAME = "联机 CLI 桥接"
PLUGIN_DESCRIPTION = "检测并受控启动本机 EasyTier，创建虚拟局域网房间；不内置或下载第三方二进制。"
PLUGIN_VERSION = "0.2.0"
PLUGIN_API_VERSION = 1
PLUGIN_DEFAULT_ENABLED = False

_configured_core = ""
_process = None
_elevated_pid = None
_process_lock = threading.Lock()
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
        f"-ArgumentList @({ps_args}) -Verb RunAs -PassThru; $p.Id"
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
        "-Verb RunAs -Wait -PassThru; exit $p.ExitCode"
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
    global _process, _elevated_pid
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
        arguments = ["--network-name", room_name, "--network-secret", secret, "-p", _shared_peer]
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
    return {
        "ok": True,
        "room_key": f"{room_name} / {secret}",
        "virtual_ip": "正在由 EasyTier 分配（可在其客户端查看）",
        "note": f"本机 EasyTier 已启动，使用共享节点 {_shared_peer}",
    }


def stop_easytier() -> bool:
    global _process, _elevated_pid
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
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(QLabel("联机 CLI 工具（EasyTier）"))
        info = QLabel("不会下载或内置第三方程序。非管理员启动器会在启动/停止时弹出 Windows 的 UAC 授权；停止只影响本插件启动的进程。")
        info.setWordWrap(True)
        layout.addWidget(info)
        path_row = QHBoxLayout()
        core_path = QLineEdit(_configured_core)
        core_path.setPlaceholderText("easytier-core.exe 路径（留空则自动检测）")
        choose = QPushButton("选择程序")
        path_row.addWidget(core_path, 1); path_row.addWidget(choose)
        layout.addLayout(path_row)
        status = QLabel("检测中…")
        status.setWordWrap(True)
        layout.addWidget(status)
        button_row = QHBoxLayout()
        start = QPushButton("启动房间")
        stop = QPushButton("停止房间")
        button_row.addWidget(start); button_row.addWidget(stop); button_row.addStretch()
        layout.addLayout(button_row)
        room_key, virtual_ip = QLineEdit(), QLineEdit()
        for control, placeholder in ((room_key, "房间钥匙（房间名 / 密钥）"), (virtual_ip, "虚拟 IP 状态")):
            control.setReadOnly(True); control.setPlaceholderText(placeholder); layout.addWidget(control)

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
                room_key.setText(result["room_key"]); virtual_ip.setText(result["virtual_ip"])
                status.setText("✅ 已启动。把房间钥匙发给朋友；双方连接后在 EasyTier 查看虚拟 IP。")
            else:
                status.setText("❌ " + result.get("error", "启动失败"))

        def stop_room():
            if stop_easytier():
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
