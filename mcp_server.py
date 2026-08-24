# -*- coding: utf-8 -*-
"""
MCP Server(轻量,零第三方依赖):把启动器的工具(agent_tools)暴露成 MCP 工具。

**MCP = Model Context Protocol**(Anthropic 提出),让外部 AI 宿主(Claude Desktop / VS Code /
其它 MCP 客户端 / 启动器自己的 AI)能远程调用启动器的能力(列实例/装 Mod/查日志/启动等)。

本实现**手写 JSON-RPC 2.0 over stdio**(MCP 最常用的传输),不引入 `mcp` 依赖:
- 走 stdin/stdout:宿主 `/path/python main.py --mcp` 拉起本进程,一行一个 JSON-RPC 消息。
- 支持:initialize / notifications/initialized / tools/list / tools/call / ping。

工具来源 = `agent_tools`(和启动器 AI 内置工具同一套,"文本进→文本出"),
schema 由函数签名 + 描述表生成;调用时按签名过滤参数(与 assistant 执行器一致)。
"""
import inspect
import json
import sys

import agent_tools


# 简短描述(没有描述用签名兜底);后续可换成 assistant.TOOLS 里的完整描述
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


def _type_name(t):
    return {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}.get(
        getattr(t, "__name__", "str"), "string")


def _schema_for(name):
    """由函数签名生成 inputSchema:参数名→类型;有默认值的可选。"""
    fn = agent_tools.TOOL_FUNCS.get(name)
    if fn is None:
        return {"type": "object", "properties": {}, "required": []}
    props = {}
    required = []
    for pname, p in inspect.signature(fn).parameters.items():
        if pname in ("status", "status_callback", "progress_callback", "game_dir"):
            continue   # 内部回调/缺省目录,不暴露
        props[pname] = {"type": _type_name(p.annotation)}
        if p.default is inspect.Parameter.empty:
            required.append(pname)   # 有默认值=可选
    return {"type": "object", "properties": props, "required": required}


def _tool_list():
    out = []
    for name in agent_tools.TOOL_FUNCS:
        out.append({
            "name": name,
            "description": _TOOL_DESC.get(name, f"调用启动器工具 {name}"),
            "inputSchema": _schema_for(name),
        })
    return out


def _call(name, args):
    fn = getattr(agent_tools, name, None)
    if fn is None:
        return f"错误:未知工具 {name}"
    try:
        kwargs = {k: v for k, v in (args or {}).items()
                  if k in inspect.signature(fn).parameters}
        return str(fn(**kwargs))
    except Exception as e:
        return f"错误:工具 {name} 调用失败:{type(e).__name__}: {e}"


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
        m_id = msg.get("id")
        method = msg.get("method")
        if method == "initialize":
            resp = {"jsonrpc": "2.0", "id": m_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "AMCL", "version": "0.1"}}}
        elif method.startswith("notifications/"):
            continue   # 通知无响应
        elif method == "ping":
            resp = {"jsonrpc": "2.0", "id": m_id, "result": {}}
        elif method == "tools/list":
            resp = {"jsonrpc": "2.0", "id": m_id, "result": {"tools": _tool_list()}}
        elif method == "tools/call":
            p = msg.get("params") or {}
            name = p.get("name")
            text = _call(name, p.get("arguments"))
            resp = {"jsonrpc": "2.0", "id": m_id, "result": {
                "content": [{"type": "text", "text": text}]}}
        else:
            resp = {"jsonrpc": "2.0", "id": m_id,
                    "error": {"code": -32601, "message": f"未知方法 {method}"}}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    serve()
