# -*- coding: utf-8 -*-
"""
任务路由与失败链路(规划 §1)。

架构:本地小模型 → 云端大模型 → 规则引擎 → 诚实认输(§1.4,每一层失败都有下一层,不能断链)

§1.2 难度判定(不用 token 数,用结构化信号):
  1. 任务类型难度清单:诊断 / 代码分析 / 多步规划 = 难;翻译 / 摘要 / 分类 = 易
  2. 输出格式匹配:能填进预设 JSON 槽位(即"能映射到某个工具")= 本地干,否则转云端
  3. 兜底信号:本地结果置信度低、超时、超长 → 自动转云端

§1.3 "转云端"的交互包装:用业务语言,不是技术提示。

AI 策略三档(ai_strategy,见 settings.DEFAULTS):
  - local_first(默认):本地优先,规则引擎回归"低置信兜底";困难任务交云端;
    关键词表预筛接不住的"未知难度"由本地模型评审器 route_by_model 判复杂度
    (easy 本地做 / hard 或低置信交云端 / 评审不可用→规则→云端,§3 B)
  - cloud_first:一切走云端;云端未配置 → 规则 → 本地(降级链不报错)
  - hybrid:现状关键词分流 + 规则兜底(模型评审校准在 route_by_model 落地后叠加)

追问降级(follow_up):规则/chat 答后用户追问 → 下一轮强制转模型,不再被低成本路径拦截。

模型评审器(route_by_model,§3 B / §2.2):
  - grammar 约束输出 {"difficulty":"easy|hard","confidence":0-1}(复用 build_gbnf 思路:
    用合成工具 schema 构造评审专用 GrammarToolEngine,零新增 local_ai 方法)
  - 本地模型不可用/未下载/超时/输出非法 → 返回 None,走规则兜底 → 云端
  - 引擎懒加载单例;探活 8090 端口复用已起的 llama-server(AI 对话框/翻译引擎),不起新进程

用法:
  from task_router import route, run_with_fallback, route_by_model
  decision = route("帮我看看日志")     # -> {"target": "local"|"cloud"|"rule"|"chat"|"ask", ...}
  decision = route("为什么崩了", strategy="cloud_first")
  result = run_with_fallback(text, local_engine, cloud_fn, rule_engine)
  j = route_by_model("帮我分析这个日志")  # -> {"difficulty": "hard", "confidence": 0.9} 或 None
"""
import re
import time

# ================= 难度判定(§1.2) =================

# 任务类型难度清单:命中关键词 = 难(转云端)
DIFFICULT_KEYWORDS = {
    "诊断": ["诊断", "为什么崩", "为啥崩", "崩溃原因", "分析崩溃", "闪退原因", "卡顿原因",
            "内存不足怎么", "性能问题", "深度分析", "帮我分析"],
    "代码分析": ["代码", "源码", "报错栈", "堆栈", "traceback", "exception", "报错信息分析"],
    "多步规划": ["先", "然后", "接着", "规划", "方案", "计划", "步骤", "流程",
              "帮我安排", "怎么做才", "怎么一步步"],
}
# 简单任务:命中关键词 = 易(本地可做)
EASY_KEYWORDS = {
    "翻译": ["翻译", "什么意思", "英文是", "中文是"],
    "摘要": ["摘要", "总结一下", "概括", "太长不看"],
    "分类": ["分类", "归类", "属于哪类", "是哪种"],
    "查询": ["查", "看看", "搜", "搜索", "找找", "多少材料", "怎么合成", "绑了"],
}

# 输出格式匹配:能映射到工具的指令往往含"动作动词 + 对象"
TOOL_VERBS = ["装", "安装", "删除", "备份", "启动", "创建", "下载", "查询", "修改",
              "设置", "发", "发送", "读取", "搜索", "列出", "比较",
              "看看", "看下", "查一下", "查查", "改成", "给我", "帮我看"]

# 歧义请求:需要问用户才能继续(小模型"过度自信"不爱问,路由层兜底)。
# 命中 → 直接让模型走 ask_user 工具,不让它瞎猜。
AMBIGUOUS_KEYWORDS = ["推荐", "该装哪些", "该装什么", "帮我选", "你决定", "随便",
                      "有什么建议", "哪个好", "推荐下", "推荐一下", "帮我看看该",
                      "优化mod", "优化 mod", "整合包推荐", "有什么mod推荐"]


