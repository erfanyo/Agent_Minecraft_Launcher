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
    return paths.bridge_dir(instance_id, game_dir)


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
                        # 把上下文(player/is_op/exec_mode/pos/dim/held)传给 answer_fn,
                        # 供注入 prompt 与权限判定;旧 answer_fn(text, instance) 兼容
                        # 旧 bridge-mod 缺字段时必须保留为 None/空，不能伪造成“非 OP”。
                        raw_is_op = req.get("is_op")
                        ctx = {
                            "instance": self.instance_id,
                            "player": player,
                            "is_op": raw_is_op if isinstance(raw_is_op, bool) else None,
                            "permission_level": req.get("permission_level"),
                            "exec_mode": req.get("exec_mode", "player"),
                            "server_type": req.get("server_type", ""),
                            "is_integrated_owner": req.get("is_integrated_owner"),
                            "protocol_version": req.get("protocol_version", 0),
                            "pos": req.get("pos", ""),
                            "dim": req.get("dim", ""),
                            "held": req.get("held", ""),
                        }
                        try:
                            reply = self.answer_fn(text, ctx) or ""
                        except TypeError:
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


def _make_cloud_executor(instance: str, base_exec, exec_mode: str = "player",
                         as_player: str = ""):
    """在 build_executor 基础上,把 send_game_command 强制指向当前实例(避免 AI 写错实例),
    并按 exec_mode 传 as_player:非控制台模式且指定玩家 → 以该玩家身份执行指令。"""
    def executor(name, args):
        if name == "send_game_command":
            args = dict(args or {})
            args["instance"] = instance
            args.setdefault("game_dir", paths.GAME_DIR)
            # 以玩家身份执行:非控制台模式且知道了发出玩家 → 带 as_player
            if exec_mode != "console" and as_player:
                args["as_player"] = as_player
        return base_exec(name, args)
    return executor


def _can_exec(ctx: dict) -> bool:
    """统一判定:游戏内 AI 能否执行改动指令(供 _in_game_ctx 与 make_answerer 共用,避免两边矛盾)。
    - 集成服房主 → 允许，实际是否开作弊仍由 MC 以玩家身份裁决；
    - LAN 客人/专用服务器 → 仅 OP / --console；不能把 "LAN 已开放" 误作房主；
    - 旧协议缺少身份字段 → 不执行写指令，提示更新 bridge-mod，避免退化成控制台身份。"""
    server_type = str(ctx.get("server_type") or "").lower()
    is_owner = ctx.get("is_integrated_owner") is True
    is_op = ctx.get("is_op") is True
    is_console = ctx.get("exec_mode") == "console"
    if server_type in ("singleplayer", "lan") and is_owner:
        return True
    if server_type in ("singleplayer", "lan", "dedicated"):
        return is_op or is_console
    return False


