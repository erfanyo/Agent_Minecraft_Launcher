"""Captured resource and pack jobs shared by frontends; no windows or widgets.

Frontends review dependencies and submit run(status, progress) to their runner.
Jobs capture destination/version inputs before a worker starts. Original pack
archives remain in the permanent download directory on success and failure.
"""
from copy import deepcopy
from dataclasses import dataclass
import os
from launcher_app.core.task_context import TaskCancelled


@dataclass(frozen=True)
class ResourcePreferences:
    game_version: str | None
    loader: str | None


def resource_preferences(instance, sub_dir):
    if sub_dir == 'shaderpacks':
        version = None
    elif sub_dir in ('datapacks', 'resourcepacks'):
        version = instance.get('base') if instance else None
    else:
        version = (instance['base'] if instance else '1.21.1') or '1.21.1'
    return ResourcePreferences(version, instance.get('loader') if instance and sub_dir == 'mods' else None)


@dataclass(frozen=True)
class DependencyReview:
    missing: tuple = ()
    optional: tuple = ()
    incompatible: tuple = ()


class ResourceDownloadJob:
    def __init__(self, hit, version, instance, target_dir, sub_dir):
        self.hit = deepcopy(hit)
        self.version = deepcopy(version)
        self.instance = deepcopy(instance)
        self.target_dir = target_dir
        self.sub_dir = sub_dir
        self.preferences = resource_preferences(self.instance, sub_dir)

    @property
    def is_curseforge(self):
        return self.hit.get('source') == 'curseforge'

    def dependency_review(self):
        if self.is_curseforge or self.sub_dir != 'mods':
            return DependencyReview()
        from launcher_app.resources.modrinth import (
            dependency_is_installed, installed_mod_identifiers, resolve_dependencies)
        try:
            deps = resolve_dependencies(self.hit['slug'], self.preferences.game_version,
                                        self.preferences.loader, self.version)
        except Exception:
            return DependencyReview()
        if not deps:
            return DependencyReview()
        installed = installed_mod_identifiers(self.target_dir)
        return DependencyReview(
            tuple(dep for dep in deps['required'] if not dependency_is_installed(dep, installed)),
            tuple(deps['optional']), tuple(deps['incompatible']))

    def run(self, status, progress, *, dependencies=(), skipped_dependencies=False):
        if self.is_curseforge:
            from launcher_app.resources.curseforge import download_mod
            try:
                filename = download_mod(self.hit.get('curseforge_id'), self.version['file_id'],
                                        self.target_dir, progress_callback=progress)
            except TaskCancelled:
                raise
            except Exception as exc:
                raise RuntimeError(f"下载 CurseForge 资源 {self.hit.get('title') or 'CurseForge 资源'} 失败: {exc}") from exc
        else:
            from launcher_app.resources.modrinth import (
                dependency_is_installed, download_mod, installed_mod_identifiers)
            if skipped_dependencies:
                status('已手动跳过前置，仅下载所选 Mod；缺少必需前置可能导致游戏无法加载。')
            installed = installed_mod_identifiers(self.target_dir) if dependencies else set()
            for dep in dependencies:
                if dependency_is_installed(dep, installed):
                    status(f"已跳过已有前置: {dep['title']}")
                    continue
                try:
                    name = download_mod(dep['slug'], self.preferences.game_version,
                                        self.preferences.loader, self.target_dir, progress_callback=progress)
                    if name:
                        status(f'依赖已装:{name}')
                        installed = installed_mod_identifiers(self.target_dir)
                except TaskCancelled:
                    raise
                except Exception as exc:
                    status(f"依赖 {dep['slug']} 装入失败(跳过): {exc}")
            filename = download_mod(self.hit['slug'], self.preferences.game_version,
                                    self.preferences.loader, self.target_dir,
                                    version_number=self.version, progress_callback=progress)
            if not filename:
                version, loader = self.preferences.game_version, self.preferences.loader
                if version:
                    target = f"{version}{'+' + loader if loader else ''}"
                    raise RuntimeError(f"{self.hit['slug']} 没有适用于 {target} 的可下载文件；请在详情中更换文件版本，或调整顶部筛选")
                raise RuntimeError(f"{self.hit['slug']} 所选版本没有可下载文件；请在详情中更换文件版本")
        status(f'✅ 已下载 {filename} → {self.sub_dir}')
        return filename


@dataclass(frozen=True)
class ArchiveImportJob:
    path: str
    game_root: str
    mc_version: str | None = None
    loader: str | None = None
    instance_id: str | None = None

    def run(self, status, progress):
        from launcher_app.resources.modpack import import_modpack
        done = import_modpack(self.path, self.game_root, mc_version=self.mc_version,
                              loader=self.loader, instance_id=self.instance_id,
                              status_callback=status, progress_callback=progress)
        status(f'整合包导入完成:{done}')
        return done


class PackDownloadJob:
    def __init__(self, hit, version, game_root):
        self.hit, self.version = deepcopy(hit), deepcopy(version)
        self.game_root = game_root

    def run(self, status, progress):
        from launcher_app.resources.pack_downloads import new_download_directory
        from launcher_app.resources.modpack import import_modpack
        from launcher_app.resources.modrinth import download_modpack
        directory = new_download_directory(self.game_root)
        title = self.hit.get('title', self.hit['slug'])
        status(f'下载整合包 {title}...')
        try:
            if self.hit.get('source') == 'curseforge':
                from launcher_app.resources.curseforge import download_mod
                if not isinstance(self.version, dict) or not self.version.get('file_id'):
                    raise ValueError('请先选择一个 CurseForge 整合包文件版本')
                filename = download_mod(self.hit['curseforge_id'], self.version['file_id'], directory,
                                        progress_callback=progress)
                local = os.path.join(directory, filename)
            else:
                local = download_modpack(self.hit['slug'], directory, version_number=self.version,
                                         progress_callback=progress)
            if not local:
                raise RuntimeError('该整合包没有可下载的文件')
        except TaskCancelled:
            raise
        except Exception as exc:
            raise RuntimeError(f'下载整合包失败:{type(exc).__name__}: {exc}') from exc
        status('导入整合包(自动装基础+加载器+全部 mod,可能要几分钟)...')
        try:
            instance_id = import_modpack(local, self.game_root, status_callback=status,
                                         progress_callback=progress)
        except TaskCancelled:
            raise
        except Exception as exc:
            raise RuntimeError(f'整合包导入失败:{type(exc).__name__}: {exc}'
                               f'(同名实例可先在「我的版本」删除或改名后重试)。原包已保留：{local}') from exc
        status(f'整合包导入完成:{instance_id}；原包已保留，可分享：{local}')
        return instance_id
