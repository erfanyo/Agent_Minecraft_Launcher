# -*- coding: utf-8 -*-
"""Minecraft 启动前准备服务。

负责把“实例描述 + 用户设置”转换为可执行的启动计划；不创建窗口、不启动进程。
界面层可根据异常类型决定如何提示玩家。
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass

import i18n
from fetch_versions import fetch_version_detail
from java_manager import ensure_java, java_major, minecraft_java_warning
from launcher import build_launch_command, resolve_inherited_json
from minecraft_language import sync_minecraft_language
from modpack import heal_instance_json


class LoginRequiredError(RuntimeError):
    """强制正版模式下，本机还没有可用的正版身份。"""


@dataclass(frozen=True)
class LaunchPlan:
    instance_id: str
    detail: dict
    game_dir: str
    java_exe: str
    command: list[str]
    first_run: bool


class GameLaunchService:
    def __init__(self, game_root: Callable[[], str], runtime_root: Callable[[], str],
                 settings: Callable[[], dict], save_settings_fn: Callable[[dict], None],
                 game_dir_for: Callable[[str], str]):
        self._game_root = game_root
        self._runtime_root = runtime_root
        self._settings = settings
        self._save_settings = save_settings_fn
        self._game_dir_for = game_dir_for

    def load_version_data(self, version: dict) -> dict:
        if version.get("local"):
            return resolve_inherited_json(version["id"], self._game_root())
        return fetch_version_detail(version["url"])

    def prepare(self, version: dict, status_cb=None, progress_cb=None) -> LaunchPlan:
        status = status_cb or (lambda _message: None)
        progress = progress_cb or (lambda _done, _total: None)
        settings = self._settings()
        instance_id = version["id"]

        if version.get("local"):
            heal_instance_json(instance_id, self._game_root())
        detail = self.load_version_data(version)
        required_java = (detail.get("javaVersion") or {}).get("majorVersion", 8)

        launch_options = self._load_launch_options(instance_id)
        selected_java = str(launch_options.get("java_path") or "").strip()
        if selected_java:
            if not os.path.isfile(selected_java):
                raise RuntimeError(f"本实例指定的 Java 不存在：{selected_java}")
            warning = minecraft_java_warning(
                version.get("base") or detail.get("inheritsFrom") or detail.get("id", ""),
                java_major(selected_java),
            )
            if warning:
                status("⚠ " + warning)
            java_exe = selected_java
        else:
            configured = str((settings.get("java_paths") or {}).get(str(required_java)) or "").strip()
            configured_major = java_major(configured) if os.path.isfile(configured) else 0
            configured_warning = minecraft_java_warning(
                version.get("base") or detail.get("inheritsFrom") or detail.get("id", ""),
                configured_major,
            ) if configured else ""
            if configured and configured_major > 0 and not configured_warning:
                java_exe = configured
                status(f"使用设置中的 Java {configured_major}: {configured}")
            else:
                if configured:
                    status("⚠ 设置中的 Java 不可用或不兼容，改用自动选择")
                java_exe = ensure_java(
                    self._runtime_root(), required_java,
                    progress_callback=progress,
                    status_callback=status,
                    max_major=8 if required_java <= 8 else None,
                    prefer_managed=(required_java <= 8),
                )

        game_dir = self._game_dir_for(instance_id)
        self._prepare_instance_files(version, game_dir, settings, status)
        auth, username = self._resolve_auth(settings)
        if settings.get("microsoft_login", True) and not (settings.get("ms_credentials") or {}).get("uuid"):
            raise LoginRequiredError("本机还没有正版账号，请先完成微软正版登录。")

        instance_memory = int(launch_options.get("memory_gb") or 0)
        memory_gb = instance_memory if instance_memory > 0 else settings.get("memory_gb", 4)
        command = build_launch_command(
            detail, game_dir, java_exe,
            username=username,
            memory_gb=memory_gb,
            assets_dir=os.path.join(self._game_root(), "assets"),
            install_dir=self._game_root(),
            auth=auth,
        )
        return LaunchPlan(
            instance_id=instance_id,
            detail=detail,
            game_dir=game_dir,
            java_exe=java_exe,
            command=command,
            first_run=not os.path.isdir(os.path.join(game_dir, "saves")),
        )

    def _load_launch_options(self, instance_id: str) -> dict:
        path = os.path.join(self._game_root(), "versions", instance_id, "launch_options.json")
        try:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as file:
                    value = json.load(file)
                return value if isinstance(value, dict) else {}
        except Exception:
            pass
        return {}

    @staticmethod
    def _prepare_instance_files(version: dict, game_dir: str, settings: dict,
                                status: Callable[[str], None]) -> None:
        loader = version.get("loader") or ""
        base = version.get("base") or ""
        if loader in ("fabric", "forge", "neoforge") and base:
            try:
                import bridge_mod_dist
                removed = bridge_mod_dist.remove_incompatible_bridge_jars(game_dir, loader, base)
                if removed:
                    status("已移除不兼容的 bridge-mod: " + ", ".join(removed))
            except Exception:
                pass
        if settings.get("sync_minecraft_language", True):
            try:
                sync_minecraft_language(game_dir, i18n.get_base_language())
            except Exception:
                pass

    def _resolve_auth(self, settings: dict) -> tuple[dict | None, str]:
        auth = None
        username = settings.get("username", "Player")
        if settings.get("login_method") != "microsoft":
            return auth, username

        credentials = dict(settings.get("ms_credentials") or {})
        if credentials.get("refresh_token"):
            try:
                from microsoft_auth import refresh_with_ms_refresh
                refreshed = refresh_with_ms_refresh(credentials["refresh_token"])
                credentials.update({
                    "refresh_token": refreshed.get("refresh_token", credentials.get("refresh_token", "")),
                    "access_token": refreshed.get("access_token", credentials.get("access_token", "")),
                    "uuid": refreshed.get("uuid", credentials.get("uuid", "")),
                    "username": refreshed.get("username", credentials.get("username", "")),
                })
                settings["ms_credentials"] = credentials
                self._save_settings(settings)
            except Exception:
                pass
        if credentials.get("access_token") and credentials.get("uuid"):
            auth = {
                "uuid": credentials.get("uuid", ""),
                "access_token": credentials.get("access_token", ""),
                "refresh_token": credentials.get("refresh_token", ""),
                "username": credentials.get("username", ""),
                "token_type": "msa",
            }
            username = credentials.get("username") or username
        return auth, username
