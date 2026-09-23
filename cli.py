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
  python cli.py server list
  python cli.py server status .minecraft/servers/server-abc123
  python cli.py server stop .minecraft/servers/server-abc123
  python cli.py server command .minecraft/servers/server-abc123 say hello
  python cli.py server properties .minecraft/servers/server-abc123
  python cli.py server properties set .minecraft/servers/server-abc123 motd "My Server"
  python cli.py server inspect my-pack.zip
  python cli.py server diagnose .minecraft/servers/server-abc123/logs/latest.log
  python cli.py server export-cmd .minecraft/servers/server-abc123
  python cli.py server launch .minecraft/servers/server-abc123
"""
import argparse
import json
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

    # ---- 服务端管理(headless,调 server_service) ----
    srv = sub.add_parser("server", help="服务端管理").add_subparsers(dest="srv_action", required=True)

    srv.add_parser("list", help="列出已管理的服务端")

    srv_status = srv.add_parser("status", help="查看服务端运行状态")
    srv_status.add_argument("root", help="服务端目录路径")

    srv_stop = srv.add_parser("stop", help="安全停止服务端")
    srv_stop.add_argument("root")

    srv_cmd = srv.add_parser("command", help="向服务端发送控制台指令")
    srv_cmd.add_argument("root")
    srv_cmd.add_argument("command", nargs="+", help="指令(如 say hello)")

    srv_props = srv.add_parser("properties", help="读取/修改 server.properties")
    srv_props.add_argument("root")
    srv_props.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"),
                           help="设置一个键值(如 --set motd 'Hello')")
    srv_props.add_argument("--json", action="store_true", help="以 JSON 格式输出")

    srv_inspect = srv.add_parser("inspect", help="扫描 ZIP/MRPACK 服务端包(不导入)")
    srv_inspect.add_argument("path", help="包文件路径")
    srv_inspect.add_argument("--json", action="store_true")

    srv_import = srv.add_parser("import", help="导入一个服务端包")
    srv_import.add_argument("path", help="包文件路径")
    srv_import.add_argument("--game-dir", default="")

    srv_diag = srv.add_parser("diagnose", help="解析日志/崩溃报告,诊断问题")
    srv_diag.add_argument("log", help="日志文件路径")
    srv_diag.add_argument("--mods-dir", default="", help="实例 mods 目录(可选,提升诊断精度)")

    srv_export = srv.add_parser("export-cmd", help="导出服务端启动命令行")
    srv_export.add_argument("root", help="服务端目录路径")
    srv_export.add_argument("--java", default="", help="Java 路径(不填则自动选择)")
    srv_export.add_argument("--bat", default="", help="同时写入 start.bat/start.sh 文件")

    srv_launch = srv.add_parser("launch", help="启动服务端(自动选 Java,后台托管)")
    srv_launch.add_argument("root", help="服务端目录路径")
    srv_launch.add_argument("--java", default="", help="Java 路径(不填则自动选择)")
    srv_launch.add_argument("--accept-eula", action="store_true",
                            help="自动同意 Minecraft EULA(无需交互确认)")

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
    elif args.command == "server":
        return _dispatch_server(args)
    return 0


# ================= 服务端 CLI =================
def _dispatch_server(args) -> int:
    import server_service
    from settings import load_settings

    action = args.srv_action

    if action == "list":
        from paths import GAME_DIR
        servers = server_service.list_servers(GAME_DIR)
        if not servers:
            print("没有已管理的服务端。用 'aml server import <zip>' 导入一个。")
        for s in servers:
            running = server_service.server_status(s.get("path", ""), probe=False)
            tag = " [运行中]" if running and running.get("running") else ""
            print(f"  {s.get('id', '?'):20s}  {s.get('loader', '?'):10s}  "
                  f"MC {s.get('minecraftVersion', '?'):8s}{tag}")
        return 0

    if action == "status":
        state = server_service.server_status(args.root, probe=True)
        if state is None:
            print("未管理或无法读取状态。")
        else:
            print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0

    if action == "stop":
        try:
            server_service.stop_server(args.root)
            print("已发送 stop 指令,等待服务端安全退出。")
        except Exception as e:
            print(f"停止失败: {e}", file=sys.stderr)
            return 1
        return 0

    if action == "command":
        cmd = " ".join(args.command)  # nargs="+"
        try:
            server_service.send_server_command(args.root, cmd)
            print(f"> {cmd}")
        except Exception as e:
            print(f"发送失败: {e}", file=sys.stderr)
            return 1
        return 0

    if action == "properties":
        if args.set:
            key, value = args.set
            result = server_service.apply_server_properties(
                args.root, {key: value}, allow_running=False)
            if result["ok"]:
                print(result["message"])
            else:
                print(f"失败: {result['message']}", file=sys.stderr)
                return 1
        else:
            props = server_service.read_server_properties(args.root)
            if args.json:
                print(json.dumps(props, ensure_ascii=False, indent=2))
            else:
                for k, v in sorted(props.items()):
                    print(f"  {k}={v}")
        return 0

    if action == "inspect":
        try:
            report = server_service.inspect_pack(args.path)
        except Exception as e:
            print(f"扫描失败: {e}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        else:
            print(f"文件数: {report.get('fileCount', '?')}")
            print(f"展开大小: {report.get('expandedBytes', 0) / 1024**2:.1f} MiB")
            print(f"加载器: {report.get('loader', '?')} / MC {report.get('minecraftVersion', '?')}")
            print(f"Java: {report.get('requiredJava', '待确认')}")
            print(f"SHA-256: {report.get('sha256', '?')}")
        return 0

    if action == "import":
        from paths import GAME_DIR
        gd = args.game_dir or GAME_DIR
        try:
            report = server_service.inspect_pack(args.path)
            server_service.import_server(args.path, gd, report["sha256"])
            print(f"导入完成: {report.get('minecraftVersion', '?')} / {report.get('loader', '?')}")
        except Exception as e:
            print(f"导入失败: {e}", file=sys.stderr)
            return 1
        return 0

    if action == "diagnose":
        try:
            with open(args.log, encoding="utf-8", errors="replace") as f:
                log_text = f.read()
        except Exception as e:
            print(f"读日志失败: {e}", file=sys.stderr)
            return 1
        print(server_service.diagnose_server_log(log_text, mods_dir=args.mods_dir))
        return 0

    if action == "export-cmd":
        _cmd_server_export(args)
        return 0

    if action == "launch":
        _cmd_server_launch(args)
        return 0

    print(f"未知服务端子命令: {action}", file=sys.stderr)
    return 1


def _cmd_server_export(args):
    import server_service
    from server_launch import build_launch_plan
    try:
        plan = build_launch_plan(args.root)
    except Exception as e:
        print(f"无法构建启动计划: {e}", file=sys.stderr)
        return
    java = args.java
    if not java:
        settings = {}
        try:
            from settings import load_settings
            settings = load_settings()
        except Exception:
            pass
        try:
            java, _ = server_service.select_server_java(
                plan, {}, settings, ".",
                status_callback=lambda m: print(f"  Java: {m}"))
        except Exception as e:
            print(f"自动选择 Java 失败: {e}", file=sys.stderr)
            return
    cmd = server_service.export_start_command(plan, java)
    print(f"启动命令: {cmd}")
    if args.bat:
        path = server_service.export_start_script(plan, java, args.bat)
        print(f"已写入: {path}")


def _cmd_server_launch(args):
    import server_service
    from server_launch import build_launch_plan, eula_accepted
    from server_eula import fetch_minecraft_eula, accept_minecraft_eula
    root = args.root
    try:
        plan = build_launch_plan(root)
    except Exception as e:
        print(f"启动计划失败: {e}", file=sys.stderr)
        return

    if not eula_accepted(root):
        if not args.accept_eula:
            print("服务端 EULA 尚未同意。用 --accept-eula 自动同意,或先运行 'aml server properties' 查看。")
            try:
                eula = fetch_minecraft_eula()
                print("--- Minecraft EULA ---")
                print(eula[:500] + ("..." if len(eula) > 500 else ""))
            except Exception:
                pass
            return
        accept_minecraft_eula(root)
        print("已自动同意 Minecraft EULA。")

    java = args.java
    if not java:
        settings = {}
        try:
            from settings import load_settings
            settings = load_settings()
        except Exception:
            pass
        try:
            java, _ = server_service.select_server_java(
                plan, {}, settings, ".",
                status_callback=lambda m: print(f"  Java: {m}"))
        except Exception as e:
            print(f"自动选择 Java 失败: {e}", file=sys.stderr)
            return

    try:
        state = server_service.start_server(root, java, plan["arguments"])
        print(f"服务端已启动(PID {state.get('pid')})。")
        print(f"关闭 aml 不会停止服务端。用 'aml server stop {root}' 停止。")
    except Exception as e:
        print(f"启动失败: {e}", file=sys.stderr)


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
