# -*- coding: utf-8 -*-
"""
MCP Server 插件(默认关闭):把启动器工具暴露给外部 AI 宿主(MCP 客户端)。
- 默认关闭(PLUGIN_DEFAULT_ENABLED=False):只在设置→插件 勾选启用 / 在设置页点启动时才拉起。
- 独立设置页:配置端口、启动/停止 Streamable-HTTP 服务(后台线程,不阻塞 GUI)、显示连接 URL。
- 也可用 CLI 旧方式:python main.py --mcp(stdio)/ --mcp-http [port](HTTP),与插件互不影响。
"""
import threading

PLUGIN_ID = "mcp_server"
PLUGIN_NAME = "MCP Server(给外部 AI 调用启动器)"
PLUGIN_DESCRIPTION = "把启动器工具暴露给 MCP 客户端(Claude Desktop/VS Code 等)。默认关闭,按需拉起到本地端口。"
PLUGIN_DEFAULT_ENABLED = False   # 默认关闭:启动器 AI 用不到它,按需开

# 全局:插件内维护的服务实例(附到插件模块,避免多实例)
_srv = None
_srv_lock = threading.Lock()


def _get_server(port: int):
    global _srv
    with _srv_lock:
        if _srv is None:
            from mcp_server import MCPHttpServer
            _srv = MCPHttpServer("127.0.0.1", port)
        elif _srv.port != port:
            _srv.stop()
            from mcp_server import MCPHttpServer
            _srv = MCPHttpServer("127.0.0.1", port)
        return _srv


def status(port: int = 8766) -> dict:
    with _srv_lock:
        running = (_srv is not None and _srv.is_running())
    return {"running": running, "url": f"http://127.0.0.1:{port}/mcp"}


def start_server(port: int = 8766) -> bool:
    return _get_server(port).start()


def stop_server() -> bool:
    global _srv
    with _srv_lock:
        if _srv is not None:
            _srv.stop()
        return True


def register(api):
    # ---- AI 工具:让启动器 AI 能查 MCP 服务状态 ----
    def mcp_status(args: dict):
        port = int((args or {}).get("port", 8766))
        st = status(port)
        return ("✅ MCP Server 运行中: " + st["url"] if st["running"]
                else "❌ MCP Server 未运行(可在 设置→插件→MCP Server 启动)")

    api.register_tool(name="mcp_status", description="查询本启动器 MCP Server(HTTP)是否在运行。",
                      parameters={"type": "object",
                                  "properties": {"port": {"type": "integer", "description": "端口,默认 8766"}},
                                  "required": []},
                      handler=mcp_status)

    # ---- 独立设置页(设置→左菜单单开一行)----
    def build_settings_page():
        from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                                       QSpinBox, QVBoxLayout, QWidget)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        lay.addWidget(QLabel("MCP Server(把启动器工具暴露给外部 AI 宿主)"))
        desc = QLabel("客户端用「http」选项填下面的地址即可连本启动器;走后端 127.0.0.1 端口,不放公网。\n"
                      "默认关闭:不用时不占端口;按需启动。")
        desc.setWordWrap(True); desc.setStyleSheet("color:#8a93a0; font-size:11px;")
        lay.addWidget(desc)

        # 端口
        prow = QHBoxLayout()
        prow.addWidget(QLabel("端口:"))
        port_spin = QSpinBox(); port_spin.setRange(1024, 65535); port_spin.setValue(8766)
        prow.addWidget(port_spin)
        lay.addLayout(prow)

        # 启动/停止
        srow = QHBoxLayout()
        start_btn = QPushButton("启动 MCP Server")
        start_btn.setMinimumHeight(34)
        stop_btn = QPushButton("停止")
        stop_btn.setMinimumHeight(34)
        srow.addWidget(start_btn); srow.addWidget(stop_btn); srow.addStretch()
        lay.addLayout(srow)

        # URL(只读)
        url_edit = QLineEdit(); url_edit.setReadOnly(True)
        url_edit.setPlaceholderText("连接地址(启动后显示)")
        lay.addWidget(url_edit)
        status_lbl = QLabel("状态: 未运行")
        status_lbl.setWordWrap(True); status_lbl.setStyleSheet("color:#8a93a0;")
        lay.addWidget(status_lbl)

        def refresh():
            st = status(port_spin.value())
            if st["running"]:
                status_lbl.setText("✅ 运行中"); url_edit.setText(st["url"])
            else:
                status_lbl.setText("❌ 未运行"); url_edit.setText("")

        def do_start():
            port = port_spin.value()
            if start_server(port):
                refresh()
                status_lbl.setText("✅ 运行中: " + f"http://127.0.0.1:{port}/mcp")
            else:
                status_lbl.setText("❌ 启动失败(端口被占?)")
            url_edit.setText(f"http://127.0.0.1:{port}/mcp" if start_server(port) else "")

        def do_stop():
            stop_server(); refresh()

        start_btn.clicked.connect(do_start)
        stop_btn.clicked.connect(do_stop)
        port_spin.valueChanged.connect(lambda _v: refresh())
        lay.addStretch()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, refresh)
        return w

    api.register_settings_page(build_settings_page)
