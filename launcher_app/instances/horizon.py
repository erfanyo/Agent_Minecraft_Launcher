"""Experimental Horizon integration through the upstream launcher's CLI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

from launcher_app.core.safe_paths import safe_child, safe_component
from launcher_app.core.task_context import checkpoint, run_process
from launcher_app.instances.instance_maintenance import assert_not_maintaining
from launcher_app.instances.instance_metadata import HORIZON_EDITION, atomic_json, read_metadata
from os_platform.process import external_process_environment


HORIZON_LAUNCHER_URL = 'https://github.com/horizon-rust/horizon/releases'
_GAME_TAG = re.compile(r'(?:nightly-\d{4}-\d{2}-\d{2}-[0-9a-f]{7,40}|v\d+(?:\.\d+){2,3})')


def _validate_tag(tag):
    if not isinstance(tag, str) or not _GAME_TAG.fullmatch(tag):
        raise ValueError('请选择一个明确的 Horizon 发行版本。')


class HorizonLauncher:
    def __init__(self, game_root, executable):
        self.root = Path(game_root).resolve()
        self.executable = executable
        self.data_dir = self.root / '_horizon' / 'launcher'

    def _program(self):
        if not self.executable or not os.path.isabs(self.executable) or not os.path.isfile(self.executable):
            raise ValueError('请在「Rust 版 MC（实验性）」中选择已解压的 Horizon Launcher。')
        return self.executable

    def environment(self, game_dir=None):
        return {**os.environ,
                'HORIZON_LAUNCHER_HOME': str(self.data_dir),
                'HORIZON_HOME': str(game_dir or self.data_dir.parent / 'home'),
                'HORIZON_MINECRAFT_DIR': str(self.root),
                'HORIZON_LAUNCHER_NO_SELF_UPDATE': '1'}

    def open_account_ui(self):
        program = self._program()
        with external_process_environment(self.environment()) as env:
            return subprocess.Popen([program], env=env, cwd=os.path.dirname(program),
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)

    def _json(self, *args, timeout=60):
        program = self._program()
        try:
            result = run_process([program, '--json', *args], timeout=timeout,
                                 env=self.environment(), cwd=os.path.dirname(program),
                                 stdin=subprocess.DEVNULL, encoding='utf-8', errors='replace',
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f'Horizon Launcher 响应超时（{args[0]}）。') from exc
        if result.returncode:
            message = (result.stderr.strip() or result.stdout.strip())[-700:]
            raise RuntimeError(f'Horizon Launcher 执行失败（{args[0]}）：{message or result.returncode}')
        try:
            return json.loads(result.stdout)
        except ValueError as exc:
            raise RuntimeError('Horizon Launcher 返回了无法识别的版本数据，请检查所选程序版本。') from exc

    def installed_versions(self):
        data = self._json('versions', '--installed')
        if not isinstance(data, dict) or not isinstance(data.get('installed'), list):
            raise RuntimeError('Horizon Launcher 返回了无法识别的已安装版本列表。')
        return [tag for tag in data['installed'] if isinstance(tag, str) and _GAME_TAG.fullmatch(tag)]

    def versions(self):
        installed = self.installed_versions()
        try:
            rows = self._json('versions')
            if not isinstance(rows, list):
                raise RuntimeError('Horizon Launcher 返回了无法识别的发行列表。')
            tags = [row['tag'] for row in rows if isinstance(row, dict) and row.get('available_here')
                    and isinstance(row.get('tag'), str) and _GAME_TAG.fullmatch(row['tag'])]
        except RuntimeError as exc:
            if not installed:
                raise
            return [(tag, True) for tag in installed], str(exc)
        return [(tag, tag in installed) for tag in dict.fromkeys(tags + installed)], ''

    def install(self, tag, status, progress, instance_id=None):
        assert_not_maintaining()
        _validate_tag(tag)
        if instance_id is not None:
            self._editable_instance(instance_id)
        status(f'正在准备 Horizon {tag}…')
        progress(0, 1)
        if tag not in self.installed_versions():
            status(f'正在通过 Horizon Launcher 下载并校验 {tag}…')
            result = self._json('install', tag, timeout=1800)
            if not isinstance(result, dict) or result.get('installed') != tag:
                raise RuntimeError(f'Horizon Launcher 未确认安装 {tag}。')
        checkpoint()
        if instance_id is None:
            versions = Path(safe_child(self.root, 'versions'))
            versions.mkdir(parents=True, exist_ok=True)
            name = f'Horizon-{tag}'
            index = 1
            while True:
                identity = name if index == 1 else f'{name}-{index}'
                folder = versions / identity
                try:
                    folder.mkdir()
                    break
                except FileExistsError:
                    index += 1
            try:
                atomic_json(folder / 'amcl_instance.json', {'edition': HORIZON_EDITION,
                                                           'horizon_version': tag, 'display_name': identity})
            except BaseException:
                folder.rmdir()
                raise
        else:
            folder, metadata = self._editable_instance(instance_id)
            metadata['horizon_version'] = tag
            atomic_json(folder / 'amcl_instance.json', metadata)
        progress(1, 1)
        status(f'Horizon 实例「{folder.name}」已固定到 {tag}。')
        return folder.name

    def _instance(self, instance_id):
        safe_component(instance_id)
        folder = Path(safe_child(self.root, f'versions/{instance_id}'))
        metadata = read_metadata(folder)
        if metadata.get('edition') != HORIZON_EDITION:
            raise ValueError('Horizon 实例已不存在，请刷新实例列表。')
        return folder, metadata

    def _editable_instance(self, instance_id):
        from launcher_app.instances.instances import detect_running_clients

        folder, metadata = self._instance(instance_id)
        if detect_running_clients({instance_id: str(folder)}, horizon_only=True):
            raise RuntimeError('请先关闭该 Horizon 实例，再更换版本。')
        return folder, metadata

    def prepare_launch(self, instance_id, status):
        from launcher_app.instances.game_launch_service import LaunchPlan

        assert_not_maintaining()
        program = self._program()
        folder, metadata = self._instance(instance_id)
        tag = metadata.get('horizon_version')
        _validate_tag(tag)
        if tag not in self.installed_versions():
            raise RuntimeError(f'本机缺少 Horizon {tag}，请在实例菜单中选择「更换 Horizon 版本」重新下载。')
        account = self._json('account', 'list')
        if isinstance(account, dict) and account.get('owner') is False:
            raise RuntimeError('请先在「Rust 版 MC（实验性）」中打开 Horizon 登录，并登录拥有 Java 版的微软账号。')
        if status:
            status('Horizon Launcher 将检查正版账号并准备游戏资源。')
        return LaunchPlan(instance_id=instance_id, detail={'id': instance_id}, game_dir=str(folder),
                          java_exe=None, command=[program, 'play', '--instance', 'horizon', '--version', tag],
                          first_run=not (folder / 'saves').is_dir(), game_root=str(self.root),
                          environment=self.environment(folder))