def classify_difficulty(text: str) -> str:
    """难度判定:返回 "difficult" / "easy" / "unknown"。
    诊断/代码/多步规划 = difficult;翻译/摘要/分类 = easy;其余 unknown。"""
    for cat, kws in DIFFICULT_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                return "difficult"
    for cat, kws in EASY_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                return "easy"
    return "unknown"


def looks_tool_callable(text: str) -> bool:
    """输出格式匹配:指令是否像能映射到工具(动作动词开头/包含)。
    能映射 = 本地小模型可干;否则倾向云端。"""
    for v in TOOL_VERBS:
        if v in text:
            return True
    return False


# 简单对话/寒暄:本地模型自由回答即可(不需要工具,也不需要云端)。
# 命中 → target="chat",走本地 chat()(规划 §1.1:简单任务本地干)。
CHAT_KEYWORDS = ["你好", "您好", "hello", "hi ", "嗨", "谢谢", "多谢", "再见", "拜拜",
                 "辛苦了", "在吗", "你叫什么", "你是谁", "介绍", "有什么功能",
                 "是干什么", "是什么", "这软件", "这个启动器", "能用它做什么",
                 "能干什么", "有什么用", "咋用", "怎么用"]


def looks_simple_chat(text: str) -> bool:
    """是否为本地模型可直接回答的简单对话/基础介绍(寒暄、功能简介等)。"""
    t = text.strip().lower()
    if len(t) <= 4:   # "你好""hi""谢谢" 等超短句
        return True
    return any(kw in t for kw in CHAT_KEYWORDS)


# ================= 规则引擎(§4.8 FAQ 模糊匹配) =================

# 固定问答库:最稳、零成本。命中即答,不再上模型。
# 注意(2026-08-24 收敛):
#   - 关键词精确化:要求含动词/问句(怎么/如何/在哪…),避免宽泛词误伤;
#   - 已移除宽泛词:"java"/"Java"/"jdk"(Java 报错应走 诊断 → 云端,不该被 FAQ 拦下)、
#     裸"更新"(可能指更新 Mod/资源)、裸"联机"(可能指联机失败诊断)、"是什么"(泛问,交给模型)
#   - 每条带置信度:high = 精确命中直接答;low = 宽泛命中,放行给模型(见 match_rule)
#   - 答案已修正:帮助菜单已并入设置,"检查更新"位置改为「设置 → 检查更新」
RULE_FAQ = [
    # (关键词列表, 回答, 置信度 high/low)
    (["怎么下载", "如何下载", "下载游戏", "在哪下"], "下载实例:点左侧「下载」→ 选版本/加载器 → 开始下载。也可以直接跟我说「下载 1.21.1」,我会帮你建。", "high"),
    (["怎么联机", "如何联机", "多人游戏", "联机方案"], "联机:点「联机方案中心」,有局域网/端口转发/第三方平台三种方案对比。", "high"),
    (["检查更新", "升级启动器", "怎么更新", "如何更新"], "检查更新:菜单「设置 → 检查更新」(帮助已并入设置)。", "high"),
    (["离线模式", "正版登录", "账号登录"], "当前是离线模式,无需正版账号即可玩;正版登录正式版会加。", "high"),
    (["设置在哪", "配置在哪", "怎么设置"], "设置:主界面右上角齿轮。AI 设置、内存、语言都在里面。", "high"),
    (["有哪些功能", "能做什么", "这软件能干什么"], "我能帮你:装/查 Mod、查配方、读日志、诊断崩溃、发游戏指令、备份实例、管理设置。", "high"),
    (["新手", "怎么玩"], "新手引导:首次启动有引导向导;随时问我「XX 怎么用」就行。", "low"),
]


def _match_rule(text: str):
    """内部:返回 (回答, 置信度) 或 None(未命中)。"""
    tl = text.lower()
    for kws, answer, conf in RULE_FAQ:
        if any(kw.lower() in tl for kw in kws):
            return (answer, conf)
    return None


