# -*- coding: utf-8 -*-
"""
MCP Server(轻量,零第三方依赖):把启动器的工具(agent_tools + server_service)暴露成 MCP 工具。

**MCP = Model Context Protocol**(Anthropic 提出),让外部 AI 宿主(Claude Desktop / VS Code /
其它 MCP 客户端 / 启动器自己的 AI)能远程调用启动器的能力(列实例/装 Mod/查日志/启动等)。

本实现**手写 JSON-RPC 2.0 over stdio**(MCP 最常用的传输),不引入 `mcp` 依赖:
- 走 stdin/stdout:宿主 `/path/python main.py --mcp` 拉起本进程,一行一个 JSON-RPC 消息。
- 支持:initialize / notifications/initialized / tools/list / tools/call / ping。

工具来源:
- `agent_tools`(客户端侧:列实例/装 Mod/查配方/发指令等,"文本进→文本出")。
- `server_service`(服务端侧:列服务端/启停/发指令/读配置/导入/诊断等,Qt-free)。
- 两者 schema 均由函数签名 + 描述表生成;调用时按签名过滤参数。
"""
import inspect
import json
import sys

import agent_tools
import server_service


# ---- 客户端工具描述 ----
_TOOL_DESC = {
    "list_instances": "列出已安装的实例(加载器/基础版本)",
    "list_mods": "列出某实例已安装的 Mod 文件",
    "search_mods": "搜索 Mod(支持中文名)",
    "search_modpacks": "搜索整合包(Modrinth modpack)",
    "read_instance_log": "读取某实例最近的游戏日志",
    "read_crash_report": "读取某实例最新的崩溃报告",
    "get_settings": "查看启动器当前设置",
    "install_mod": "给某实例安装单个 Mod",
    "install_mods": "批量给某实例安装多个 Mod",
    "install_instance": "创建新游戏实例(原版/带加载器)",
    "install_modpack": "下载并导入 Modrinth 整合包",
    "backup_instance": "备份某实例(存档 zip + mod 列表)",
    "set_setting": "修改启动器设置",
    "launch_game": "启动某实例",
    "send_game_command": "向运行中的游戏发送指令",
    "get_command_guide": "按游戏版本查指令指南",
    "get_key_bindings": "查询按键绑定",
    "get_recipe_path": "查询物品合成配方",
    "compare_items": "比较物品参数(武器伤害/护甲等)",
    "translate_mod_desc": "翻译 Mod 描述(英→中)",
}

# ---- 服务端工具(来自 server_service,Qt-free) ----
_SERVER_TOOL_FUNCS = {
    "list_servers": server_service.list_servers,
    "server_status": server_service.server_status,
    "start_server": server_service.start_server,
    "stop_server": server_service.stop_server,
    "send_server_command": server_service.send_server_command,
    "inspect_pack": server_service.inspect_pack,
    "import_server": server_service.import_server,
    "install_runtime": server_service.install_runtime,
    "read_server_properties": server_service.read_server_properties,
    "apply_server_properties": server_service.apply_server_properties,
    "diagnose_server_log": server_service.diagnose_server_log,
    "export_start_command": server_service.export_start_command,
}

_SERVER_TOOL_DESC = {
    "list_servers": "列出已管理的服务端(名称/加载器/MC 版本/运行状态)",
    "server_status": "查看某个服务端的运行状态(PID/端口/是否在线)",
    "start_server": "启动一个已安装的服务端(需要 Java 路径 + 启动参数)",
    "stop_server": "安全停止运行中的服务端(等世界保存后退出)",
    "send_server_command": "向运行中的服务端发送控制台指令(如 say/whitelist/op/ban)",
    "inspect_pack": "扫描 ZIP/MRPACK 服务端包,返回版本/加载器/Java/文件清单等报告(不导入)",
    "import_server": "导入一个已扫描确认的服务端包到游戏目录",
    "install_runtime": "为服务端补全运行库(运行官方安装器,补 libraries 等)",
    "read_server_properties": "读取服务端 server.properties 当前键值",
    "apply_server_properties": "原子修改服务端 server.properties(带备份+校验+运行中拒写)",
    "diagnose_server_log": "解析服务端日志/崩溃报告,诊断崩溃原因并建议修复(纯函数,不改文件)",
    "export_start_command": "把启动计划导出为可复制的 java 命令行(用于 start.bat / MCSManager 等面板)",
}


