# -*- coding: utf-8 -*-
"""
游戏内 AI 入口(启动器侧):轮询 bridge-mod 写的 `.bridge/ai_request.json`,
把玩家在游戏里敲的 `/ai <内容>` 交给启动器 AI,结果写回 `.bridge/ai_reply.json`
供 bridge-mod 回显。

流程(文件交换,复用 bridge-mod 的 .bridge 机制):
  游戏(mod)  /ai xxx → 写 .bridge/ai_request.json {seq, text, ts}
  启动器    轮询 → 发现新 seq → 调 AI → 写 .bridge/ai_reply.json {seq, text, ts}
  游戏(mod)  读 ai_reply.json → tellraw 回显给玩家

现状:启动器侧可用(轮询/处理/回复);mod 侧 `/ai` 命令代码见 bridge-mod(需编译)。
"""
import json
import os
import time

import paths


def _bridge_dir(instance_id: str, game_dir: str = None) -> str:
    """实例的 .bridge 目录(隔离开时在 versions/<id>/.bridge)。"""
    gd = game_dir or paths.GAME_DIR
    if (__import__("settings").load_settings().get("version_isolation")):
        return os.path.join(gd, "versions", instance_id, ".bridge")
    return os.path.join(gd, ".bridge")


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path: str, data: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


class InGameAI:
    """轮询某实例的 .bridge/ai_request.json,处理玩家 '/ai' 请求。

    用法(在主窗口/游戏运行线程):
        ai = InGameAI(instance_id, answer_fn, poll=1.0)
        ai.start()   # 后台线程轮询;answer_fn(text, instance) -> 回复文本
        ai.stop()
    """

    def __init__(self, instance_id: str, answer_fn, poll: float = 1.0,
                 game_dir: str = None):
        self.instance_id = instance_id
        self.answer_fn = answer_fn      # (text, instance_id) -> 回复文本
        self.poll = poll
        self.game_dir = game_dir
        self._last_seq = 0
        self._running = False
        self._thread = None
        # 记住上次回复的 seq,避免重复处理
        self._seen_seq = set()

    def _req_path(self) -> str:
        return os.path.join(_bridge_dir(self.instance_id, self.game_dir),
                            "ai_request.json")

    def _rep_path(self) -> str:
        return os.path.join(_bridge_dir(self.instance_id, self.game_dir),
                            "ai_reply.json")

    def _latest_request(self) -> dict | None:
        req = _read_json(self._req_path())
        if not req:
            return None
        seq = req.get("seq")
        text = (req.get("text") or "").strip()
        if text and seq not in self._seen_seq:
            return req
        return None

    def _loop(self):
        while self._running:
            try:
                req = self._latest_request()
                if req:
                    seq = req.get("seq", 0)
                    self._seen_seq.add(seq)
                    text = req.get("text", "")
                    player = req.get("player", "") or ""
                    # 额度/冷却检查(启动器端,保护服主 API):超限直接回提示,不调 AI
                    try:
                        from ai_quota import check_and_consume
                        gr = check_and_consume(player)
                        if not gr.ok:
                            _write_json(self._rep_path(),
                                        {"seq": seq, "text": gr.reason, "ts": time.time()})
                            continue
                    except Exception:
                        pass   # 额度模块异常不阻断主流程
                    reply = ""
                    try:
                        reply = self.answer_fn(text, self.instance_id) or ""
                    except Exception as e:
                        reply = f"(AI 处理失败:{type(e).__name__})"
                    _write_json(self._rep_path(),
                                {"seq": seq, "text": reply, "ts": time.time()})
            except Exception:
                pass
            time.sleep(self.poll)

    def start(self):
        if self._running:
            return
        self._running = True
        import threading
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False


# ---- 便捷:在游戏运行期间轮询,用启动器 AI 作答 ----
def _in_game_tools():
    """游戏内可用的 AI 工具子集(从 assistant.TOOLS 里挑):以指令/查询为主,不含写操作。"""
    try:
        from assistant import TOOLS
    except Exception:
        return None
    want = {"send_game_command", "get_command_guide", "get_recipe_path",
            "compare_items", "get_key_bindings", "get_settings",
            "list_instances", "ask_user"}
    return [t for t in TOOLS if t.get("function", {}).get("name") in want] or None


def _in_game_system(instance: str) -> str:
    return ("你是 Agent Minecraft 启动器的 AI,在游戏内回答玩家。"
            f"当前正在运行的实例是「{instance}」,你可以对它执行操作(如 send_game_command 发指令改天气/召唤生物)。"
            "用中文简洁回答,能执行就直接执行,不要只说不做。执行结果要反馈给玩家。")


def _make_cloud_executor(instance: str, base_exec):
    """在 build_executor 基础上,把 send_game_command 强制指向当前实例(避免 AI 写错实例)。"""
    def executor(name, args):
        if name == "send_game_command":
            args = dict(args or {})
            args["instance"] = instance
            args.setdefault("game_dir", paths.GAME_DIR)
        return base_exec(name, args)
    return executor


def _in_game_ctx(win, instance: str, settings: dict) -> str:
    """游戏内 AI 的系统提示 = 启动器 ai_context(含 skill 系统)+ 当前实例说明。"""
    parts = []
    if win is not None and hasattr(win, "ai_context"):
        try:
            parts.append(win.ai_context())
        except Exception:
            pass
    if not parts:
        parts.append("你是 Agent Minecraft 启动器里内置的 AI 助手,用中文简洁回答玩家。")
    parts.append(
        f"你正在【游戏内】响应玩家,当前运行实例:「{instance}」。"
        "玩家不用切出游戏。下面这些工具你【应该】能用,能执行就直接执行、不要只给指南:"
        "send_game_command(向该实例发指令,如 weather rain 改雨天 / summon 召唤 / give 给物品)、"
        "get_command_guide(查指令写法)、get_recipe_path(查配方)、compare_items(比物品)、"
        "get_key_bindings(查按键)。执行结果要反馈给玩家。")
    return "\n\n".join(parts)


def make_answerer(win=None, settings: dict | None = None):
    """返回 answer_fn(text, instance) -> str:游戏内 AI,按启动器 AI 路由(ai_strategy)作答。

    开关(ai_in_game):off=关闭;其它值(如 on)=打开 → 走 assistant.route_answer,
    与启动器 AI 同一套路由,并始终挂上指令相关工具(send_game_command 等)。
    """
    _FORCE_TOOLS = ["send_game_command", "get_command_guide", "get_recipe_path",
                    "compare_items", "get_key_bindings"]

    def answer(text: str, instance: str) -> str:
        try:
            cfg = settings if settings is not None else \
                (__import__("settings").load_settings())
            if str(cfg.get("ai_in_game", "off") or "off").strip().lower() == "off":
                return "游戏内 AI 未开启(设置→AI 助手→开启游戏内 AI)。"
            from assistant import route_answer
            ctx = _in_game_ctx(win, instance, cfg)
            return route_answer(text, cfg, context=ctx, force_tools=_FORCE_TOOLS)
        except Exception as e:
            return f"(游戏内 AI 错误:{type(e).__name__})"
    return answer
