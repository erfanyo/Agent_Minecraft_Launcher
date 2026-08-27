# -*- coding: utf-8 -*-
"""
游戏内 AI 额度限制 / 每玩家冷却(启动器端)。

**为什么**:/ai 请求底层走的是【服主(启动器主人)的 AI API】,多人联机时游戏内任何玩家
都能敲 /ai,不设限会被刷、烧光启动器主人的 API 额度。这里做两件事:
- 每日额度:整个实例 /ai 每天总发言次数上限(保护 API)
- 每玩家冷却:同一玩家两次 /ai 的最小间隔(防单个玩家刷)

**特例**:个别玩家可豁免每日额度(如服主自己无限用)。

状态持久化到 AMCL/cache/ai_quota.json,跨启动计数(自然日 0 点重置)。
"""
import json
import os
import threading
import time

from paths import CONFIG_DIR  # AMCL 目录

_CACHE_FILE = os.path.join(CONFIG_DIR, "cache", "ai_quota.json")
_LOCK = threading.Lock()

# 读取配置键(从 settings.DEFAULTS 兜底,见 _get_setting)


def _load_settings() -> dict:
    try:
        from settings import load_settings
        return load_settings()
    except Exception:
        return {}


def _get(key: str, default):
    return _load_settings().get(key, default)


def _read_state() -> dict:
    """读持久化计数:{"date":"2026-08-26","total":N,"last_time":{player:ts}}"""
    try:
        if os.path.isfile(_CACHE_FILE):
            with open(_CACHE_FILE, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {"date": "", "total": 0, "last_time": {}}


def _write_state(st: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _exempt_players() -> set:
    """特例玩家(豁免每日额度)名单,逗号分隔。"""
    ex = _get("ai_in_game_quota_exempt", "")
    return {x.strip() for x in str(ex or "").replace("，", ",").split(",") if x.strip()}


class GuardResult:
    __slots__ = ("ok", "reason")

    def __init__(self, ok: bool, reason: str = ""):
        self.ok = ok
        self.reason = reason


def check_and_consume(player: str) -> GuardResult:
    """对一次 /ai 请求做额度 + 冷却检查,【通过则消耗一次额度】并写回。

    player:玩家名(从 /ai 请求上报;空/未知按"匿名"处理)。
    返回 GuardResult(ok=True 放行;ok=False 附提示文本)。

    规则:
    - 每玩家冷却:距该玩家上次 /ai 不足 cool 秒 → 拒绝;
    - 每日额度:当天 total >= 额度且该玩家不在特例名单 → 拒绝;
      (额度 0 = 不限)
    """
    with _LOCK:
        state = _read_state()
        today = _today()
        # 跨天重置
        if state.get("date") != today:
            state = {"date": today, "total": 0, "last_time": {}}

        name = player or "匿名"
        # ① 每玩家冷却
        cool = int(_get("ai_in_game_cool", 5) or 5)
        last = state["last_time"].get(name, 0)
        now = time.time()
        if cool > 0 and last and (now - last) < cool:
            wait = int(cool - (now - last)) + 1
            return GuardResult(False, f"[AI] 你发得太快了,请 {wait} 秒后再试")

        # ② 每日额度(特例豁免)
        quota = int(_get("ai_in_game_quota", 50) or 50)
        is_exempt = name in _exempt_players() or _is_admin(name)
        if quota > 0 and not is_exempt:
            if state["total"] >= quota:
                return GuardResult(False,
                                   f"[AI] 今日游戏内 AI 额度已用完({quota} 次),明天再试")

        # ③ 通过 → 消耗(特例豁免不计入总额度,不挤压其它玩家)
        if not is_exempt:
            state["total"] += 1
        state["last_time"][name] = now
        _write_state(state)
        return GuardResult(True)


def _is_admin(player: str) -> bool:
    """判断是否"服主/可豁免"账号(与特例名单公共:也接受 ai_in_game_admin 名单)。"""
    admins = _get("ai_in_game_admin", "")
    adm = {x.strip() for x in str(admins or "").replace("，", ",").split(",") if x.strip()}
    return player in adm


def reset_today() -> None:
    """手动清零今日额度(测试/管理用)。"""
    with _LOCK:
        _write_state({"date": _today(), "total": 0, "last_time": {}})