# ---- MCSManager 联动工具(opt-in,需 mcsmapi 包 + settings 配置) ----
def _mcsm_client():
    """从 settings 构建 MCSManagerClient(每次调用都重新建,保证用最新配置)。"""
    from mcsmanager_adapter import MCSManagerClient
    try:
        from settings import load_settings
        s = load_settings()
    except Exception:
        s = url = apikey = ""
        return MCSManagerClient()
    url = (s.get("mcsmanager_url") or "").strip()
    apikey = (s.get("mcsmanager_apikey") or "").strip()
    username = (s.get("mcsmanager_username") or "").strip()
    password = (s.get("mcsmanager_password") or "").strip()
    if not url:
        raise ValueError("未配置 MCSManager URL(settings → mcsmanager_url)")
    client = MCSManagerClient(url=url, apikey=apikey, username=username, password=password)
    client.connect()
    return client


def _mcsm_test_connection() -> str:
    from mcsmanager_adapter import test_connection
    try:
        from settings import load_settings
        s = load_settings()
    except Exception:
        return "无法加载启动器设置。"
    return test_connection(s)


def _mcsm_list_daemons() -> str:
    client = _mcsm_client()
    daemons = client.list_daemons()
    lines = [f"共 {len(daemons)} 个节点:"]
    for d in daemons:
        tag = "在线" if d.get("available") else "离线"
        lines.append(f"  [{tag}] {d['uuid']}  {d.get('ip','')}:{d.get('port','')}  {d.get('remarks','')}")
    return "\n".join(lines)


def _mcsm_list_instances(daemon: str = "") -> str:
    client = _mcsm_client()
    instances = client.list_instances(daemon_id=daemon)
    if not instances:
        return "没有实例。"
    lines = [f"共 {len(instances)} 个实例:"]
    for inst in instances:
        lines.append(f"  {inst['uuid']}  [{inst['status']}]  {inst['name']}  (node={inst['daemon_id'][:8]}...)")
    return "\n".join(lines)


def _mcsm_instance_status(daemon_id: str, uuid: str) -> str:
    client = _mcsm_client()
    inst = client.instance_status(daemon_id, uuid)
    import json
    return json.dumps(inst, ensure_ascii=False, indent=2)


def _mcsm_start_instance(daemon_id: str, uuid: str) -> str:
    client = _mcsm_client()
    return f"已启动: {client.start_instance(daemon_id, uuid)}"


def _mcsm_stop_instance(daemon_id: str, uuid: str) -> str:
    client = _mcsm_client()
    return f"已停止: {client.stop_instance(daemon_id, uuid)}"


def _mcsm_send_command(daemon_id: str, uuid: str, command: str) -> str:
    client = _mcsm_client()
    client.send_command(daemon_id, uuid, command)
    return f"> {command}"


def _mcsm_get_output(daemon_id: str, uuid: str, size: int = 0) -> str:
    client = _mcsm_client()
    return client.get_output(daemon_id, uuid, size=size if size > 0 else None)


_MCSM_TOOL_FUNCS = {
    "mcsm_test_connection": _mcsm_test_connection,
    "mcsm_list_daemons": _mcsm_list_daemons,
    "mcsm_list_instances": _mcsm_list_instances,
    "mcsm_instance_status": _mcsm_instance_status,
    "mcsm_start_instance": _mcsm_start_instance,
    "mcsm_stop_instance": _mcsm_stop_instance,
    "mcsm_send_command": _mcsm_send_command,
    "mcsm_get_output": _mcsm_get_output,
}

_MCSM_TOOL_DESC = {
    "mcsm_test_connection": "测试与 MCSManager 面板的连接(settings 中配置 URL 和 API Key)",
    "mcsm_list_daemons": "列出 MCSManager 的所有节点(在线/离线/地址)",
    "mcsm_list_instances": "列出 MCSManager 管理的所有实例(可按节点过滤)",
    "mcsm_instance_status": "查看 MCSManager 上某个实例的详细状态",
    "mcsm_start_instance": "通过 MCSManager 启动一个实例",
    "mcsm_stop_instance": "通过 MCSManager 停止一个实例",
    "mcsm_send_command": "通过 MCSManager 向实例发送控制台指令",
    "mcsm_get_output": "通过 MCSManager 获取实例的控制台输出/日志",
}

# 合并:调用方不需要关心来源,统一用名字查
_ALL_TOOL_FUNCS = {**{name: getattr(agent_tools, name) for name in agent_tools.TOOL_FUNCS},
                   **_SERVER_TOOL_FUNCS,
                   **_MCSM_TOOL_FUNCS}


def _type_name(t):
    return {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}.get(
        getattr(t, "__name__", "str"), "string")


# 这些参数是内部回调/自动填充的,不暴露给 MCP 客户端
_EXCLUDE_PARAMS = frozenset({"status", "status_callback", "progress_callback"})


