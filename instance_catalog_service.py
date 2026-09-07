# -*- coding: utf-8 -*-
"""实例目录扫描、旧基础版本整理与实例记录维护。"""
from __future__ import annotations

import datetime
import json
import os
import shutil
from collections.abc import Callable

from instances import scan_instances


class InstanceCatalogService:
    def __init__(self, game_root: Callable[[], str], game_dir_for: Callable[[str], str]):
        self._game_root = game_root
        self._game_dir_for = game_dir_for

    @property
    def game_root(self) -> str:
        return self._game_root()

    def refresh(self) -> list[dict]:
        self.tidy_base_versions()
        instances = scan_instances(self.game_root)
        bases_in_use = {item["base"] for item in instances if item["loader"]}
        return [
            item for item in instances
            if not (
                item["loader"] is None
                and item["id"] in bases_in_use
                and not os.path.isdir(os.path.join(self._game_dir_for(item["id"]), "saves"))
            )
        ]

    def tidy_base_versions(self) -> None:
        try:
            instances = scan_instances(self.game_root)
        except Exception:
            return
        bases_in_use = {item["base"] for item in instances if item["loader"]}
        repository = os.path.join(self.game_root, "versions", "_versions")
        for item in instances:
            if item["loader"] is not None or item["id"] not in bases_in_use:
                continue
            instance_dir = os.path.join(self.game_root, "versions", item["id"])
            expected = {item["id"] + ".json", item["id"] + ".jar"}
            try:
                if set(os.listdir(instance_dir)) != expected:
                    continue
            except OSError:
                continue
            destination = os.path.join(repository, item["id"])
            try:
                if not os.path.isdir(destination) and os.path.isdir(instance_dir):
                    os.makedirs(repository, exist_ok=True)
                    shutil.move(instance_dir, destination)
            except OSError:
                pass

    def write_record(self, instances: list[dict]) -> None:
        versions_dir = os.path.join(self.game_root, "versions")
        path = os.path.join(versions_dir, "实例记录.json")
        old_notes = {}
        try:
            with open(path, encoding="utf-8") as file:
                old = json.load(file)
            for item in old.get("instances", []):
                if isinstance(item, dict) and item.get("id") and item.get("note"):
                    old_notes[item["id"]] = item["note"]
        except (OSError, ValueError, TypeError):
            pass

        data = {
            "note": "实例记录(启动器自动生成,可手动编辑补充说明;每实例的 note 会保留)",
            "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "instances": [
                {
                    "id": item["id"],
                    "loader": item.get("loader") or "原版",
                    "base": item.get("base", ""),
                    "note": old_notes.get(item["id"], ""),
                }
                for item in instances
            ],
        }
        try:
            os.makedirs(versions_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
        except OSError:
            pass

        try:
            old_path = os.path.join(versions_dir, "打小抄.txt")
            if os.path.exists(old_path):
                os.remove(old_path)
        except OSError:
            pass
