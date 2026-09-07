# -*- coding: utf-8 -*-
"""Minecraft 实例安装业务。

不依赖任何窗口控件：调用者只需提供状态和进度回调，因此 GUI、CLI、AI 工具
都可以复用同一套原版、加载器与基础 Mod 安装流程。
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable

from downloader import download_with_mirror
from fetch_versions import fetch_version_detail, fetch_version_manifest
from game_files import install_version_files
from instance_wizard import OPTIMIZE_MODS, SHADER_MODS
from loaders import install_loader
from modrinth import download_mod


def _ignore_status(_message) -> None:
    pass


def _ignore_progress(_done, _total) -> None:
    pass


class InstanceInstallService:
    def __init__(self, game_root: Callable[[], str], version_isolation: Callable[[], bool]):
        self._game_root = game_root
        self._version_isolation = version_isolation

    @property
    def game_root(self) -> str:
        return self._game_root()

    def game_dir_for(self, instance_id: str) -> str:
        if self._version_isolation():
            return os.path.join(self.game_root, "versions", instance_id)
        return self.game_root

    def install_version(self, version_id: str, status_cb=None, progress_cb=None,
                        repository_only: bool = False) -> bool:
        status = status_cb or _ignore_status
        progress = progress_cb or _ignore_progress
        status(f"正在获取 {version_id} 的安装信息...")
        try:
            manifest = fetch_version_manifest()
            entry = next((v for v in manifest["versions"]
                          if v["id"] == version_id
                          and v["type"] in ("release", "snapshot")), None)
            if entry is None:
                status(f"清单里找不到 {version_id}")
                return False
            detail = fetch_version_detail(entry["url"])
        except Exception as exc:
            status(f"获取版本信息失败: {exc}")
            return False
        return self.install_detail(detail, status, progress, repository_only)

    def install_detail(self, detail: dict, status_cb=None, progress_cb=None,
                       repository_only: bool = False) -> bool:
        status = status_cb or _ignore_status
        progress = progress_cb or _ignore_progress
        client = detail.get("downloads", {}).get("client")
        if client is None:
            status(f"{detail['id']} 没有客户端 jar(该版本不可直接启动)")
            return False

        version_root = (os.path.join(self.game_root, "versions", "_versions")
                        if repository_only else os.path.join(self.game_root, "versions"))
        instance_dir = os.path.join(version_root, detail["id"])
        os.makedirs(instance_dir, exist_ok=True)
        with open(os.path.join(instance_dir, detail["id"] + ".json"),
                  "w", encoding="utf-8") as file:
            json.dump(detail, file, ensure_ascii=False, indent=2)

        try:
            destination = os.path.join(instance_dir, f"{detail['id']}.jar")
            status(f"下载客户端 {detail['id']} ...")
            download_with_mirror(
                client["url"], destination, version_id=detail["id"],
                sha1=client.get("sha1"), progress_callback=progress,
            )
            _downloaded, failures = install_version_files(
                detail, self.game_root,
                progress_callback=progress, status_callback=status,
            )
        except Exception as exc:
            status(f"安装失败: {exc}")
            return False

        if failures:
            status(f"安装完成但 {len(failures)} 个文件失败(如 {failures[0][0]})——请重试补齐")
            return False
        return True

    def create_instance(self, version: str, loader_key, modrinth_loader,
                        shader: bool, optimize: bool,
                        loader_version: str | None = None,
                        shader_version: str | None = None,
                        optimize_versions: dict | None = None,
                        fabric_api_version: str | None = None,
                        status_cb=None, progress_cb=None):
        status = status_cb or _ignore_status
        progress = progress_cb or _ignore_progress
        status(f"开始下载实例 {version} ...")
        if loader_key:
            status(f"准备基础原版 {version}({loader_key} 加载器依赖，存入版本仓库)...")
        messages = []
        def install_status(message):
            messages.append(str(message))
            status(message)
        if not self.install_version(version, install_status, progress, repository_only=bool(loader_key)):
            raise RuntimeError(messages[-1] if messages else "基础版本安装失败，请查看上方的具体原因")

        instance_id = version
        if loader_key:
            try:
                instance_id = install_loader(
                    loader_key, version, self.game_root,
                    loader_version=loader_version,
                    progress_callback=progress, status_callback=status,
                )
            except Exception as exc:
                status(f"加载器安装失败: {exc}")
                raise RuntimeError(f"加载器安装失败: {exc}") from exc

        mods_dir = os.path.join(self.game_dir_for(instance_id), "mods")
        if loader_key == "fabric" and fabric_api_version:
            self.install_mod("fabric-api", version, "fabric", mods_dir, "Fabric API",
                             fabric_api_version, status, progress)
        if shader and modrinth_loader:
            slug = SHADER_MODS.get(modrinth_loader)
            if slug:
                self.install_mod(slug, version, modrinth_loader, mods_dir, "光影",
                                 shader_version, status, progress)
        if optimize and modrinth_loader:
            for slug in OPTIMIZE_MODS.get(modrinth_loader, []):
                wanted = (optimize_versions or {}).get(slug)
                self.install_mod(slug, version, modrinth_loader, mods_dir, "优化",
                                 wanted, status, progress)

        from instance_metadata import atomic_json, read_metadata
        folder = os.path.join(self.game_root, 'versions', instance_id)
        metadata = read_metadata(folder)
        metadata['minecraft_version'] = version
        atomic_json(os.path.join(folder, 'amcl_instance.json'), metadata)
        status(f"实例就绪:{instance_id} ✅ "
               f"(游戏目录:{self.game_dir_for(instance_id)};"
               f"首次运行会生成完整目录——存档/配置/日志)")
        return instance_id

    @staticmethod
    def install_mod(slug: str, game_version: str, loader: str,
                    mods_dir: str, kind: str, version_number: str | None = None,
                    status_cb=None, progress_cb=None):
        status = status_cb or _ignore_status
        try:
            filename = download_mod(
                slug, game_version, loader, mods_dir,
                version_number=version_number, progress_callback=progress_cb,
            )
        except Exception as exc:
            status(f"{kind} Mod {slug} 下载失败: {exc}")
            raise RuntimeError(f"{kind} Mod {slug} 下载失败: {exc}") from exc
        if filename:
            status(f"{kind} Mod 已装:{filename}")
        else:
            status(f"{kind} Mod {slug} 暂无 {game_version}+{loader} 版本,已跳过")
        return filename