def _schema_for(fn):
    """由函数签名生成 inputSchema:参数名→类型;有默认值的可选。"""
    if fn is None:
        return {"type": "object", "properties": {}, "required": []}
    props = {}
    required = []
    for pname, p in inspect.signature(fn).parameters.items():
        if pname in _EXCLUDE_PARAMS or pname.startswith("_"):
            continue
        if pname == "game_dir" and fn not in _SERVER_TOOL_FUNCS.values():
            continue   # 客户端 tool 的 game_dir 由启动器自动填;服务端 tool 暴露它
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue   # *args / **kwargs 不暴露
        props[pname] = {"type": _type_name(p.annotation)}
        if p.default is inspect.Parameter.empty:
            required.append(pname)
    return {"type": "object", "properties": props, "required": required}


def _tool_list():
    out = []
    for name, fn in _ALL_TOOL_FUNCS.items():
        desc = (_TOOL_DESC.get(name) or _SERVER_TOOL_DESC.get(name)
                or _MCSM_TOOL_DESC.get(name) or f"调用启动器工具 {name}")
        out.append({
            "name": name,
            "description": desc,
            "inputSchema": _schema_for(fn),
        })
    return out


def _call(name, args):
    fn = _ALL_TOOL_FUNCS.get(name)
    if fn is None:
        return f"错误:未知工具 {name}"
    try:
        kwargs = {k: v for k, v in (args or {}).items()
                  if k in inspect.signature(fn).parameters}
        return str(fn(**kwargs))
    except Exception as e:
        return f"错误:工具 {name} 调用失败:{type(e).__name__}: {e}"


def handle_message(msg: dict) -> dict | None:
    """处理一条 JSON-RPC 消息,返回完整响应(通知返回 None)。stdio 与 HTTP 共用。"""
    m_id = msg.get("id")
    method = msg.get("method")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": m_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "AMCL", "version": "0.1"}}}
    if method.startswith("notifications/"):
        return None   # 通知无响应
    if method == "ping":
        return {"jsonrpc": "2.0", "id": m_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": m_id, "result": {"tools": _tool_list()}}
    if method == "tools/call":
        p = msg.get("params") or {}
        text = _call(p.get("name"), p.get("arguments"))
        return {"jsonrpc": "2.0", "id": m_id, "result": {
            "content": [{"type": "text", "text": text}]}}
    return {"jsonrpc": "2.0", "id": m_id,
            "error": {"code": -32601, "message": f"未知方法 {method}"}}


def serve():
    """stdio MCP 主循环:一行一个 JSON-RPC 消息。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        resp = handle_message(msg)
        if resp is None:
            continue
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def serve_http(host: str = "127.0.0.1", port: int = 8766):
    """Streamable-HTTP 模式:POST /mcp 接收 JSON-RPC,返回 application/json。
    让 MCP 客户端能通过「http」选项连接(本地启动器跑这一端)。"""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path.rstrip("/") != "/mcp":
                self.send_response(404)
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                msg = json.loads(body or b"{}")
            except Exception:
                self.send_response(400)
                self.end_headers()
                return
            resp = handle_message(msg)
            if resp is None:      # 通知 → 202
                self.send_response(202)
                self.end_headers()
                return
            data = json.dumps(resp, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass   # 静默访问日志

    print(f"AMCL MCP 服务已启动 http://{host}:{port}/mcp")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


# ---- 可启停的 HTTP 服务(供插件/设置页在 GUI 内启停)----
_MCP_HTTP_SERVER = None       # ThreadingHTTPServer 实例


class MCPHttpServer:
    """把 serve_http 封成可 start()/stop() 的对象:后台线程跑,不阻塞 GUI。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8766):
        self.host, self.port = host, port
        self._server = None
        self._thread = None

    def is_running(self) -> bool:
        return self._server is not None

    def start(self) -> bool:
        if self._server is not None:
            return True
        try:
            import threading
            from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

            class Handler(BaseHTTPRequestHandler):
                def do_POST(self):
                    if self.path.rstrip("/") != "/mcp":
                        self.send_response(404); self.end_headers(); return
                    try:
                        length = int(self.headers.get("Content-Length", 0))
                        msg = json.loads(self.rfile.read(length) or b"{}")
                    except Exception:
                        self.send_response(400); self.end_headers(); return
                    resp = handle_message(msg)
                    if resp is None:
                        self.send_response(202); self.end_headers(); return
                    data = json.dumps(resp, ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers(); self.wfile.write(data)

                def log_message(self, *_):
                    pass

            self._server = ThreadingHTTPServer((self.host, self.port), Handler)
            self._thread = threading.Thread(target=self._server.serve_forever,
                                            daemon=True)
            self._thread.start()
            return True
        except Exception:
            self._server = None
            return False

    def stop(self):
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None


if __name__ == "__main__":
    serve()
