"""Headless local/cloud response routing and shared tool-call loop."""
import requests
from typing import Callable, cast
from launcher_app.ai.assistant_defaults import LOCAL_MODEL_ID
from launcher_app.ai.tool_catalog import TOOLS, CLOUD_MAX_TOKENS, mount_tools_for
from launcher_app.ai.tool_executor import build_executor

def chat_completion(messages: list, base_url: str, api_key: str, model: str) -> str:
    """调用 OpenAI 兼容的 /chat/completions,返回回复文本"""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.post(url, headers=headers,
                         json={"model": model, "messages": messages}, timeout=180)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

def chat_with_tools(messages: list, settings: dict, tools: list[dict] | None,
                    executor: Callable[[str, dict], str], max_rounds=None,
                    on_tool=None, on_user_ask=None, return_messages=False,
                    cancel_event=None, stop_after_first_tool=False):
    """Shared progress-bounded loop; max_rounds is a deprecated compatibility argument."""
    from launcher_app.ai.ai_run import run
    return run(messages, settings, tools, executor, max_rounds=max_rounds,
               on_tool=on_tool, on_user_ask=on_user_ask,
               return_messages=return_messages, cancel_event=cancel_event,
               max_tokens=CLOUD_MAX_TOKENS,
               stop_after_first_tool=stop_after_first_tool)

def _cloud_available_settings(settings: dict) -> bool:
    """云端/兼容通道是否可用(与 dock._cloud_available 同逻辑,headless 版)。"""
    base = (settings.get("ai_cloud_base_url") or settings.get("ai_base_url") or "").strip()
    if not base.startswith(("http://", "https://")):
        return False
    h = base.split("://", 1)[-1].split("/", 1)[0].lower()
    host = h.split("]")[0][1:] if h.startswith("[") else h.split(":")[0]
    if host in ("localhost", "127.0.0.1", "::1") or host.startswith("127.0.0.1"):
        return True
    key = (settings.get("ai_cloud_api_key") or settings.get("ai_api_key") or "").strip()
    return bool(key)

def _cloud_settings_headless(settings: dict) -> dict:
    s = settings
    if (s.get("ai_cloud_base_url") or "").strip():
        return {**s,
                "ai_provider": s.get("ai_cloud_provider", "deepseek"),
                "ai_base_url": s.get("ai_cloud_base_url") or "",
                "ai_api_key": s.get("ai_cloud_api_key") or "",
                "ai_model": s.get("ai_cloud_model") or ""}
    return s

def _local_model_downloaded() -> bool:
    try:
        import launcher_app.ai.model_registry as model_registry
        return model_registry.is_downloaded(LOCAL_MODEL_ID)
    except Exception:
        return False

def _cloud_chat(text: str, settings: dict, context: str = "",
                on_tool: Callable | None = None,
                force_tools: list | None = None,
                executor: Callable[[str, dict], str] | None = None) -> str:
    """云端带工具对话(复用 chat_with_tools)。context = 给 AI 的系统提示(如游戏内实例上下文)。
    force_tools: 始终挂上的工具名(如游戏内必须的 send_game_command),不被按关键词裁剪。"""
    cs = _cloud_settings_headless(settings)
    if not _cloud_available_settings(cs):
        return ("这个任务需要联网的云端模型。请在 设置→AI 助手 里配置云端服务(如 DeepSeek)。")
    tools = mount_tools_for(text, cs) or []
    if force_tools:
        by_name = {t["function"]["name"]: t for t in tools}
        for n in force_tools:
            if n not in by_name:
                t = next((x for x in TOOLS if x["function"]["name"] == n), None)
                if t:
                    tools = tools + [t]
                    by_name[n] = t
    sys_text = context or ("你是 Agent Minecraft 启动器的 AI 助手,用中文简洁回答用户。")
    msgs = [{"role": "system", "content": sys_text}, {"role": "user", "content": text}]
    exec_ = executor or build_executor(cs)
    try:
        # _cloud_chat 始终以 return_messages=False 调用 chat_with_tools → 返回 str
        return cast(str, chat_with_tools(msgs, cs, tools, exec_, max_rounds=12,
                                         on_tool=on_tool))
    except Exception as e:
        return f"(AI 请求失败:{type(e).__name__})"

