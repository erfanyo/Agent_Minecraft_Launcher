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
def make_answerer(win=None, settings: dict | None = None):
    """返回 answer_fn(text, instance) -> str:用启动器 AI(按 ai_in_game)同步回答游戏内提问。

    - 云端(ai_in_game=cloud 或默认):用 settings 的 cloud base/key/model 直连 chat_completion;
    - 本地(local):走内置 GrammarToolEngine(约 500MB,需已下载);
    - off:返回引导提示。
    """
    def answer(text: str, instance: str) -> str:
        try:
            cfg = settings if settings is not None else \
                (__import__("settings").load_settings())
            mode = cfg.get("ai_in_game", "off")
            if mode == "off":
                return "游戏内 AI 未开启(设置→AI 助手→游戏内 AI)。"
            base = cfg.get("ai_cloud_base_url") or cfg.get("ai_base_url") or ""
            key = cfg.get("ai_cloud_api_key") or cfg.get("ai_api_key") or ""
            model = cfg.get("ai_cloud_model") or cfg.get("ai_model") or ""
            if base and key and model:
                from assistant import chat_completion
                messages = [{"role": "system", "content":
                             "你是 Agent Minecraft 启动器的 AI,用中文简短回答用户(≤3 句)。"},
                            {"role": "user", "content": text}]
                return chat_completion(messages, base.rstrip("/"), key, model)
            # 无云端 → 本地模型(需已下载)
            if mode == "local":
                from local_ai import GrammarToolEngine
                eng = GrammarToolEngine()
                try:
                    eng.start()
                    return eng.chat(text, n_predict=256, temperature=0.3)
                except Exception as e:
                    return f"(本地模型不可用:{type(e).__name__})"
            return "(未配置云端 AI,无法游戏内回答。)"
        except Exception as e:
            return f"(游戏内 AI 错误:{type(e).__name__})"
    return answer
