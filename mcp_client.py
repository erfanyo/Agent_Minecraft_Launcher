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
import urllib.request


class MCPClient:
    def __init__(self, name: str, url: str):
        self.name = name
        self.url = url
        self._id = 0

    def _send(self, method: str, params=None):
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id,
                           "method": method, "params": params or {}}).encode("utf-8")
        req = urllib.request.Request(self.url, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))

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


def connect_mcp_clients(clients: list) -> tuple:
    """连接一组 MCP 服务器,返回 (mcp_schemas, caller_map)。
    clients = [{name, url}, ...]。mcp_schemas 为合并后的工具 schema(名字带 mcp__ 前缀);
    caller_map[工具全名] = 可调用函数(fn(**args) -> str)。连接失败则跳过该服务器。"""
    mcp_schemas = []
    caller_map = {}
    for c in clients or []:
        name = (c.get("name") or "").strip()
        url = (c.get("url") or "").strip()
        if not name or not url:
            continue
        try:
            client = MCPClient(name, url)
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