def _human_wrap_result(tool_name: str, tool_result: str) -> str:
    """转人话失败时的兜底:把工具结果用大白话包装,去掉「✅ 已执行「工具名」」这类内部术语。
    结果本身可读(如「(1.20.1 没有 mods 目录)」)就直接给;是清单/多行就加一句引导。"""
    r = (tool_result or "").strip()
    if not r:
        return "已完成,但没有返回具体内容。"
    lines = [ln for ln in r.splitlines() if ln.strip()]
    # 结果是单行括号说明(如"(x 没有 mods 目录)")→ 去掉外层括号直接给
    if len(lines) == 1 and lines[0].startswith("(") and lines[0].endswith(")"):
        return lines[0][1:-1] + "。"
    if len(lines) == 1:
        return lines[0]
    # 多行清单 → 一句话 + 内容
    return f"查到 {len(lines)} 项:\n" + "\n".join(f"· {ln}" for ln in lines[:30])

def _synthesize_tool_reply(user_text: str, tool_name: str, tool_result: str,
                           settings: dict, context: str = "",
                           executor: Callable[[str, dict], str] | None = None,
                           engine=None) -> str:
    """本地工具执行完 → 把工具结果「转成人话」正式回答用户,而不是裸奔原始结果。
    转人话这一步当成一个新的小请求再走一遍 route()(与首轮一致的混合路由):
    本地模型够就本地总结,否则按 ai_strategy 落云端总结;两条都失败才回退到
    「✅ 已执行 + 结果」兜底。这样本地/云端/hybrid 三档的回复质量一致,不再只给工具输出。
    engine: 已在跑的 GrammarToolEngine(复用,不起新进程);不给则临时起一个本地总结。"""
    summary_prompt = (
        f"用户的问题是:{user_text}\n"
        f"我已经调用工具「{tool_name}」并拿到结果:\n{tool_result}\n"
        "请把上面的结果总结成给用户的正式中文回答:直接回答用户的问题,"
        "重点说结论和影响,不要罗列原始数据/日志/JSON,不要重复工具名。简洁(1-3 句)。")
    # 兜底:去掉「✅ 已执行「工具名」」这类内部术语,把结果用大白话包装(不裸奔工具原文)。
    fallback = _human_wrap_result(tool_name, tool_result)
    try:
        from launcher_app.ai.task_router import route
        strategy = str(settings.get("ai_strategy", "local_first") or "local_first")
        have_cloud = _cloud_available_settings(settings)
        # 转人话是"总结/解释"类任务:交给 route() 决定本地还是云端(难度判定会把它判为易/未知)
        decision = route(summary_prompt, strategy=strategy, have_cloud=have_cloud,
                         have_local=_local_model_downloaded(), follow_up=True)
        target = decision.get("target", "cloud")
        if target in ("local", "chat", "rule") and _local_model_downloaded():
            try:
                if engine is not None:
                    rep = engine.chat(summary_prompt, context=context)
                else:
                    from launcher_app.ai.local_ai import GrammarToolEngine
                    eng = GrammarToolEngine(model_id=LOCAL_MODEL_ID)
                    eng.start()
                    try:
                        rep = eng.chat(summary_prompt, context=context)
                    finally:
                        try:
                            eng.stop()
                        except Exception:
                            pass
                if rep and rep.strip() and "已执行" not in rep[:8]:
                    return rep
            except Exception:
                pass
        if have_cloud:
            rep = _cloud_chat(summary_prompt, settings, context, None, None, executor)
            if rep and rep.strip():
                return rep
    except Exception:
        pass
    return fallback