def match_rule(text: str) -> str | None:
    """规则引擎:高置信命中直接返回回答;低置信(宽泛词命中)返回 None,放行给模型。"""
    hit = _match_rule(text)
    if hit and hit[1] == "high":
        return hit[0]
    return None


def match_rule_any(text: str) -> str | None:
    """兜底用(失败链最后一步):任何置信度的 FAQ 命中都返回,比诚实认输强。"""
    hit = _match_rule(text)
    return hit[0] if hit else None


# ================= 模型评审器(local_first 核心,§3 B / §2.2) =================

# 评审用合成工具 schema:grammar 只约束结构(必填 difficulty/confidence),
# 值域(easy|hard、0~1)由 route_by_model 语义校验(结构 100% 合法,值不合法 → None 兜底)。
JUDGE_SCHEMAS = {
    "difficulty_judge": {
        "properties": {"difficulty": "string", "confidence": "number"},
        "required": ["difficulty", "confidence"],
    },
}
JUDGE_SYSTEM = (
    "你是 Minecraft 启动器 AI 的「任务难度评审器」。判断用户请求的难度:"
    "easy=简单任务(单步工具操作、查询、改设置、寒暄、翻译、摘要等,本地小模型能完成);"
    "hard=困难任务(诊断崩溃/日志、代码/报错分析、多步规划、需要深度推理)。"
    'difficulty 只能是 "easy" 或 "hard";confidence 是 0~1 的把握度(0.9=很有把握)。'
    '只输出 JSON:{"name": "difficulty_judge", "arguments": {"difficulty": "easy|hard", "confidence": 0.0}}'
)
# easy 判定要求的最低置信度;低于它 → "低置信转云端再判"(§2.2 双层保险)
JUDGE_CONF_THRESHOLD = 0.6

_judge_engine = None
_judge_engine_lock = None  # 惰性初始化


def _get_judge_engine():
    """评审用 GrammarToolEngine 懒加载单例(合成 schema + 评审 system prompt)。
    模型 id 跟随设置的 ai_local_model(仅内置模型可用;ollama/lmstudio → 启动失败返回 None)。"""
    global _judge_engine, _judge_engine_lock
    if _judge_engine is None:
        import threading
        _judge_engine_lock = threading.Lock()
        with _judge_engine_lock:
            if _judge_engine is None:
                from local_ai import GrammarToolEngine
                mid = None
                try:
                    from settings import load_settings
                    mid = (load_settings().get("ai_local_model") or "").strip()
                except Exception:
                    pass
                if not mid:
                    from local_ai import DEFAULT_MODEL_ID
                    mid = DEFAULT_MODEL_ID
                _judge_engine = GrammarToolEngine(model_id=mid,
                                                  schemas=JUDGE_SCHEMAS,
                                                  system_prompt=JUDGE_SYSTEM)
    return _judge_engine


