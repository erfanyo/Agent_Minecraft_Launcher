# -*- coding: utf-8 -*-
"""
本地推理模块原型(规划 §7.1 优先项:grammar 约束解码)。

核心思路:
  1. 用 llama.cpp server(b10590 自带二进制,AMCL/runtime/llama-cpp)加载本地模型
  2. GBNF grammar 从工具 schema **自动生成**:name 枚举合法工具名,
     arguments 按每个工具的 parameters(required 字段必填)约束 —— "结构上必对"
  3. 输出必然是可解析 JSON,模型只能"选工具 + 填参数",格式错误从根上消灭

用法:
  from local_ai import GrammarToolEngine
  engine = GrammarToolEngine()
  engine.start()                      # 启动 llama-server(懒加载,用完可 stop)
  call = engine.tool_call("给 neoforge-21.1.248 装 钠")   # -> {"name": ..., "arguments": ...}
  engine.stop()

当前原型用原生 /completion 端点 + GBNF(不走 OpenAI 兼容层,因为 LM Studio
端点对推理模型不生效 grammar,见 .tmp/probe 结论)。
"""
import json
import os
import subprocess
import sys
import time

import requests

from paths import CONFIG_DIR  # noqa: E402

LLAMA_DIR = os.path.join(CONFIG_DIR, "runtime", "llama-cpp")
SERVER_EXE = os.path.join(LLAMA_DIR, "llama-server.exe")

# 默认模型:xLAM 微调版 Q4_K_M(§8.1 拍板)
DEFAULT_MODEL_ID = "qwen3.5-0.8b-xlam-q4km"

# ---- 翻译(W1:Mod 描述英→中,复用 chat 通道)----
# MC 标准译名术语表(内置 30-50 条,随用随加):注入翻译 system prompt 强制标准译名;
# 命中术语的文本置信度标记为高(mod_translate 会复用本表做置信度判断)。
MC_GLOSSARY = {
    # 维度 / 世界
    "nether": "下界", "the nether": "下界", "end": "末地", "the end": "末地",
    "overworld": "主世界", "dimension": "维度", "biome": "生物群系",
    "structure": "结构", "world generation": "世界生成",
    # 生物 / 刷怪
    "mob spawner": "刷怪笼", "spawner": "刷怪笼", "mob": "生物", "villager": "村民",
    "ender dragon": "末影龙", "wither": "凋灵", "zombie": "僵尸", "skeleton": "骷髅",
    "creeper": "苦力怕", "enderman": "末影人",
    # 附魔 / 装备
    "enchant": "附魔", "enchanting": "附魔", "mending": "经验修补", "sharpness": "锋利",
    "unbreaking": "耐久", "protection": "保护", "fire aspect": "火焰附加",
    "knockback": "击退", "looting": "抢夺", "fortune": "时运", "efficiency": "效率",
    "silk touch": "精准采集", "respiration": "水下呼吸", "aqua affinity": "水下速掘",
    "feather falling": "摔落缓冲", "thorns": "荆棘", "depth strider": "深海探索者",
    "frost walker": "冰霜行者", "soul speed": "灵魂疾行",
    # 物品 / 材料
    "ingot": "锭", "ore": "矿石", "gem": "宝石", "dust": "粉", "plate": "板",
    "gear": "齿轮", "circuit": "电路板", "alloy": "合金", "bucket": "桶",
    "sword": "剑", "pickaxe": "镐", "axe": "斧", "shovel": "锹", "hoe": "锄",
    "bow": "弓", "armor": "盔甲", "helmet": "头盔", "chestplate": "胸甲",
    "leggings": "护腿", "boots": "靴子",
    # 玩法 / 机制
    "crafting": "合成", "craft": "合成", "smelting": "冶炼", "smelt": "冶炼",
    "mining": "挖掘", "farming": "农业", "farm": "农业", "automation": "自动化",
    "storage": "存储", "energy": "能量", "power": "能量", "generator": "发电机",
    "cable": "线缆", "pipe": "管道", "machine": "机器", "multiblock": "多方块",
    "recipe": "配方", "ore generation": "矿石生成",
    # Mod 类型 / 常用
    "mod": "模组", "modpack": "整合包", "shader": "光影", "resource pack": "资源包",
    "datapack": "数据包", "client side": "客户端", "server side": "服务端",
    "performance": "性能", "optimization": "优化", "fps": "帧率",
    "lightweight": "轻量", "compatibility": "兼容性", "configurable": "可配置",
    "configuration": "配置", "guide": "指南", "overlay": "覆盖层", "widget": "组件",
}


