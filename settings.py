# -*- coding: utf-8 -*-
"""
启动器设置:用户名、内存、版本隔离等,持久化到 config.json。

学到的模式:配置文件的读写。
- 读取:文件里的值覆盖默认值,缺的字段补默认(这样以后加新设置,旧配置也不会坏)
- 保存:写成 JSON,人类可读可改
"""
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULTS = {
    "username": "Player",        # 离线模式游戏名
    "memory_gb": 2,              # 给游戏分配的内存
    "version_isolation": True,   # 版本隔离:每版本独立游戏目录
    "game_dir": "",              # 游戏目录(.minecraft 位置;空 = 启动器目录下默认位置)
    "skills": {},                # 技能启停状态 {技能id: true/false}(见 skill_manager.py)
    "language": "auto",          # 界面语言:auto(跟随系统)/ zh / en(见 i18n.py)
    # AI 助手(OpenAI 兼容接口)
    "ai_provider": "deepseek",
    "ai_base_url": "https://api.deepseek.com/v1",
    "ai_api_key": "",
    "ai_model": "deepseek-chat",
    "ai_permission": "readonly",   # AI 文件权限:readonly / workspace_write
    "context_window": 65536,       # AI 上下文窗口上限(tokens),DeepSeek-chat 为 64K
}


def load_settings() -> dict:
    """读配置;没有文件或文件坏了就返回默认值"""
    data = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                data.update(saved)  # 文件里的覆盖默认,缺失的补默认
        except Exception:
            pass  # 配置文件损坏:退回默认
    return data


def save_settings(settings: dict) -> None:
    """把设置写回 config.json"""
    data = dict(DEFAULTS)
    data.update(settings)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
