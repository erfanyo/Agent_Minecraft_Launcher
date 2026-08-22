# -*- coding: utf-8 -*-
"""
Agent Minecraft Launcher CLI(命令名:aml)

人和 AI 都能用的命令行接口。每条命令对应 agent_tools.py 里的一个函数,
AI 工具调用(tool calling)也注册的是这些函数——一次实现,两边通用。

用法示例:
  python cli.py instances
  python cli.py install 26.2 --loader fabric --optimize
  python cli.py mod search 钠 --game-version 26.2 --loader fabric
  python cli.py mod install 1.21.1-forge-52.1.16 jade
  python cli.py backup 1.21.1-forge-52.1.16
  python cli.py log 1.21.1-forge-52.1.16 --tail 50
  python cli.py settings get
  python cli.py settings set memory_gb 6
  python cli.py ai "这个实例装了什么 Mod?"
"""
import argparse
import sys


def main(argv=None):
    p = argparse.ArgumentParser(prog="aml", description="Agent Minecraft Launcher CLI")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("instances", help="列出已安装的实例")

    sp = sub.add_parser("install", help="创建实例(原版 + 可选加载器 + 可选 Mod)")
    sp.add_argument("version")
    sp.add_argument("--loader", choices=["fabric", "forge", "neoforge"], default="")
    sp.add_argument("--loader-version", default="")
    sp.add_argument("--shader", action="store_true")
    sp.add_argument("--optimize", action="store_true")

    msub = sub.add_parser("mod", help="Mod 操作").add_subparsers(dest="action", required=True)
    mi = msub.add_parser("install", help="给实例安装 Mod")
    mi.add_argument("instance")
    mi.add_argument("slug")
    mi.add_argument("--version", default="")
    ms = msub.add_parser("search", help="搜索 Mod(支持中文)")
    ms.add_argument("query")
    ms.add_argument("--game-version", default="")
    ms.add_argument("--loader", default="")
    ml = msub.add_parser("list", help="列出实例已装的 Mod")
    ml.add_argument("instance")

    sp = sub.add_parser("backup", help="备份实例(存档 zip + 模组列表)")
    sp.add_argument("instance")

    sp = sub.add_parser("log", help="查看实例最近的游戏日志")
    sp.add_argument("instance")
    sp.add_argument("--tail", type=int, default=80)

    sp = sub.add_parser("crash", help="查看实例最新的崩溃报告")
    sp.add_argument("instance")

    ssub = sub.add_parser("settings", help="读写设置").add_subparsers(dest="action", required=True)
    ssub.add_parser("get")
    ss = ssub.add_parser("set")
    ss.add_argument("key")
    ss.add_argument("value")

    sp = sub.add_parser("ai", help="问 AI 一句话(可带工具)")
    sp.add_argument("question")
    sp.add_argument("--with-tools", action="store_true")

    args = p.parse_args(argv)
    return _dispatch(args)


def _dispatch(args) -> int:
    import agent_tools

    if args.command == "instances":
        print(agent_tools.list_instances())
    elif args.command == "install":
        print(agent_tools.install_instance(
            args.version, loader=args.loader, loader_version=args.loader_version,
            shader=args.shader, optimize=args.optimize, status=lambda m: print("  ", m)))
    elif args.command == "mod":
        if args.action == "search":
            print(agent_tools.search_mods(args.query, args.game_version, args.loader))
        elif args.action == "list":
            print(agent_tools.list_mods(args.instance))
        elif args.action == "install":
            print(agent_tools.install_mod(args.slug, args.instance, args.version))
    elif args.command == "backup":
        print(agent_tools.backup_instance(args.instance))
    elif args.command == "log":
        print(agent_tools.read_instance_log(args.instance, tail=args.tail))
    elif args.command == "crash":
        print(agent_tools.read_crash_report(args.instance))
    elif args.command == "settings":
        if args.action == "get":
            print(agent_tools.get_settings())
        elif args.action == "set":
            print(agent_tools.set_setting(args.key, args.value))
    elif args.command == "ai":
        _cmd_ai(args)
    return 0


def _cmd_ai(args):
    from assistant import build_executor, chat_with_tools
    from settings import load_settings

    settings = load_settings()
    executor = build_executor(settings)
    messages = [{"role": "system", "content": "你是 Agent Minecraft Launcher 的助手,用中文简洁回答。"},
                {"role": "user", "content": args.question}]
    tools = None if not args.with_tools else _tools()
    reply = chat_with_tools(messages, settings, tools, executor)
    print(reply)


# 工具 schema 与 assistant 里的一致(避免循环导入,这里延迟引用)
def _tools():
    from assistant import TOOLS
    return TOOLS


if __name__ == "__main__":
    sys.exit(main())
