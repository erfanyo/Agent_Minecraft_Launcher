# -*- coding: utf-8 -*-
"""
MCP 客户端(轻量,零依赖):让启动器自己的 AI 能调用**外部 MCP 服务器**的工具。

- 传输:Streamable-HTTP(POST /mcp → application/json),与 mcp_server.serve_http 对称。
- 能力:initialize / tools/list / tools/call。
- 工具名规范化为 `mcp__<server名>__<工具名>`,避免与内置 agent_tools 冲突;
  调用时按 server 名路由到对应 MCP 服务器。

用法:
  client = MCPClient("amcl", "http://127.0.0.1:8766/mcp")
  client.initialize()
  tools = client.tools()          # [ {name, description, inputSchema} ]
  text = client.call("list_instances", {})   # 文本结果
"""
import json
import subprocess
import threading
import time
import urllib.request


class MCPStdioClient:
    """stdio 传输的 MCP 客户端:本地起一个子进程,一行一个 JSON-RPC 消息。
    用于连接 mc-wiki 等"以 stdio 方式运行的 MC 资料库 MCP 服务器"。
    command/args 如 ["uvx", "mc-wiki-mcp"] 或 [python, -m, {一些模块}]。"""
    def __init__(self, name: str, command: list):
        self.name = name
        self.command = command
        self._id = 0
        self._lock = threading.Lock()
        try:
            self.proc = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", bufsize=1,
            )
        except Exception:
            self.proc = None

    def _send(self, method: str, params=None) -> dict:
        if self.proc is None:
            raise RuntimeError("stdio 客户端启动失败(命令不存在?)")
        self._id += 1
        line = json.dumps({"jsonrpc": "2.0", "id": self._id,
                           "method": method, "params": params or {}},
                          ensure_ascii=False)
        with self._lock:
            self.proc.stdin.write(line + "\n")
            self.proc.stdin.flush()
            # 读响应:逐行读,直到拿到匹配 id 的 JSON-RPC 响应
            deadline = time.time() + 20
            while time.time() < deadline:
                out = self.proc.stdout.readline()
                if not out:
                    break
                out = out.strip()
                if not out:
                    continue
                try:
                    m = json.loads(out)
                except Exception:
                    continue
                if m.get("id") == self._id:
                    return m
        raise TimeoutError("stdio MCP 未在 20 秒内响应")

    def initialize(self):
        return self._send("initialize", {"protocolVersion": "2024-11-05",
                                         "capabilities": {}})

    def tools(self) -> list:
        r = self._send("tools/list")
        return r.get("result", {}).get("tools", [])

    def call(self, name: str, args=None) -> str:
        r = self._send("tools/call", {"name": name, "arguments": args or {}})
        if "error" in r:
            return f"错误:{r['error']}"
        res = r.get("result", {})
        content = res.get("content", [])
        return "\n".join(c.get("text", "") for c in content
                         if c.get("type") == "text")

    def close(self):
        if self.proc is not None:
            try:
                self.proc.stdin.close()
                self.proc.terminate()
            except Exception:
                pass


class MCPClient:
    def __init__(self, name: str, url: str):
        self.name = name
        self.url = url
        self._id = 0
        self._session = None   # Streamable-HTTP 会话 id(initialize 后返回,后续每请求回传)

    def _send(self, method: str, params=None):
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id,
                           "method": method, "params": params or {}}).encode("utf-8")
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        req = urllib.request.Request(self.url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            sid = r.headers.get("Mcp-Session-Id")
            if sid:
                self._session = sid
            raw = r.read().decode("utf-8")
            # 兼容两种响应:纯 JSON,或 SSE(data: ...)。剥掉 SSE 前缀取 JSON。
            if raw.lstrip().startswith("data:"):
                data_lines = [ln[5:].strip() for ln in raw.splitlines()
                              if ln.startswith("data:")]
                raw = "\n".join(data_lines)
            return json.loads(raw)

    def initialize(self):
        return self._send("initialize", {"protocolVersion": "2024-11-05",
                                         "capabilities": {}})

    def tools(self) -> list:
        r = self._send("tools/list")
        return r.get("result", {}).get("tools", [])

    def call(self, name: str, args=None) -> str:
        r = self._send("tools/call", {"name": name, "arguments": args or {}})
        res = r.get("result", {})
        # 若返回 error(如远端报错),尝试读取并返回
        if "error" in r:
            return f"错误:{r['error']}"
        content = res.get("content", [])
        return "\n".join(c.get("text", "") for c in content
                         if c.get("type") == "text")


def _parse_stdio_command(c: dict) -> list:
    """从配置里解析 stdio 命令。支持:
      {"transport":"stdio","command":"uvx something ..."} → 按空格/shlx 拆
      {"transport":"stdio","command":["uvx","something"]} → 直接用
    注意:mc-wiki 等常带 Python 包名。command 为字符串时交给 shlex 拆。"""
    cmd = c.get("command")
    if isinstance(cmd, list):
        return [str(x) for x in cmd]
    if isinstance(cmd, str):
        import shlex
        return shlex.split(cmd)
    return []


def _build_client(c: dict):
    """按配置的 transport 构造 MCP 客户端(HTTP 或 stdio)。返回客户端实例或 None。"""
    transport = (c.get("transport") or "http").strip().lower()
    name = (c.get("name") or "").strip()
    if transport in ("stdio", "local", "command", "process"):
        cmd = _parse_stdio_command(c)
        if cmd:
            return MCPStdioClient(name, cmd)
        return None
    url = (c.get("url") or "").strip()
    if not url:
        return None
    return MCPClient(name, url)


def connect_mcp_clients(clients: list) -> tuple:
    """连接一组 MCP 服务器,返回 (mcp_schemas, caller_map)。
    clients = [{name, url}](HTTP) 或 [{name, transport:'stdio', command:...}](stdio)。
    mcp_schemas 为合并后的工具 schema(名字带 mcp__ 前缀);
    caller_map[工具全名] = 可调用函数(fn(**args) -> str)。连接失败则跳过该服务器。"""
    mcp_schemas = []
    caller_map = {}
    for c in clients or []:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        try:
            client = _build_client(c)
            if client is None:
                continue
            client.initialize()
            for t in client.tools():
                full = f"mcp__{name}__{t['name']}"
                mcp_schemas.append({
                    "name": full,
                    "description": t.get("description", f"MCP 工具 {name}::{t['name']}"),
                    "parameters": t.get("inputSchema", {"type": "object",
                                                        "properties": {}, "required": []}),
                })
                caller_map[full] = (client, t["name"])
        except Exception:
            continue
    return mcp_schemas, caller_map


def mcp_tool_call(caller_map: dict, full_name: str, args: dict) -> str:
    """按 mcp__ 全名调用对应 MCP 服务器工具。"""
    client = caller_map[full_name]
    client, real_name = client
    try:
        return client.call(real_name, args)
    except Exception as e:
        return f"错误:调用 MCP 工具 {full_name} 失败:{type(e).__name__}: {e}"
