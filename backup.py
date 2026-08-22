# -*- coding: utf-8 -*-
"""
备份机制(灵感 #6):在执行"需要进世界测试"的操作前,备份:
1. 存档 saves → 打包成 saves.zip
2. 模组列表 → mods.txt
3. 实例信息 → info.json

备份目录:.minecraft/backups/<实例名>/<时间戳>/
"""
import json
import os
import zipfile
from datetime import datetime

import paths


def backup_instance(instance_id: str, game_dir: str = None) -> str:
    """备份一个实例,返回备份目录路径。
    game_dir 缺省时用当前生效的游戏目录(paths.GAME_DIR)。"""
    if game_dir is None:
        game_dir = paths.GAME_DIR
    inst_dir = os.path.join(game_dir, "versions", instance_id)
    saves_dir = os.path.join(inst_dir, "saves")
    mods_dir = os.path.join(inst_dir, "mods")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(game_dir, "backups", instance_id, stamp)
    os.makedirs(out_dir, exist_ok=True)

    # 1) 存档打包成 zip(防坏档)
    if os.path.isdir(saves_dir):
        zip_path = os.path.join(out_dir, "saves.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _dirs, files in os.walk(saves_dir):
                for f in files:
                    full = os.path.join(root, f)
                    z.write(full, os.path.relpath(full, saves_dir))

    # 2) 模组列表 txt
    mod_lines = []
    if os.path.isdir(mods_dir):
        mod_lines = sorted(f for f in os.listdir(mods_dir) if f.endswith(".jar"))
    with open(os.path.join(out_dir, "mods.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(mod_lines))

    # 3) 实例信息
    with open(os.path.join(out_dir, "info.json"), "w", encoding="utf-8") as f:
        json.dump({"instance": instance_id, "time": stamp, "mods": mod_lines},
                  f, ensure_ascii=False, indent=2)

    return out_dir


def list_backups(instance_id: str, game_dir: str = None) -> list:
    """列出某实例的备份历史(新的在前):[{stamp, path, has_saves, has_mods}]"""
    if game_dir is None:
        game_dir = paths.GAME_DIR
    bak_dir = os.path.join(game_dir, "backups", instance_id)
    if not os.path.isdir(bak_dir):
        return []
    out = []
    for name in sorted(os.listdir(bak_dir), reverse=True):
        p = os.path.join(bak_dir, name)
        if not os.path.isdir(p):
            continue
        out.append({
            "stamp": name,
            "path": p,
            "has_saves": os.path.isfile(os.path.join(p, "saves.zip")),
            "has_mods": os.path.isfile(os.path.join(p, "mods.txt")),
        })
    return out


def set_ftb_backup_frequency(instance_id: str, minutes: int, game_dir: str = None) -> str:
    """与 FTB Backups 联动:直接改它的配置文件里的自动备份频率。
    支持新版 ftbbackups2.toml 和旧版 ftbbackups.cfg。
    返回状态信息;找不到配置文件时提示先装模组并启动过一次游戏。"""
    if game_dir is None:
        game_dir = paths.GAME_DIR
    config_dir = os.path.join(game_dir, "versions", instance_id, "config")

    # 新版 FTB Backups 2:config/ftbbackups2.toml
    toml_path = os.path.join(config_dir, "ftbbackups2.toml")
    if os.path.isfile(toml_path):
        try:
            text = open(toml_path, encoding="utf-8", errors="replace").read()
            import re
            new, n = re.subn(r"(frequency_minutes\s*=\s*)\d+",
                             rf"\g<1>{int(minutes)}", text)
            if n == 0:  # 没有该字段:在 [backups] 段里补一行
                if "[backups]" in new:
                    new = new.replace("[backups]",
                                      f"[backups]\n    frequency_minutes = {int(minutes)}", 1)
                else:
                    new += f"\n[backups]\n    frequency_minutes = {int(minutes)}\n"
            open(toml_path, "w", encoding="utf-8").write(new)
            return f"已修改 ftbbackups2.toml:自动备份间隔 = {minutes} 分钟"
        except Exception as e:
            return f"修改 ftbbackups2.toml 失败:{e}"

    # 旧版 FTB Backups:config/ftbbackups.cfg
    cfg_path = os.path.join(config_dir, "ftbbackups.cfg")
    if os.path.isfile(cfg_path):
        try:
            text = open(cfg_path, encoding="utf-8", errors="replace").read()
            import re
            new, n = re.subn(r"(frequency\s*[=:]\s*)\d+",
                             rf"\g<1>{int(minutes)}", text)
            if n == 0:
                new += f"\nbackups {{\n    frequency = {int(minutes)}\n}}\n"
            open(cfg_path, "w", encoding="utf-8").write(new)
            return f"已修改 ftbbackups.cfg:自动备份间隔 = {minutes} 分钟"
        except Exception as e:
            return f"修改 ftbbackups.cfg 失败:{e}"

    return ("未找到 FTB Backups 配置文件(config/ftbbackups2.toml 或 ftbbackups.cfg)。\n"
            "需要:先安装 FTB Backups 模组,并启动过一次游戏让配置生成。")
