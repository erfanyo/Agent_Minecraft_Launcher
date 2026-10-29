# SPDX-License-Identifier: GPL-3.0-only
"""AMCL instance plugin. Development checkout integration; no bundled core yet."""

import json
import secrets
import shutil
from pathlib import Path
from uuid import UUID, uuid4
from zipfile import ZipFile

PLUGIN_ID = "craftloom"
PLUGIN_NAME = "织途 CraftLoom"
PLUGIN_DESCRIPTION = "为实例准备织途知识服务、游戏 Mod 与目标工作台。"
PLUGIN_VERSION = "0.2.0-dev.1"
PLUGIN_API_VERSION = 1
PLUGIN_DEFAULT_ENABLED = False

_process = None


def prepare(game_dir, repository, data_dir, instance_name):
    """Explicit button action: preserve identity and back up the previous Mod."""
    game = Path(game_dir)
    repository = Path(repository)
    data = Path(data_dir)
    artifact = repository / "game/forge-1.20.1/build/libs/craftloom-forge-1.20.1-0.1.0-dev.1.jar"
    with ZipFile(artifact) as jar:
        if any("IntegrationSmoke" in name for name in jar.namelist()):
            raise ValueError("不能安装包含实机测试夹具的 Mod，请先常规 clean build")
    config = game / "config"
    config.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    identity_path = config / "craftloom-instance.json"
    if identity_path.exists():
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        UUID(identity["id"])
    else:
        identity = {"id": str(uuid4()), "name": str(instance_name)[:200]}
        identity_path.write_text(json.dumps(identity, ensure_ascii=False), encoding="utf-8")
    secret = data / "access-token"
    if not secret.exists():
        secret.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    connection = {"endpoint": "http://127.0.0.1:24780", "token": secret.read_text().strip()}
    for path in (data / "connection.json", config / "craftloom-connection.json"):
        path.write_text(json.dumps(connection), encoding="utf-8")
    mods = game / "mods"
    mods.mkdir(exist_ok=True)
    for old in mods.glob("craftloom-forge-1.20.1-*.jar"):
        backup = data / "mod-backups" / str(uuid4())
        backup.mkdir(parents=True)
        shutil.copy2(old, backup / old.name)
        old.unlink()
    shutil.copy2(artifact, mods / artifact.name)
    return identity


def register(api):
    def build(ctx):
        from PySide6.QtCore import QProcess, QUrl
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import (
            QApplication,
            QFileDialog,
            QLabel,
            QLineEdit,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("织途 · 当前实例知识工作台"))
        layout.addWidget(
            QLabel(
                f"实例：{ctx.instance_id}\n知识跟随实例，目标跟随世界。当前仅支持 1.20.1 Forge。"
            )
        )
        repository = QLineEdit(str(api.get_config("repository", "")))
        repository.setPlaceholderText("选择 CraftLoom 开发仓库（含 .venv 与已构建 Mod）")
        layout.addWidget(repository)
        status = QLabel("尚未准备；此开发插件不会自动下载或安装第三方依赖。")
        status.setWordWrap(True)

        def report(text):
            from shiboken6 import isValid

            if isValid(status):
                status.setText(text)

        def choose():
            path = QFileDialog.getExistingDirectory(widget, "选择 CraftLoom 仓库")
            if path:
                repository.setText(path)
                api.set_config("repository", path)

        def install():
            try:
                identity = prepare(ctx.game_dir, repository.text(), api.data_dir(), ctx.instance_id)
                report(f"已准备：{identity['name']}。请启动核心后进入游戏。")
            except Exception as error:
                report(f"准备失败：{error}")

        def spawn_core():
            global _process
            if _process is not None and _process.state() != QProcess.NotRunning:
                report("本插件的核心已启动。")
                return
            root = Path(repository.text())
            executable = root / ".venv/Scripts/python.exe"
            if not executable.is_file():
                report("未找到开发环境，请先准备 CraftLoom 的 .venv。")
                return
            _process = QProcess(QApplication.instance())
            _process.setWorkingDirectory(str(root))
            _process.setProgram(str(executable))
            _process.setArguments(["-m", "craftloom.cli", "serve", "--data-dir", api.data_dir()])
            _process.setStandardOutputFile(str(Path(api.data_dir()) / "core.log"))
            _process.setProcessChannelMode(QProcess.MergedChannels)
            _process.errorOccurred.connect(lambda _: report("核心启动失败，请检查日志。"))
            _process.finished.connect(
                lambda code, _: report(f"核心已退出：{code}；端口冲突请检查日志。")
            )
            _process.start()
            report("已请求启动核心，结果见日志与工作台。")

        def start():
            # Reuse the single authenticated core, including one restarted for an update.
            from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

            try:
                token = (Path(api.data_dir()) / "access-token").read_text().strip()
            except OSError:
                report("请先准备当前实例。")
                return
            manager = QNetworkAccessManager(widget)
            query = QNetworkRequest(QUrl("http://127.0.0.1:24780/v1/contexts"))
            query.setRawHeader(b"Authorization", f"Bearer {token}".encode())
            query.setTransferTimeout(2000)
            reply = manager.get(query)

            def finished():
                code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                if code == 200:
                    report("已连接现有本机核心，无需重复启动。")
                elif reply.error() == QNetworkReply.ConnectionRefusedError:
                    spawn_core()
                else:
                    report("端口已有其他服务或连接凭据不一致，请核对当前核心。")
                reply.deleteLater()
                manager.deleteLater()

            reply.finished.connect(finished)
            report("正在检查本机核心…")

        def open_workbench():
            try:
                identity = json.loads(
                    (Path(ctx.game_dir) / "config/craftloom-instance.json").read_text(
                        encoding="utf-8"
                    )
                )
                instance = str(UUID(identity["id"]))
                QDesktopServices.openUrl(QUrl(f"http://127.0.0.1:24780/?instance={instance}"))
            except Exception as error:
                report(f"请先准备当前实例：{error}")

        for text, callback in (
            ("选择仓库", choose),
            ("准备当前实例", install),
            ("启动核心", start),
            ("打开实例工作台", open_workbench),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            layout.addWidget(button)
        layout.addWidget(status)
        layout.addStretch()
        return widget

    api.register_instance_section("织途知识与目标", build)
