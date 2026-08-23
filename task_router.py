# -*- coding: utf-8 -*-
"""
任务路由与失败链路(规划 §1)。

架构:本地小模型 → 规则引擎 → 云端大模型 → 诚实认输(§1.4,每一层失败都有下一层,不能断链)

§1.2 难度判定(不用 token 数,用结构化信号):
  1. 任务类型难度清单:诊断 / 代码分析 / 多步规划 = 难;翻译 / 摘要 / 分类 = 易
  2. 输出格式匹配:能填进预设 JSON 槽位(即"能映射到某个工具")= 本地干,否则转云端
  3. 兜底信号:本地结果置信度低、超时、超长 → 自动转云端

§1.3 "转云端"的交互包装:用业务语言,不是技术提示。

用法:
  from task_router import route, run_with_fallback
  decision = route("帮我看看日志")          # -> {"target": "local"|"cloud"|"rule", ...}
  result = run_with_fallback(text, local_engine, cloud_fn, rule_engine)
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
# 注意:关键词要精确,避免与工具动词冲突(如"装"/"查"不放进 FAQ)。
RULE_FAQ = [
    # (关键词列表, 回答)
    (["怎么下载", "如何下载", "下载游戏", "在哪下"], "下载实例:点左侧「下载」→ 选版本/加载器 → 开始下载。也可以直接跟我说「下载 1.21.1」,我会帮你建。"),
    (["java", "Java", "jdk"], "Java 会自动下载管理,不用手动装。遇到 Java 报错告诉我,我会看日志。"),
    (["联机", "多人游戏", "怎么联机"], "联机:点「联机方案中心」,有局域网/端口转发/第三方平台三种方案对比。"),
    (["更新", "检查更新", "升级启动器"], "检查更新:菜单「帮助 → 检查更新」。"),
    (["离线模式", "正版", "账号登录"], "当前是离线模式,无需正版账号即可玩;正版登录正式版会加。"),
    (["设置在哪", "配置在哪", "怎么设置"], "设置:主界面右上角齿轮。AI 设置、内存、语言都在里面。"),
    (["是什么", "有哪些功能", "能做什么"], "我能帮你:装/查 Mod、查配方、读日志、诊断崩溃、发游戏指令、备份实例、管理设置。"),
    (["怎么用", "怎么玩", "新手"], "新手引导:首次启动有引导向导;随时问我「XX 怎么用」就行。"),
]


def match_rule(text: str) -> str | None:
    """规则引擎:关键词模糊匹配 FAQ。命中返回回答,否则 None(交给上层)。"""
    for kws, answer in RULE_FAQ:
        if any(kw.lower() in text.lower() for kw in kws):
            return answer
    return None


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


def route(text: str, *, have_cloud: bool = True, have_local: bool = True) -> dict:
    """决定任务走哪一层。返回 {"target": ..., "reason": ...}。
    target: "rule"(规则引擎直接答) / "chat"(本地简单对话) / "local"(本地工具) /
            "ask"(问用户) / "cloud"(云端)。

    优先级设计(关键):
      0. 歧义请求(推荐/该装哪些)→ 直接 ask_user,不让模型瞎猜
      1. 含工具动词的指令(如"把内存改成 6G")→ 先本地工具,规则引擎不抢
      2. 纯问答(如"怎么下载游戏")→ 规则引擎 FAQ 最稳
      3. 困难任务(诊断/代码/多步规划)→ 云端
      4. 兜底 → 云端"""
    # 0. 歧义请求:需要用户选择 → ask_user(模型层面 + 路由层面双保险)
    if looks_ambiguous(text):
        return {"target": "ask", "reason": "歧义请求,需要问用户"}
    # 0b. 简单对话/寒暄/基础介绍 → 本地自由回答(不需要工具,也不需要云端)
    if looks_simple_chat(text):
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
    # 1. 纯问答 → 规则引擎(最稳、零成本)
    if match_rule(text):
        return {"target": "rule", "reason": "命中固定问答库"}
    # 2. 难度判定
    difficulty = classify_difficulty(text)
    if difficulty == "difficult":
        return {"target": "cloud" if have_cloud else "local",
                "reason": "困难任务(诊断/代码/多步规划)转云端"}
    # 3. 兜底:未知难度 → 云端
    return {"target": "cloud" if have_cloud else "local",
            "reason": "未知难度,云端兜底"}


# ================= 失败链路执行(§1.4) =================

def _wrap_cloud_offer(reason: str) -> str:
    """§1.3 转云端用业务语言包装,不是技术提示。"""
    return ("这个任务超出了我的基础能力,升级后可以完成,要不要试试?"
            "(或者你说'就用基础版凑合一下'也行)")


def run_with_fallback(text: str, local_engine=None, cloud_fn=None,
                      rule_engine=match_rule, timeout: float = 120.0,
                      ask_engine=None) -> dict:
    """失败链路:本地小模型 → 规则引擎 → 云端大模型 → 诚实认输。
    每一层失败都有下一层,不能断链(§1.4)。

    参数:
      local_engine: 可调用,输入文本返回工具调用 dict(如 GrammarToolEngine.tool_call)
      cloud_fn:     可调用,输入文本返回云端回复字符串(失败抛异常或返回 None)
      rule_engine:  可调用,输入文本返回回答或 None(默认 match_rule)
      ask_engine:   可调用,输入文本返回 ask_user 工具调用 dict;歧义请求时用它问用户

    返回 {"source": "ask"|"local"|"rule"|"cloud"|"give_up", "content": ..., "raw": ...}
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

    # 1. 规则引擎先试(最稳)
    ans = rule_engine(text)
    if ans:
        return {"source": "rule", "content": ans, "raw": None}

    # 2. 本地小模型
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

    # 3. 云端大模型
    if cloud_fn is not None:
        try:
            reply = cloud_fn(text)
            if reply:
                return {"source": "cloud", "content": reply, "raw": reply,
                        "note": _wrap_cloud_offer("本地未能处理")}
        except Exception:
            pass

    # 4. 诚实认输
    return {"source": "give_up",
            "content": "我尽力了,这个问题暂时搞不定。你可以换个说法,或者到设置里换个更强的模型。"}


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # 自测:路由决策 + 失败链路(用假引擎演示)
    print("==== 路由决策示例 ====")
    samples = [
        "看看我有哪些实例",           # 本地(工具动词)
        "帮我查一下为什么崩了",       # 云端(诊断)
        "怎么下载游戏",               # 本地(工具)
        "把内存改成 6G",              # 本地
        "我想装几个mod,你帮我推荐下",  # ask(歧义)
        "我该装哪些优化mod",           # ask(歧义)
        "给我做个装mod的方案",        # 云端(规划)
        "今天天气怎么样",             # 云端(兜底)
    ]
    for s in samples:
        d = route(s)
        print(f"  [{d['target']:<6}] {s}  ({d['reason']})")

    print("\n==== 失败链路示例(本地引擎抛异常→云端)====")
    def bad_local(t):
        raise RuntimeError("本地模型未就绪")
    def cloud(t):
        return f"[云端回复] {t} 的建议……"
    r = run_with_fallback("为什么我的游戏闪退", bad_local, cloud)
    print(f"  source={r['source']} content={r['content'][:60]}")

    print("\n==== 歧义请求→ask_user(路由层兜底)====")
    def ask_engine(t):
        return {"name": "ask_user", "arguments": {"question": "你想装哪些 Mod?", "options": ["钠", "锂", "玉"]}}
    r3 = run_with_fallback("我想装几个mod,你帮我推荐下", None, None, ask_engine=ask_engine)
    print(f"  source={r3['source']} content={r3['content']}")

    print("\n==== 失败链路示例(全失败→诚实认输)====")
    r2 = run_with_fallback("为什么我的游戏闪退", None, None)
    print(f"  source={r2['source']} content={r2['content'][:60]}")