def _build_translate_system(glossary: dict) -> str:
    """翻译用 system prompt:目标中文 + 强制 MC 标准译名(命中即用标准译名,不直译)。
    用 <translation>...</translation> 定界 + 少样本示例,约束小模型只吐译文不罗嗦。"""
    lines = ["你是一个 Minecraft 中文翻译助手。把用户给的英文文本翻译成简体中文。",
             "规则:",
             "1. 只输出 <translation> 与 </translation> 之间的译文,不要任何解释、思考、清单或额外内容。",
             "2. 以下 Minecraft 标准译名必须使用(命中时用标准译名,不要直译):"]
    lines += [f"   {en} → {cn}" for en, cn in glossary.items()]
    lines += ["3. 文本本身就是中文时,原样放进标签。",
              "4. 长文本保持段落结构,译文通顺自然。",
              "示例:",
              "输入:This mod adds new ores to the Nether.",
              "输出:<translation>这个模组为下界添加了新矿石。</translation>",
              "输入:Enchant your tools with mending and silk touch.",
              "输出:<translation>用经验修补和精准采集附魔你的工具。</translation>"]
    return "\n".join(lines)

def schemas_from_assistant_tools() -> dict:
    """从 assistant.TOOLS(单一来源)提取本地 grammar 用的工具 schema。
    这样以后加工具只需改 assistant.py 一处,grammar 自动跟着变。
    返回 {工具名: {"properties": {k: 类型}, "required": [...]}}"""
    try:
        import assistant
        out = {}
        for t in assistant.TOOLS:
            fn = t["function"]
            params = fn.get("parameters", {})
            props = params.get("properties", {})
            out[fn["name"]] = {
                "properties": {k: (v.get("type", "string") if isinstance(v, dict) else "string")
                               for k, v in props.items()},
                "required": list(params.get("required", [])),
            }
        if out:
            return out
    except Exception:
        pass
    # fallback:assistant 不可用时用内置清单
    return TOOL_SCHEMAS_FALLBACK
# 工具 schema 的最小形态:name + 参数 key/required。
# 正式来源:assistant.TOOLS(见 schemas_from_assistant_tools);
# 下面这份是 assistant 不可用时的 fallback(内容与 assistant.TOOLS 同步维护)。
TOOL_SCHEMAS_FALLBACK = {
    "list_instances": {"properties": {}, "required": []},
    "search_mods": {"properties": {"query": "string", "game_version": "string", "loader": "string"},
                    "required": ["query"]},
    "list_mods": {"properties": {"instance": "string"}, "required": ["instance"]},
    "read_instance_log": {"properties": {"instance": "string"}, "required": ["instance"]},
    "read_crash_report": {"properties": {"instance": "string"}, "required": ["instance"]},
    "get_settings": {"properties": {}, "required": []},
    "install_instance": {"properties": {"version": "string", "loader": "string",
                                        "loader_version": "string", "shader": "boolean",
                                        "optimize": "boolean"},
                         "required": ["version"]},
    "ask_user": {"properties": {"question": "string", "options": "array"},
                 "required": ["question"]},
    "launch_game": {"properties": {"instance": "string"}, "required": ["instance"]},
    "install_mod": {"properties": {"slug": "string", "instance": "string", "version": "string"},
                    "required": ["slug", "instance"]},
    "install_mods": {"properties": {"slugs": "array", "instance": "string"},
                     "required": ["slugs", "instance"]},
    "backup_instance": {"properties": {"instance": "string"}, "required": ["instance"]},
    "set_setting": {"properties": {"key": "string", "value": "string"},
                    "required": ["key", "value"]},
    "send_game_command": {"properties": {"instance": "string", "command": "string"},
                          "required": ["instance", "command"]},
    "get_command_guide": {"properties": {"mc_version": "string"}, "required": ["mc_version"]},
    "get_key_bindings": {"properties": {"instance": "string", "query": "string"},
                         "required": ["instance", "query"]},
    "get_recipe_path": {"properties": {"item": "string", "count": "integer",
                                       "instance": "string", "brief": "boolean",
                                       "recipe_index": "integer"},
                        "required": ["item"]},
    "compare_items": {"properties": {"attribute": "string", "top_n": "integer"},
                      "required": ["attribute"]},
}

