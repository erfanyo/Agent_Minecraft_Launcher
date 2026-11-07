"""Permission-aware tool execution, independent of chat widgets."""
import json
from typing import Callable, cast
from launcher_app.ai.ai_actions import ALWAYS_CONFIRM_ACTIONS, require_launcher_write, require_workspace_write
from launcher_app.ai.tool_catalog import WRITE_TOOLS, CONFIRM_TOOLS

def build_executor(settings: dict, progress_cb: Callable | None = None,
                   confirm_action: Callable[[str, str], bool] | None = None,
                   notice_cb: Callable[[str], None] | None = None,
                   auto_confirm_tools: set | None = None) -> Callable[[str, dict], str]:
    """构造工具执行器:LLM 只能"提议",真正执行在这里,权限检查也在这里。
    多余参数会被过滤(模型幻觉传错参数不报错,只调它真需要的)。
    progress_cb(done, total) 若提供,把底层下载(装 Mod 等)进度传给界面(左下角圆环)。
    confirm_action(name, preview) 由 GUI 提供时，会在执行高影响动作前让用户确认。
    auto_confirm_tools: 给【没有可交互确认通道】的调用方(如游戏内 /ai)用——集合里的工具名
      表示"调用方已按玩家身份判定过权限、且玩家主动发起",直接执行(仍写操作记录);
      不在集合里、又需要确认的动作会返回明确说明,而不是让模型去谎称"启动器里会弹确认框"。"""
    import inspect
    import launcher_app.ai.agent_tools as agent_tools
    # MCP 客户端:连接配置的外部 MCP 服务器,AI 可调用它们暴露的工具
    _mcp_callers = {}
    try:
        from launcher_app.browser.mcp_client import connect_agent_clients
        _mcp_schemas, _mcp_callers = connect_agent_clients(settings)
    except Exception:
        _mcp_callers = {}
    # Continuous repair is a desktop-chat experience: it needs the confirmation channel
    # for migration/high-impact decisions. Headless/CLI/game-chat callers keep per-action gates.
    continuous = (settings.get("ai_confirmation_mode", "per_action") == "backup_continue" and
                  confirm_action is not None)
    auto_snapshots = set()
    repair_environments = {}
    autonomy_notified = False
    snapshot_before = {
        'repair_instance_core', 'complete_instance_files', 'reset_instance',
        'install_mod', 'install_mods', 'set_mod_enabled', 'replace_mod_version',
    }

    def notify_continuous(backup_note=""):
        nonlocal autonomy_notified
        if autonomy_notified:
            return
        autonomy_notified = True
        if notice_cb:
            saved = ("已保存当前实例的完整恢复点。" if backup_note else
                     "这项修改可以通过操作记录回退。")
            scope = ("启动器程序、设置和游戏实例" if settings.get("ai_permission") == "workspace_write"
                     else "启动器设置和游戏实例")
            notice_cb(saved + f"接下来 AI 可能在你已允许的{scope}中下载或调整文件、修改设置并启动验证；"
                      "它会持续处理到可以交付、失败或达到本轮时间预算。")

    def executor(name: str, args: dict) -> str:
        action_preview = ""
        undo = {}
        core_runtime_issue = False
        plugin_policy = {}
        try:
            import launcher_app.extensions.plugin_manager as plugin_manager
            plugin_policy = plugin_manager.TOOL_POLICIES.get(name, {})
        except Exception:
            pass
        mcp_annotations = {}
        if name in _mcp_callers:
            entry = _mcp_callers[name]
            if len(entry) >= 3 and isinstance(entry[2], dict):
                mcp_annotations = entry[2]
        mcp_write = name in _mcp_callers and mcp_annotations.get("readOnlyHint") is not True
        if name.startswith('mcp__browser__'):
            from launcher_app.browser.browser_agent import validate
            try:
                validate(name.removeprefix('mcp__browser__'), args)
            except ValueError as error:
                return str(error)
        if name == 'repair_instance_core':
            try:
                core = json.loads(agent_tools.inspect_instance_core(str(args.get('instance') or '')))
            except Exception as exc:
                return f'没有开始修补：核心核验未完成（{type(exc).__name__}: {exc}）。'
            status = core.get('status')
            if status == 'verified':
                log_text = agent_tools.read_instance_log(str(args.get('instance') or ''), tail=1200)
                lowered = log_text.lower()
                missing_core = ("actual version: '[missing]'" in lowered and
                                any(f"mod id: '{mod_id}'" in lowered for mod_id in
                                    ('minecraft', 'neoforge', 'forge', 'fabricloader')))
                if not missing_core:
                    return '没有执行核心修补：文件和最近一次加载记录都没有显示核心故障，应继续检查 Mod 或配置。'
                core_runtime_issue = True
            if status != 'issues_found':
                if not core_runtime_issue:
                    return '没有执行核心修补：目前没有足够证据证明核心损坏。'
        confirmation_candidate = (name in CONFIRM_TOOLS or plugin_policy.get("confirm") or mcp_write)
        auto_continue = (continuous and name in CONFIRM_TOOLS and
                         name not in ALWAYS_CONFIRM_ACTIONS and
                         not plugin_policy.get("confirm") and not mcp_write)
        needs_confirm = confirmation_candidate and not auto_continue
        if confirmation_candidate:
            from launcher_app.ai.ai_action_log import preview
            action_preview = preview(name, args, settings.get("ai_response_style", "plain"))
            if core_runtime_issue and settings.get("ai_response_style", "plain") == "plain":
                action_preview = ('重新建立这个实例的游戏与加载器关系。现有文件会先保留，'
                                  '存档、Mod 和设置不会删除。')
            if name == "set_setting":
                from settings import load_settings
                key = str(args.get("key", ""))
                undo = {"kind": "setting", "key": key, "value": load_settings().get(key)}
        if needs_confirm:
            if confirm_action is None:
                if name not in (auto_confirm_tools or ()):
                    # 没有确认通道时,绝不能让模型以为"启动器里会弹确认框"(那里并没有
                    # 这个待确认项,玩家会白等)。这里把事实说清楚,并指出正确入口。
                    return (f'这项操作({name})需要你确认,但当前通道没有确认界面'
                            '(弹不出确认框):请在启动器的 AI 对话界面里继续。')
                # 在 auto_confirm_tools 里:调用方(如游戏内 /ai)已按玩家身份判定过权限,
                # 且玩家是主动发起的 → 直接执行(下面 finish() 仍会写操作记录)。
            elif not confirm_action(name, action_preview):
                result = "用户取消了这项操作，未做任何修改。"
                from launcher_app.ai.ai_action_log import record
                record(name, args, result, approved=False, undo=undo)
                return result
            if notice_cb:
                notice_cb('已同意，正在处理：' + action_preview)

        def finish(result) -> str:
            result = str(result)
            if action_preview:
                from launcher_app.ai.ai_action_log import record
                record(name, args, result, approved=True, undo=undo)
            return result

        # MCP 工具(mcp__服务器__工具)优先路由到对应 MCP 服务器
        if name in _mcp_callers:
            if mcp_write:
                require_launcher_write(settings)
            from launcher_app.browser.mcp_client import mcp_tool_call
            return finish(mcp_tool_call(_mcp_callers, name, args))
        # create_plugin:生成启动器插件(语法校验 + 落盘 plugins/<name>.py)——写操作,需工作区写权限
        if name == "create_plugin":
            require_workspace_write(settings)   # 只读权限 → 拒绝
            import launcher_app.extensions.plugin_manager as plugin_manager
            r = plugin_manager.save_plugin(str(args.get("name", "")), str(args.get("code", "")))
            if r.get("ok"):
                aud = r.get("audit") or {}
                # 展示该插件 import/调用了什么(供判断是否恶意),让 AI 转告用户检查
                note = ""
                if aud.get("imports"):
                    note += "\n⚠️ 该插件 import: " + ", ".join(aud["imports"])
                if aud.get("danger_calls"):
                    note += "\n⚠️ 该插件调用: " + ", ".join(aud["danger_calls"])
                if note:
                    note += "\n(请确认这些是合理用途再启用;AI 生成的插件默认未审核)"
                return finish(f"✅ 已生成插件 {r['name']} → {r['path']}\n"
                        "已在 plugins/ 落盘,【重启启动器】后生效。可在 设置→插件 里启用/停用。" + note)
            return finish(f"❌ 插件生成失败:{r.get('error', '未知错误')}")
        # 插件注册的工具(plugin_manager.TOOLS)优先于内置 getattr 兜底
        plugin_entry = None
        try:
            import launcher_app.extensions.plugin_manager as plugin_manager
            plugin_entry = plugin_manager.TOOLS.get(name)
        except Exception:
            pass
        if plugin_entry is not None:
            if plugin_policy.get("write"):
                require_launcher_write(settings)
            _desc, _params, handler = plugin_entry
            try:
                return finish(handler(dict(args or {})))
            except Exception as e:
                return finish(f"插件工具执行失败:{type(e).__name__}: {e}")
        # 动态查找:函数名 == 工具名,便于测试打桩与后续扩展
        fn = getattr(agent_tools, name, None)
        if fn is None:
            return f"错误:未知工具 {name}"
        if name in WRITE_TOOLS:
            require_launcher_write(settings)  # 只读权限 → 直接拒绝
        if auto_continue and name in snapshot_before:
            instance = str(args.get("instance") or "").strip()
            if instance and instance not in auto_snapshots:
                if notice_cb:
                    notice_cb('正在保存当前实例，完成后会自动继续。')
                try:
                    backup_result = agent_tools.snapshot_instance(instance)
                except Exception as exc:
                    return finish(f"未开始修改：无法为当前实例建立恢复点（{type(exc).__name__}: {exc}）。")
                auto_snapshots.add(instance)
                from launcher_app.ai.ai_action_log import record
                record('snapshot_instance', {'instance': instance, 'automatic': True},
                       str(backup_result), approved=True)
                notify_continuous(backup_result)
        elif auto_continue and name != 'snapshot_instance':
            notify_continuous()
        # 灵感 #6:写操作前先自动备份(装 Mod 前防坏档);批量安装只备份一次
        if name in ("install_mod", "install_mods", "install_resource_pack", "install_shader"):
            try:
                backup_note = agent_tools.backup_instance(args.get("instance", ""))
            except Exception as e:
                backup_note = f"(备份失败:{e})"
        # 把 progress_cb 塞给支持它的下载工具(install_mod / install_mods / install_instance 等)
        out_args = dict(args)
        if progress_cb is not None and name in ("install_mod", "install_mods",
                                                "install_instance", "install_modpack",
                                                "install_resource_pack", "install_shader", 'download_cloud_archive'):
            try:
                sig = inspect.signature(fn)
                if "progress_callback" in sig.parameters:
                    out_args["progress_callback"] = progress_cb
            except (TypeError, ValueError):
                pass
        if notice_cb is not None and name in ('repair_instance_core', 'complete_instance_files', 'download_cloud_archive',
                                               'reset_instance'):
            try:
                sig = inspect.signature(fn)
                if 'status_callback' in sig.parameters:
                    out_args['status_callback'] = lambda message: notice_cb(
                        '处理进度：' + str(message))
            except (TypeError, ValueError):
                pass
        if name in ("install_mod", "install_mods"):
            try:
                result = fn(**out_args)
            except Exception as e:
                result = f"工具执行失败:{type(e).__name__}: {e}"
            return finish(f"[已自动备份:{backup_note}]\n{result}")
        # 过滤多余参数:只传函数签名里有的(模型经常幻觉多传参数)
        try:
            sig = inspect.signature(fn)
            kwargs = {k: v for k, v in out_args.items() if k in sig.parameters}
        except (TypeError, ValueError):
            kwargs = out_args
        from launcher_app.instances.diagnostic_tools import environment, repair_environment_scope, check_constraint
        instance = str(args.get('instance') or '').strip()
        repair_tools = {'set_mod_enabled', 'replace_mod_version', 'repair_instance_core',
                        'complete_instance_files', 'inspect_instance_core',
                        'find_compatible_mod_replacement', 'find_compatible_mod_versions'}
        if instance and name in repair_tools and instance not in repair_environments:
            repair_environments[instance] = environment(instance)
        scoped = repair_environments if name in repair_tools | {'launch_game', 'observe_game'} else {}
        with repair_environment_scope(scoped):
            if instance and instance in scoped:
                check_constraint(instance)
            result = fn(**kwargs)
        if continuous and name == 'snapshot_instance':
            instance = str(args.get('instance') or '').strip()
            if instance:
                auto_snapshots.add(instance)
            notify_continuous(str(result))
        return finish(result)

    return executor
