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

from paths import GAME_DIR


def backup_instance(instance_id: str, game_dir: str = GAME_DIR) -> str:
    """备份一个实例,返回备份目录路径"""
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