def route_by_model(text: str, engine=None, timeout: int = 60) -> dict | None:
    """本地模型任务评审(§3 B):grammar 约束输出 {"difficulty":"easy|hard","confidence":0-1}。

    返回 {"difficulty", "confidence", "raw"} 或 None:
      - 模型未下载 / 内置引擎不可用(ollama/lmstudio)→ 快速失败(None,不起 llama-server)
      - 无已运行 llama-server 且启动失败 / 超时 / 输出解析失败 / 值域非法 → None
    None 表示"评审不可用",由调用方走规则兜底 → 云端(§2.2 降级链不报错)。

    engine: 可注入(测试/复用);None = 模块级懒加载单例。
    """
    if engine is None:
        try:
            engine = _get_judge_engine()
        except Exception:
            return None
    # 1) 模型/运行时可用性:未下载或非内置模型 → 快速失败
    try:
        import model_registry
        if not model_registry.is_downloaded(engine.model_id):
            return None
    except Exception:
        return None
    # 2) 探活已运行的 llama-server(8090,复用 AI 对话框/翻译引擎起的进程);没有才 start
    try:
        import requests
        if requests.get(f"{engine.base}/health", timeout=2).status_code != 200:
            engine.start()
    except Exception:
        try:
            engine.start()
        except Exception:
            return None
    # 3) grammar 工具调用:结构必对,值域语义校验
    try:
        call = engine.tool_call(text, timeout=timeout)
        args = (call or {}).get("arguments") or {}
        difficulty = str(args.get("difficulty", "")).strip().lower()
        try:
            confidence = float(args.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if difficulty not in ("easy", "hard"):
            return None                     # 值域非法 → 兜底
        confidence = max(0.0, min(1.0, confidence))
        return {"difficulty": difficulty, "confidence": confidence, "raw": call}
    except Exception:
        return None                         # 超时/解析失败 → 兜底


# ================= 路由决策 =================

def looks_ambiguous(text: str) -> bool:
    """歧义检测:命中"推荐/该装哪些/你决定"等 → 需要问用户,别让模型瞎猜。"""
    return any(kw in text for kw in AMBIGUOUS_KEYWORDS)


# 常见歧义场景 → 候选选项(给 ask_user 用;新场景往这里加)
_ASK_OPTIONS = {
    "mod": ["钠", "锂", "玉", "JEI", "更好的F3"],
    "优化": ["钠", "锂", "铁锭优化", "FastChest"],
    "光影": ["Iris", "BSL", "Complementary"],
    "整合包": ["ATM10", "Better MC", "All of Fabric"],
}


def _ask_question_for(text: str) -> str:
    """从歧义请求提取要问的问题(业务语言)。"""
    if "整合包" in text:
        return "你想装哪个整合包?"
    if "光影" in text:
        return "你想要哪种光影?"
    if "优化" in text or "性能" in text:
        return "你想装哪些优化 Mod?"
    if "mod" in text.lower() or "模组" in text or "mods" in text.lower():
        return "你想装哪些 Mod?"
    return "你能说得具体一点吗?你想要我做什么?"


def _ask_options_for(text: str) -> list:
    """按场景给候选选项(没有合适场景就给空列表,用户可自由输入)。"""
    if "整合包" in text:
        return _ASK_OPTIONS["整合包"]
    if "光影" in text:
        return _ASK_OPTIONS["光影"]
    if "优化" in text or "性能" in text:
        return _ASK_OPTIONS["优化"]
    if "mod" in text.lower() or "模组" in text or "mods" in text.lower():
        return _ASK_OPTIONS["mod"]
    return []


def route(text: str, *, have_cloud: bool = True, have_local: bool = True,
          strategy: str = "local_first", follow_up: bool = False,
          use_judge: bool = True, judge_fn=None) -> dict:
    """决定任务走哪一层。返回 {"target": ..., "reason": ...}。
    target: "rule"(规则引擎直接答) / "chat"(本地简单对话) / "local"(本地工具) /
            "ask"(问用户) / "cloud"(云端)。

    strategy(ai_strategy 三档,见 settings.DEFAULTS):
      local_first(默认):本地优先——简单本地做、难交云端;规则低置信兜底
      cloud_first:一切走云端;云端未配置 → 规则 → 本地(降级链不报错)
      hybrid:现状关键词分流 + 规则兜底(模型评审校准后续叠加)

    use_judge(仅 local_first):关键词表预筛未接住的"未知难度"是否交本地模型评审
      (route_by_model)。测试/确定性场景可关;judge_fn 可注入自定义评审函数(测试用)。
      easy(置信 ≥ JUDGE_CONF_THRESHOLD)→ 本地;hard / 低置信 → 云端;
      评审不可用(None)→ 规则 FAQ(高置信)→ 云端兜底(§2.2 降级链)。

    follow_up(追问降级):规则/chat 答后用户追问 → 跳过规则与聊天捷径,强制转模型,
    避免被低成本路径反复拦截(见 assistant.py 接线)。

    优先级设计(关键,local_first/hybrid):
      0. 歧义请求(推荐/该装哪些)→ 直接 ask_user,不让模型瞎猜
      0b. 简单对话/寒暄(追问时仅超短句保留)→ 本地 chat
      0c. 含工具动词的指令(如"把内存改成 6G")→ 先本地工具,规则引擎不抢
      1. 难度判定(诊断/代码/多步规划)→ 云端
      2. 规则 FAQ(高置信命中直接答;低置信/追问 → 放行给模型)→ 低置信兜底
      2.5 模型评审(local_first 核心):未知难度 → 本地模型判复杂度(§3 B)
      3. 兜底 → 云端"""
    # 0. 歧义请求:需要用户选择 → ask_user(模型层面 + 路由层面双保险)
    if looks_ambiguous(text):
        return {"target": "ask", "reason": "歧义请求,需要问用户"}

    # ---- cloud_first:一切走云端;云端未配置 → 规则 → 本地(§2.3 降级链) ----
    if strategy == "cloud_first":
        if have_cloud:
            return {"target": "cloud", "reason": "云端优先策略,一切走云端"}
        ans = match_rule(text)
        if ans:
            return {"target": "rule", "reason": "云端未配置,规则兜底"}
        if looks_simple_chat(text):
            return {"target": "chat" if have_local else "cloud",
                    "reason": "云端未配置,本地简单对话兜底"}
        if looks_tool_callable(text):
            return {"target": "local" if have_local else "cloud",
                    "reason": "云端未配置,本地工具兜底"}
        return {"target": "local" if have_local else "cloud",
                "reason": "云端未配置,本地兜底"}

    # ---- local_first / hybrid:收敛后的分流(规则回到"低置信兜底"位) ----
    # 0b. 简单对话/寒暄/基础介绍 → 本地自由回答(追问时只保留超短寒暄,其余强制转模型)
    if (not follow_up or len(text.strip()) <= 4) and looks_simple_chat(text):
        if classify_difficulty(text) == "difficult":
            return {"target": "cloud" if have_cloud else "chat",
                    "reason": "看似闲聊实为复杂问题,转云端"}
        return {"target": "chat" if have_local else "cloud",
                "reason": "简单对话/介绍,本地可答"}
    # 0c. 含工具动词 = 明确的操作请求 → 优先本地工具(即使 FAQ 也命中)
    if looks_tool_callable(text):
        # 但若同时是"困难任务"(如"帮我分析怎么装mod")→ 云端
        if classify_difficulty(text) == "difficult":
            return {"target": "cloud" if have_cloud else "local",
                    "reason": "工具指令但属困难任务,转云端"}
        return {"target": "local" if have_local else "cloud",
                "reason": "含工具动词,本地小模型可处理"}
    # 1. 难度判定(先于规则:困难任务不该被 FAQ 拦下)
    difficulty = classify_difficulty(text)
    if difficulty == "difficult":
        return {"target": "cloud" if have_cloud else "local",
                "reason": "困难任务(诊断/代码/多步规划)转云端"}
    # 2. 规则 FAQ(高置信直接答;低置信放行给模型;追问时跳过 → 强制转模型)
    if not follow_up:
        ans = match_rule(text)
        if ans:
            return {"target": "rule", "reason": "命中固定问答库(高置信)"}
    # 2.5 模型评审(local_first 核心 §3 B):关键词表预筛未接住的"未知难度" →
    #     本地模型判复杂度:easy 且置信够 → 本地做;hard / 低置信 → 云端;
    #     评审不可用(None)→ 落入 3 兜底(规则低置信 FAQ + 云端,降级链不报错)
    if strategy == "local_first" and use_judge and have_local:
        j = judge_fn(text) if judge_fn is not None else route_by_model(text)
        if j is not None:
            conf = float(j.get("confidence", 0.0) or 0.0)
            if j.get("difficulty") == "easy" and conf >= JUDGE_CONF_THRESHOLD:
                return {"target": "local", "reason": f"模型评审:easy(置信 {conf:.2f})"}
            tag = "hard" if j.get("difficulty") == "hard" else "低置信"
            return {"target": "cloud" if have_cloud else "local",
                    "reason": f"模型评审:{tag}(置信 {conf:.2f})转云端"}
    # 3. 兜底:未知难度 → 云端
    return {"target": "cloud" if have_cloud else "local",
            "reason": "未知难度,云端兜底"}


# ================= 失败链路执行(§1.4) =================

def _wrap_cloud_offer(reason: str) -> str:
    """§1.3 转云端用业务语言包装,不是技术提示。"""
    return ("这个任务超出了我的基础能力,升级后可以完成,要不要试试?"
            "(或者你说'就用基础版凑合一下'也行)")


def run_with_fallback(text: str, local_engine=None, cloud_fn=None,
                      rule_engine=match_rule_any, timeout: float = 120.0,
                      ask_engine=None, strategy: str = "local_first") -> dict:
    """失败链路:本地小模型 → 云端大模型 → 规则引擎 → 诚实认输。
    每一层失败都有下一层,不能断链(§1.4)。
    strategy=cloud_first 时顺序为:云端 → 本地 → 规则 → 认输。

    参数:
      local_engine: 可调用,输入文本返回工具调用 dict(如 GrammarToolEngine.tool_call)
      cloud_fn:     可调用,输入文本返回云端回复字符串(失败抛异常或返回 None)
      rule_engine:  可调用,输入文本返回回答或 None(默认 match_rule_any:任何置信度兜底)
      ask_engine:   可调用,输入文本返回 ask_user 工具调用 dict;歧义请求时用它问用户
      strategy:     ai_strategy 三档(local_first/cloud_first/hybrid)

    返回 {"source": "ask"|"local"|"cloud"|"rule"|"give_up", "content": ..., "raw": ...}
    """
    # 0. 歧义请求 → 直接构造 ask_user 调用(不依赖小模型的指令遵循能力)。
    #    小模型"过度自信"不爱问用户(§8.1 实测),这里在架构层强制。
    if looks_ambiguous(text):
        question = _ask_question_for(text)
        options = _ask_options_for(text)
        return {"source": "ask",
                "content": {"name": "ask_user",
                            "arguments": {"question": question, "options": options}},
                "raw": None}

    if strategy == "cloud_first":
        # 云端优先:云端 → 本地 → 规则 → 认输
        if cloud_fn is not None:
            try:
                reply = cloud_fn(text)
                if reply:
                    return {"source": "cloud", "content": reply, "raw": reply}
            except Exception:
                pass
        if local_engine is not None:
            try:
                call = local_engine(text)
                if isinstance(call, dict) and call.get("name"):
                    return {"source": "local", "content": call, "raw": call}
            except Exception:
                pass
        ans = rule_engine(text)
        if ans:
            return {"source": "rule", "content": ans, "raw": None}
        return {"source": "give_up",
                "content": "我尽力了,这个问题暂时搞不定。你可以换个说法,或者到设置里换个更强的模型。"}

    # 1. 本地小模型(优先,§2.2 local_first 语义)
    if local_engine is not None:
        t0 = time.time()
        try:
            call = local_engine(text)
            if isinstance(call, dict) and call.get("name"):
                return {"source": "local", "content": call, "raw": call}
            # 模型没选工具 = 低置信度 → 转云端
        except Exception as e:
            # 本地失败(超时/解析失败等) → 转云端
            if time.time() - t0 > timeout:
                pass  # 超时
        # 本地不可用/失败,落到云端

    # 2. 云端大模型
    if cloud_fn is not None:
        try:
            reply = cloud_fn(text)
            if reply:
                return {"source": "cloud", "content": reply, "raw": reply,
                        "note": _wrap_cloud_offer("本地未能处理")}
        except Exception:
            pass

    # 3. 规则引擎(兜底保险:模型都失败后,FAQ 高低置信都试一次,尽量不认输)
    ans = rule_engine(text)
    if ans:
        return {"source": "rule", "content": ans, "raw": None}

    # 4. 诚实认输
    return {"source": "give_up",
            "content": "我尽力了,这个问题暂时搞不定。你可以换个说法,或者到设置里换个更强的模型。"}


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    use_judge = "--judge-demo" not in sys.argv[1:]   # 默认关,保持自测确定性/快速
    # 自测:路由决策 + 失败链路(用假引擎演示)
    print("==== 路由决策示例(local_first 默认,use_judge={})====".format(use_judge))
    samples = [
        "看看我有哪些实例",           # 本地(工具动词)
        "帮我查一下为什么崩了",       # 云端(诊断,难度判定在规则之前)
        "怎么下载游戏",               # 本地(工具)
        "把内存改成 6G",              # 本地
        "我想装几个mod,你帮我推荐下",  # ask(歧义)
        "我该装哪些优化mod",           # ask(歧义)
        "给我做个装mod的方案",        # 云端(规划)
        "今天天气怎么样",             # use_judge:本地(评审 easy)/ 关:云端(兜底)
        "怎么检查更新",               # 规则(高置信 FAQ,答案已修正:设置→检查更新)
        "检查更新",                   # chat(≤4字超短句先走本地简单对话捷径,不进 FAQ)
        "java 报错怎么办",            # 云端(java 已移出 FAQ → 诊断 → 云端)
        "新手"                        # chat(超短句;低置信 FAQ 仅在失败链兜底时命中)
    ]
    for s in samples:
        d = route(s, use_judge=use_judge)
        print(f"  [{d['target']:<6}] {s}  ({d['reason']})")

    print("\n==== 策略三档对比(route 入口)====")
    for s in ("把内存改成 6G", "帮我查一下为什么崩了"):
        row = [route(s, strategy=st, use_judge=False)["target"]
               for st in ("local_first", "cloud_first", "hybrid")]
        print(f"  {s} → local_first={row[0]} / cloud_first={row[1]} / hybrid={row[2]}")

    print("\n==== 追问降级(follow_up):规则答后追问 → 强制转模型 ====")
    d1 = route("怎么检查更新", use_judge=False)
    d2 = route("那检查更新后呢", follow_up=False, use_judge=False)
    d3 = route("那检查更新后呢", follow_up=True, use_judge=False)
    print(f"  首问:{d1['target']}(规则答) → 追问无标记:{d2['target']}(仍会再命中规则) "
          f"→ 追问带标记:{d3['target']} ({d3['reason']})")

    print("\n==== 降级链:cloud_first 未配云端 → 规则/本地(不报错)====")
    d3 = route("检查更新", strategy="cloud_first", have_cloud=False, use_judge=False)
    d4 = route("把内存改成 6G", strategy="cloud_first", have_cloud=False, use_judge=False)
    print(f"  检查更新 → {d3['target']} ({d3['reason']})")
    print(f"  把内存改成6G → {d4['target']} ({d4['reason']})")

    print("\n==== 失败链路示例(本地引擎抛异常→云端)====")
    def bad_local(t):
        raise RuntimeError("本地模型未就绪")
    def cloud(t):
        return f"[云端回复] {t} 的建议……"
    r = run_with_fallback("为什么我的游戏闪退", bad_local, cloud)
    print(f"  source={r['source']} content={r['content'][:60]}")

    print("\n==== 失败链路示例(全失败→规则兜底,再认输)====")
    r4 = run_with_fallback("检查更新", None, None)
    print(f"  source={r4['source']} content={r4['content'][:40]}")
    r5 = run_with_fallback("为什么我的游戏闪退", None, None)
    print(f"  source={r5['source']} content={r5['content'][:60]}")

    print("\n==== 歧义请求→ask_user(路由层兜底)====")
    def ask_engine(t):
        return {"name": "ask_user", "arguments": {"question": "你想装哪些 Mod?", "options": ["钠", "锂", "玉"]}}
    r3 = run_with_fallback("我想装几个mod,你帮我推荐下", None, None, ask_engine=ask_engine)
    print(f"  source={r3['source']} content={r3['content']}")

    if "--judge-demo" in sys.argv[1:]:
        print("\n==== 模型评审 route_by_model(真实本地模型,--judge-demo)====")
        judge_cases = [
            "看看我有哪些实例",            # easy(查询)
            "把内存改成 6G",               # easy(单步设置)
            "翻译一下这段英文",            # easy(翻译)
            "为什么我装了光影后游戏变卡了",  # hard(诊断)
            "帮我分析崩溃日志找原因",       # hard(诊断,关键词已覆盖→评审不触发,这里直接测函数)
            "今天天气怎么样",              # easy(简单问答)
        ]
        for s in judge_cases:
            j = route_by_model(s)
            print(f"  {s}\n    -> {j}")
        print("\n  route() 集成(local_first + 评审):")
        for s in ("今天天气怎么样", "为什么我装了光影后游戏变卡了"):
            d = route(s)
            print(f"  [{d['target']:<6}] {s}  ({d['reason']})")