def _in_game_ctx(win, instance: str, settings: dict, ctx: dict | None = None) -> str:
    """游戏内 AI 的系统提示 = 启动器 ai_context(含 skill 系统)+ 当前实例说明 + 玩家上下文。"""
    parts = []
    if win is not None and hasattr(win, "ai_context"):
        try:
            parts.append(win.ai_context())
        except Exception:
            pass
    if not parts:
        parts.append("你是 Agent Minecraft 启动器里内置的 AI 助手,用中文简洁回答玩家。")
    # 玩家实时上下文(用于精准回答)
    ctx = ctx or {}
    # 请求文件只能由已在运行的 bridge-mod 写入；协议 v2 更包含完整身份
    # 上下文。把这一事实明确交给模型，避免它根据知识库版本表臆测“没有
    # 安装 bridge”，进而要求玩家做无意义的重装。
    try:
        protocol_version = int(ctx.get("protocol_version") or 0)
    except (TypeError, ValueError):
        protocol_version = 0
    if protocol_version >= 2:
        parts.append(
            "桥接状态：已确认。本条消息由当前游戏中正在运行的 AgentMC Bridge "
            "通过本地通道发送；不要声称 bridge-mod 未安装、未加载或要求玩家为了"
            "建立通道而重装。")
    ctxt_line = []
    if ctx.get("player"):
        ctxt_line.append(f"发起玩家:{ctx['player']}")
    if ctx.get("is_op") is not None:
        ctxt_line.append("该玩家是 OP(level≥2)" if ctx["is_op"] else "该玩家不是 OP")
    if ctx.get("exec_mode"):
        ctxt_line.append("请求用控制台身份执行" if ctx["exec_mode"] == "console"
                         else "请求用玩家身份执行")
    if ctx.get("pos"):
        ctxt_line.append(f"坐标({ctx['pos']})")
    if ctx.get("dim"):
        ctxt_line.append(f"维度:{ctx['dim']}")
    if ctx.get("held"):
        ctxt_line.append(f"手持:{ctx['held']}")
    if ctxt_line:
        parts.append("玩家上下文(回答尽量结合):" + "; ".join(ctxt_line))
    # 只由 bridge-mod 上报的环境、房主身份与权限共同决定；不能仅凭 LAN 状态放行。
    can_exec = _can_exec(ctx)
    tool_note = (
        "你正在【游戏内】响应玩家,当前运行实例:「%s」。"
        "玩家不用切出游戏。能执行就直接执行、不要只给指南:"
        "send_game_command(向该实例发指令)、get_command_guide(查指令)、"
        "get_recipe_path(查配方)、compare_items(比物品)、get_key_bindings(查按键)。"
        "执行结果要反馈给玩家。" % instance)
    if not can_exec:
        tool_note = (
            "你正在【游戏内】响应玩家,当前运行实例:「%s」。"
            "当前身份无法安全执行改动指令:你只能用【只读】工具(查配方/get_command_guide/查按键/比物品),"
            "【不能】执行任何改动的游戏指令(send_game_command 不可用)。"
            "若这是旧版 bridge-mod，请先在启动器里更新它；否则需要 OP 权限或请服主操作。" % instance)
    parts.append(tool_note)
    return "\n\n".join(parts)


def make_answerer(win=None, settings: dict | None = None):
    """返回 answer_fn(text, ctx) -> str:游戏内 AI,按启动器 AI 路由(ai_strategy)作答。

    开关(ai_in_game):off=关闭;其它值(如 on)=打开 → 走 assistant.route_answer,
    与启动器 AI 同一套路由。ctx 含 {instance, player, is_op, exec_mode, pos, dim, held}:
    - 上下文注入:坐标/手持/维度/玩家名 → 更精准;
    - 权限:is_op=False(非 OP)或 exec_mode=player → 不挂 send_game_command(只读),
      仅 OP(或 --console/纯服务端)才允许 AI 执行指令;身份按 exec_mode(as_player)。"""
    _READONLY_TOOLS = ["get_command_guide", "get_recipe_path",
                       "compare_items", "get_key_bindings", "get_settings", "list_instances"]
    _FULL_TOOLS = _READONLY_TOOLS + ["send_game_command"]

    def answer(text: str, ctx: dict | None = None) -> str:
        try:
            cfg = settings if settings is not None else \
                (__import__("settings").load_settings())
            if str(cfg.get("ai_in_game", "off") or "off").strip().lower() == "off":
                return "游戏内 AI 未开启(设置→AI 助手→开启游戏内 AI)。"
            ctx = ctx or {}
            instance = ctx.get("instance", "")
            # 权限统一判(与 _in_game_ctx 一致)。执行时强制携带发起玩家，
            # 由 Minecraft 本身做最后的权限裁决，绝不退化为控制台身份。
            allow_exec = _can_exec(ctx)
            force_tools = _FULL_TOOLS if allow_exec else _READONLY_TOOLS
            from assistant import route_answer
            system = _in_game_ctx(win, instance, cfg, ctx)
            from assistant import build_executor
            executor = _make_cloud_executor(
                instance, build_executor(cfg),
                str(ctx.get("exec_mode") or "player"), str(ctx.get("player") or ""))
            return route_answer(text, cfg, context=system, force_tools=force_tools,
                                executor=executor)
        except Exception as e:
            return f"(游戏内 AI 错误:{type(e).__name__})"
    return answer