# 工具描述(给模型看的语义信息,决定它选对工具;grammar 管格式,描述管语义)
TOOL_DESCRIPTIONS = {
    "list_instances": "列出已安装的实例及其加载器/基础版本。用户问'有哪些实例/装了哪些游戏/看看实例'时用它",
    "search_mods": "搜索 Mod(支持中文名),参数 query 如 sodium 或 钠;可按游戏版本/加载器过滤。注意:只是搜索,不是安装",
    "list_mods": "列出某实例已安装的 Mod 文件。用户问'XX 装了哪些mod/有什么mod'时用它",
    "read_instance_log": "读取某实例最近的游戏日志(诊断报错/崩溃用)。用户说'看日志/看报错'时用它",
    "read_crash_report": "读取某实例最新的崩溃报告(诊断崩溃用)。用户说'崩溃了/闪退/看崩溃报告'时用它",
    "get_settings": "查看启动器当前设置(内存/用户名等)",
    "install_instance": "下载/创建【新】游戏实例(写操作)。version 如 1.21.1,loader 如 fabric/forge/neoforge。"
                        "注意:这是创建新实例,不是启动已有实例!用户说'建一个/下载一个/创建实例'时用它",
    "ask_user": "重要!当用户指令有歧义、缺少关键信息、或需要用户选择时调用:向用户弹出选择框,question 是你要问的话,options 是候选选项列表。"
                "规则:拿不准用户想要什么时【必须】用这个,不要擅自猜测!例如用户说'帮我推荐mod/该装哪些'但没说具体装什么时,用这个问用户",
    "launch_game": "启动【已存在】的实例游戏(写操作)。用户说'启动XX/打开游戏/开始玩/进游戏'时用它。"
                   "注意:只启动,不创建!实例不存在时改用 install_instance 或先查 list_instances",
    "install_mod": "给某实例安装单个 Mod(写操作),slug 是 mod 的英文名如 sodium。用户明确说要装某个具体 mod 时用它",
    "install_mods": "批量给某实例安装多个 Mod(写操作),slugs 是 mod 名列表如 [sodium, lithium]。"
                    "用户说'装A和B/装这几个mod'时用它一次装完,别逐个调 install_mod",
    "backup_instance": "备份某实例(写操作)。用户说'备份XX/怕坏档'时用它",
    "set_setting": "修改启动器设置(写操作),key 如 memory_gb / username,value 是新值。用户说'改成XX/设置XX'时用它",
    "send_game_command": "向运行中的游戏发送指令,command 如 summon zombie 或 weather rain。"
                         "用户说'发指令/执行命令/summon/生成僵尸/改天气'时用它",
    "get_command_guide": "按游戏版本查指令指南,mc_version 如 1.21.1。用户问'XX指令怎么写/指令大全'时用它",
    "get_key_bindings": "查询按键绑定,query 是按键或功能词如 空格/space/前进/攻击",
    "get_recipe_path": "查询物品合成配方,支持中文名,item 如 终极感应供应器/铁锭。用户问'怎么合成/要多少材料/怎么做'时用它",
    "compare_items": "比较物品参数(武器伤害/护甲/护甲韧性/攻速/挖掘等级),attribute 必须用中文(如 武器伤害/护甲/攻速),"
                     "不要用英文 damage/armor!用户问'哪个伤害最高/谁护甲最厚/哪个最强'时用它",
}


