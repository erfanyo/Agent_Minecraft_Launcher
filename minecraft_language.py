# -*- coding: utf-8 -*-
"""Minecraft ``options.txt`` 语言同步。

启动器界面语言为 ``auto`` 时会先由 i18n 解析系统语言；这里仅把最终基础语言
映射为 Minecraft 的语言代码。用户关闭同步后，游戏内手动选择的语言完全不受影响。
"""
from __future__ import annotations

import os


# i18n 语言 / 常见系统语言 → Minecraft assets/<namespace>/lang 中的代码。
_MC_LANGUAGE = {
    "zh": "zh_cn", "zh_cn": "zh_cn", "zh_tw": "zh_tw",
    "en": "en_us", "en_us": "en_us", "en_gb": "en_gb",
    "ja": "ja_jp", "ko": "ko_kr", "fr": "fr_fr", "de": "de_de",
    "es": "es_es", "pt": "pt_br", "pt_br": "pt_br", "pt_pt": "pt_pt",
    "ru": "ru_ru", "it": "it_it", "pl": "pl_pl", "nl": "nl_nl",
    "tr": "tr_tr", "uk": "uk_ua", "ar": "ar_sa", "sv": "sv_se",
    "da": "da_dk", "fi": "fi_fi", "nb": "no_no", "cs": "cs_cz",
    "hu": "hu_hu", "ro": "ro_ro", "bg": "bg_bg", "el": "el_gr",
}


def minecraft_language_for(launcher_language: str = "") -> str:
    """将启动器的基础语言转为 MC 语言代码；未知语言安全回退英文。"""
    code = (launcher_language or "").strip().lower().replace("-", "_")
    if not code:
        try:
            from i18n import get_base_language
            code = (get_base_language() or "").strip().lower().replace("-", "_")
        except Exception:
            code = ""
    return _MC_LANGUAGE.get(code, _MC_LANGUAGE.get(code.split("_", 1)[0], "en_us"))


def sync_minecraft_language(game_dir: str, launcher_language: str = "") -> tuple[bool, str]:
    """更新 ``game_dir/options.txt`` 内的 ``lang:`` 行。

    返回 ``(changed, mc_language)``。不触及 options 中的其他设置，也可用于首次启动。
    """
    mc_language = minecraft_language_for(launcher_language)
    if not game_dir:
        return False, mc_language
    path = os.path.join(game_dir, "options.txt")
    try:
        os.makedirs(game_dir, exist_ok=True)
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except FileNotFoundError:
            lines = []
        except UnicodeDecodeError:
            # options.txt 正常应为 UTF-8；遇到异常文件时不覆盖，交还游戏自行处理。
            return False, mc_language

        replacement = f"lang:{mc_language}"
        changed = False
        found = False
        updated = []
        for line in lines:
            if line.startswith("lang:"):
                found = True
                if line != replacement:
                    changed = True
                updated.append(replacement)
            else:
                updated.append(line)
        if not found:
            updated.append(replacement)
            changed = True
        if changed:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(updated) + "\n")
        return changed, mc_language
    except OSError:
        # 目录只读等情况不阻断正常启动。
        return False, mc_language