def route_answer(text: str, settings: dict, context: str = "",
                 on_tool: Callable | None = None,
                 force_tools: list | None = None,
                 executor: Callable[[str, dict], str] | None = None) -> str:
    """headless AI 路由:按 ai_strategy 用启动器 AI(规则 → 本地对话/工具 → 云端带工具)作答。
    复用 task_router 决策 + 启动器工具链;不依赖 GUI 信号。供游戏内 AI 等复用。
    context = 给 AI 的系统提示(可含当前实例等游戏上下文);on_tool(name,args,result) 可选回调。
    force_tools: 始终挂上的工具名(如游戏内必须的 send_game_command)。"""
    from launcher_app.ai.task_router import route, match_rule
    from launcher_app.ai.local_ai import GrammarToolEngine, build_launcher_context
    strategy = str(settings.get("ai_strategy", "local_first") or "local_first")
    have_cloud = _cloud_available_settings(settings)
    local_ready = _local_model_downloaded()
    decision = route(text, strategy=strategy, have_cloud=have_cloud, follow_up=False)
    target = decision.get("target", "cloud")
    if target == "rule":
        return match_rule(text) or "(没想好怎么答,稍后再试试)"

    if target in ("chat", "local"):
        if local_ready:
            try:
                eng = GrammarToolEngine()
                eng.start()
                try:
                    if target == "chat":
                        rep = eng.chat(text, context=context or build_launcher_context())
                    else:
                        from launcher_app.ai.local_ai import two_stage_tool_call, reasoning_effort_from_settings
                        call = two_stage_tool_call(text, context=context or build_launcher_context(),
                                                   engine=eng, effort=reasoning_effort_from_settings())
                        name = call.get("name", "")
                        args = call.get("arguments", {})
                        if not name:
                            return "(本地模型未给出明确动作)"
                        result = str((executor or build_executor(settings))(name, args))
                        if on_tool:
                            on_tool(name, args, result)
                        # 转人话:按混合路由把工具结果总结成正式回答,不再裸奔原始结果
                        rep = _synthesize_tool_reply(
                            text, name, result, settings,
                            context=context or build_launcher_context(),
                            executor=executor)
                except Exception:
                    rep = ""
                if rep and rep.strip():
                    return rep
                if have_cloud:
                    return _cloud_chat(text, settings, context, on_tool, force_tools, executor)
                return "(本地模型未成功,且无可用云端服务。)"
            except Exception:
                pass
        if have_cloud:
            return _cloud_chat(text, settings, context, on_tool, force_tools, executor)
        return ("本地模型未下载,且当前没有可用的云端服务。可在 设置→AI 助手 里配置云端(如 DeepSeek)。")

    # cloud / ask:落云端带工具(ask_user 由 chat_with_tools 的 on_user_ask 处理;无交互通道时降级)
    return _cloud_chat(text, settings, context, on_tool, force_tools, executor)

def _friendly_cloud_error(e: Exception) -> str:
    """把云端请求异常翻译成业务化中文提示(参考 _cloud_unavailable_hint 风格,不抛技术栈)。

    分类:
      - HTTPError 401 → API Key 无效/未配置;402 → 余额不足;404 → 接口地址/模型名不存在;
        429 → 太频繁;其他 4xx/5xx → 服务返回错误码
      - ConnectionError / Timeout → 无法连接(网络/接口地址)
      - 其他 → 原样(保留排查信息)
    """
    import requests
    if isinstance(e, requests.exceptions.HTTPError):
        resp = getattr(e, "response", None)
        code = resp.status_code if resp is not None else None
        if code == 401:
            return "云端服务拒绝了请求:API Key 无效或未配置(设置 → AI 助手 → 检查密钥)。"
        if code == 402:
            return "云端服务返回 402:账户余额不足,请充值后再试。"
        if code == 404:
            return "云端服务返回 404:接口地址或模型名不存在,请检查设置里的接口地址/模型名。"
        if code == 429:
            return "云端服务返回 429:请求太频繁,请稍后再试。"
        return (f"云端服务返回错误 {code if code is not None else '?'}:"
                f"请检查设置(接口地址/模型名/密钥)是否正确。")
    if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return ("无法连接云端服务:请检查网络,或确认设置里的接口地址正确"
                "(可先在浏览器打开该地址验证)。")
    return str(e) or f"{type(e).__name__}"