def build_gbnf(schemas: dict) -> str:
    """从工具 schema 生成 GBNF grammar:
    root 是每个工具一个分支:name 字面量 + 对应 arguments 结构绑定,
    模型选 name=xxx 时 arguments 只能走该工具的字段约束 —— "结构上必对,字段按工具齐全"。
    """
    lines = [
        # 每个工具一个完整分支:name 字面量 与 该工具 argsN 绑定
        "root ::= " + " | ".join(f"tool{i}" for i in range(len(schemas))),
        'object ::= "{" ws (pair (ws "," ws pair)*)? ws "}"',
        'pair ::= "\\"" key "\\"" ws ":" ws value',
        'key ::= [a-zA-Z_]+',
        'value ::= string | number | boolean | "null" | object | array',
        'string ::= "\\"" ([^"\\\\] | "\\\\" .)* "\\""',
        'number ::= "-"? [0-9]+ ("." [0-9]+)?',
        'boolean ::= "true" | "false"',
        'array ::= "[" ws (value (ws "," ws value)*)? ws "]"',
        'ws ::= [ \\t\\n]*',
    ]
    for i, (name, meta) in enumerate(schemas.items()):
        # 分支:{"name": "<工具名>", "arguments": <argsN>}
        lines.append(f'tool{i} ::= "{{" ws "\\"name\\"" ws ":" ws "\\"{name}\\""'
                     f' ws "," ws "\\"arguments\\"" ws ":" ws args{i} ws "}}"')
        props = meta.get("properties", {})
        required = meta.get("required", [])
        opt_keys = [k for k in props if k not in required]
        if not props:
            lines.append(f"args{i} ::= object")
            continue
        # 必填:key:value 用逗号连接,固定顺序
        req_pairs = [f'"\\"{k}\\"" ws ":" ws {_type_rule(props[k])}' for k in required]
        core = " ws \",\" ws ".join(req_pairs)
        # 可选:每个整体 (ws "," ws "key" ws ":" ws value)? 包裹
        for k in opt_keys:
            core += f' (ws "," ws "\\"{k}\\"" ws ":" ws {_type_rule(props[k])})?'
        lines.append(f"args{i} ::= " + '"{" ws ' + core + ' ws "}"')
    return "\n".join(lines)


def _type_rule(t: str) -> str:
    return {"string": "string", "integer": "number", "number": "number",
            "boolean": "boolean", "array": "array"}.get(t, "string")


def _extract_translation(raw: str) -> str:
    """从 <translation>...</translation> 定界里取译文;标签缺失/为空时回退:
    取最后一段非空文本(模型啰嗦时译文通常在末尾),仍空则原样返回。"""
    raw = (raw or "").strip()
    start = raw.find("<translation>")
    if start >= 0:
        start += len("<translation>")
        end = raw.find("</translation>", start)
        if end >= 0:
            inside = raw[start:end].strip()
            if inside:
                return inside
    # 回退:去掉疑似思考/分析段,取最后一段;并清掉可能残留的开标签
    parts = [p.strip() for p in raw.splitlines() if p.strip()]
    if parts:
        out = parts[-1]
        if out.startswith("<translation>"):
            out = out[len("<translation>"):].strip()
        return out
    return raw


class GrammarToolEngine:
    """本地推理引擎原型:管理 llama-server 子进程 + GBNF 约束的工具调用"""

    def __init__(self, model_id: str = DEFAULT_MODEL_ID, port: int = 8090,
                 gbnf: str = None, system_prompt: str = None,
                 schemas: dict = None):
        self.model_id = model_id
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.schemas = schemas or schemas_from_assistant_tools()
        self.gbnf = gbnf or build_gbnf(self.schemas)
        self.system_prompt = system_prompt or self._default_system()
        self.proc = None

    # ---- 生命周期(规划 §5:用完即卸)----
    def start(self, model_path: str = None, wait: int = 90):
        import model_registry
        if self.proc and self.proc.poll() is None:
            return
        if model_path is None:
            model_path = model_registry.local_path(self.model_id)
        if not os.path.exists(SERVER_EXE):
            raise RuntimeError(f"llama-server 不存在:{SERVER_EXE}(先运行 .tmp/full_llamacpp.py)")
        self.proc = subprocess.Popen(
            [SERVER_EXE, "-m", model_path, "--port", str(self.port),
             "-c", "2048", "--no-webui", "-np", "1", "--log-disable"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(wait):
            try:
                if requests.get(f"{self.base}/health", timeout=3).status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(1)
        self.stop()
        raise RuntimeError("llama-server 启动超时")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *a):
        self.stop()

    # ---- 调用 ----
    def _chat_prompt(self, user_text: str, context: str = "", system: str = None) -> str:
        sys_text = system if system is not None else self.system_prompt
        if context:
            sys_text = sys_text + "\n\n" + context
        return ("<|im_start|>system\n" + sys_text + "<|im_end|> \n"
                f"<|im_start|>user\n{user_text}<|im_end|> \n"
                "<|im_start|>assistant\n")

    def chat(self, user_text: str, timeout: int = 120, context: str = "",
             system: str = None, n_predict: int = 256, temperature: float = 0.3) -> str:
        """本地自由对话(无 grammar 约束):寒暄/基础介绍/简单问答/翻译。
        与 tool_call 互补 —— 本地小模型既能"干活"(工具调用)也能"说话"(简单对话)。
        返回回复文本;失败抛异常,上层可落云端(§1.4)。
        system: 覆盖默认助手 system prompt(翻译等专用场景传入);
        n_predict: 最大生成长度(长文本翻译时调大);
        temperature: 采样温度(翻译用更低值更稳定)。"""
        chat_system = system or ("你是 Agent Minecraft Launcher 启动器的 AI 助手,用中文简洁友好地回答。"
                                 "你可以介绍启动器的功能(下载/启动游戏、装 Mod、查配方、发指令、诊断日志等)。"
                                 "回答要简短(3 句话以内),不知道的就直说。")
        body = {"prompt": self._chat_prompt(user_text, context=context, system=chat_system),
                "n_predict": n_predict, "temperature": temperature,
                "stop": ["<|im_end|>", "</s>"]}
        r = requests.post(f"{self.base}/completion", json=body, timeout=timeout)
        r.raise_for_status()
        content = r.json()["content"].strip()
        # 剥掉思考块(Qwen 推理模型的 <think>...</think> 输出对用户无意义)
        if content.startswith("<think>"):
            end = content.find("</think>")
            if end >= 0:
                content = content[end + len("</think>"):].strip()
        return content

    def translate(self, text: str, timeout: int = 90, context: str = "",
                  glossary: dict = None, n_predict: int = 768) -> str:
        """英→中翻译(复用 chat 通道,注入 MC 标准译名术语表)。
        模型按约定把译文放在 <translation>...</translation> 之间;解析失败则
        原样返回模型输出(置信度由 mod_translate 判断)。失败抛异常(调用方降级显示原文)。"""
        g = dict(MC_GLOSSARY)
        if glossary:
            g.update(glossary)
        raw = self.chat(text, timeout=timeout, context=context,
                        system=_build_translate_system(g),
                        n_predict=n_predict, temperature=0.1)
        return _extract_translation(raw)

    def tool_call(self, user_text: str, timeout: int = 120, context: str = "") -> dict:
        """让模型输出一次工具调用,grammar 保证可解析。返回 {"name":..,"arguments":..}
        context: 真实启动器上下文(如实例清单/设置),注入 system prompt(规划 §7.3 最轻量 RAG)。
        若输出被截断/卡住(必填参数未填完),自动重试:
          1. 把已输出的半截 JSON 作为前缀续写(模型只需补缺失字段,不从头重吐)
          2. 仍失败则报错,上层落云端(§1.4)"""
        attempt = 0
        last_content = ""
        while True:
            if attempt == 0:
                prompt = self._chat_prompt(user_text, context=context)
            else:
                # 续写:把上次半截输出拼进 prompt 末尾(模型接着补完,grammar 从当前位置继续约束)
                prompt = (self._chat_prompt("", context=context).rstrip() + "\n" +
                          last_content + "\n(继续:请补齐剩余必填参数后结束)")
            body = {"prompt": prompt, "n_predict": 1024,
                    "temperature": 0.0, "stop": ["<|im_end|>", "</s>"],
                    "grammar": self.gbnf}
            r = requests.post(f"{self.base}/completion", json=body, timeout=timeout)
            r.raise_for_status()
            last_content = r.json()["content"].strip()
            try:
                return json.loads(last_content)
            except json.JSONDecodeError:
                if attempt >= 2:
                    raise ValueError(f"grammar 输出解析失败:{last_content[:200]}")
                attempt += 1
                continue

    def _default_system(self) -> str:
        descs = "\n".join(f"- {n}:{d}" for n, d in TOOL_DESCRIPTIONS.items())
        return ("你是 Agent Minecraft 启动器的 AI 助手。需要调用工具时,只输出 JSON:"
                '{"name": 工具名, "arguments": {参数}}。工具清单:\n' + descs +
                "\n参数里需要实例 id 时,从 system 提示的可用实例中选择;"
                "没给出实例信息时,用 list_instances 先查。"
                "**重要:arguments 必须包含该工具的全部必填参数,一个都不能少;"
                "缺参数会导致调用失败,请确保输出完整后再结束。**")


def build_launcher_context(game_dir: str = None) -> str:
    """构建启动器真实上下文(规划 §7.3 最轻量 RAG):
    已装实例清单 + 关键设置,注入本地模型的 system prompt,避免模型乱编实例 id。
    无 GUI 依赖,CLI / 测试 / 前端共用。"""
    lines = []
    try:
        from agent_tools import list_instances
        insts = list_instances(game_dir)
        lines.append(f"当前已安装实例:\n{insts}")
    except Exception:
        pass
    try:
        from settings import load_settings
        s = load_settings()
        lines.append(f"启动器设置:游戏名 {s.get('username', 'Player')},"
                     f"内存 {s.get('memory_gb', 2)}G")
    except Exception:
        pass
    return "\n".join(lines)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # CLI 用法:
    #   python local_ai.py              冒烟:6 条典型指令
    #   python local_ai.py --regress    回归:31 条测试集(§7.4),模型/规则更新后自动跑(3 次平均,注入真实上下文)
    if len(sys.argv) > 1 and sys.argv[1] == "--regress":
        import ai_testset
        runs = 3
        if "--runs" in sys.argv:
            try:
                runs = int(sys.argv[sys.argv.index("--runs") + 1])
            except (IndexError, ValueError):
                pass
        print(f"回归测试:{len(ai_testset.CASES)} 条用例 ×{runs} 次平均(注入真实上下文)…\n")
        with GrammarToolEngine() as eng:
            context = build_launcher_context()
            per = {}
            for _r in range(runs):
                for case in ai_testset.CASES:
                    try:
                        call = eng.tool_call(case["user"], context=context)
                        score = ai_testset.evaluate_output(
                            case, call.get("name", ""), call.get("arguments", {}))
                    except Exception as e:
                        score = {"name_ok": 0.0, "args_score": 0.0,
                                 "detail": f"FAIL {type(e).__name__}"}
                    per.setdefault(case["id"], []).append(score)
            name_hits = args_hits = total = 0
            for case in ai_testset.CASES:
                total += 1
                sc = per[case["id"]]
                n_ok = sum(x["name_ok"] for x in sc) / len(sc)
                a_ok = sum(x["args_score"] for x in sc) / len(sc)
                name_hits += n_ok
                args_hits += a_ok
                tag = "✓" if n_ok == 1.0 else "✗"
                print(f"  {tag} {case['id']} 期望={case['expect_tool']} "
                      f"name={n_ok:.2f} args={a_ok:.2f}")
        print(f"\n回归汇总:工具名 {name_hits/total:.1%} 参数 {args_hits/total:.1%} "
              f"综合 {(name_hits+args_hits)/(2*total):.1%}")
        raise SystemExit
    cases = [
        "看看我有哪些实例",
        "给 neoforge-21.1.248 装 钠 和 锂 两个mod",
        "查一下 终极感应供应器 怎么合成",
        "把内存改成 6G",
        "游戏崩了,帮我看看崩溃报告",
        "给 neoforge-21.1.248 发指令 summon zombie",
    ]
    with GrammarToolEngine() as eng:
        for u in cases:
            try:
                call = eng.tool_call(u)
                print(f"{u}\n  -> {json.dumps(call, ensure_ascii=False)}\n")
            except Exception as e:
                print(f"{u}\n  -> FAIL {type(e).__name__}: {str(e)[:150]}\n")
