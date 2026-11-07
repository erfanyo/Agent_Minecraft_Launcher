"""Local import interaction with explicit ports; never reads a main window's state."""
import logging
import os
from PySide6.QtWidgets import QInputDialog
from launcher_app.core.i18n import t
from launcher_app.resources.download_jobs import ArchiveImportJob
from launcher_app.resources.modpack import detect_modpack_format, suggested_instance_id
from launcher_app.ui.ui_notifications import task_notice, task_warning

logger = logging.getLogger(__name__)


class PackImportController:
    def __init__(self, *, parent, smart_enabled, smart_import, choose_archive,
                 check_archive, import_server, import_directory, submit, game_root, show_status):
        self.parent = parent
        self.smart_enabled = smart_enabled
        self.smart_import = smart_import
        self.choose_archive = choose_archive
        self.check_archive = check_archive
        self.import_server = import_server
        self.import_directory = import_directory
        self.submit = submit
        self.game_root = game_root
        self.show_status = show_status

    def import_archive(self, path=None, *, safety_checked=False, classic=True):
        if self.smart_enabled():
            self.smart_import(path or None, safety_checked=safety_checked)
            return
        path = path or self.choose_archive()
        if not path:
            return
        if not safety_checked:
            self.check_archive(path, lambda prepared: self.import_archive(
                prepared, safety_checked=True, classic=classic))
            return
        if not classic and os.path.isdir(path):
            self.import_directory(path)
            return
        try:
            fmt = detect_modpack_format(path)
        except Exception:
            logger.debug('Cannot inspect imported archive', exc_info=True)
            fmt = None
        if fmt == 'server':
            self.import_server(path)
            return
        mc_version, loader, instance_id = None, None, None
        if fmt == 'flat':
            mc_version, ok = QInputDialog.getText(
                self.parent, t('导入扁平整合包'), t('该整合包没有清单,请填游戏版本(如 1.20.1):'))
            if not ok or not mc_version.strip():
                return
            mc_version = mc_version.strip()
            loader, ok = QInputDialog.getItem(
                self.parent, t('导入扁平整合包') if classic else t('加载器'),
                t('加载器(可选,跳过=原版):'), ['(原版)', 'fabric', 'forge', 'neoforge'], 0, False)
            loader = loader if ok and loader != '(原版)' else None
        elif fmt is None:
            if classic:
                task_warning(self.parent, t('导入整合包'),
                             t('无法识别该文件的格式(既不是 Modrinth/CurseForge,也不像实例文件夹 zip)'))
            else:
                task_notice(self.parent, t('拖入文件'),
                            t('无法识别该文件为整合包(Modrinth/CurseForge/实例文件夹 zip)。'))
            return
        root = self.game_root()
        if classic:
            try:
                default_id = suggested_instance_id(path)
                if default_id and os.path.isdir(os.path.join(root, 'versions', default_id)):
                    instance_id, ok = QInputDialog.getText(
                        self.parent, t('实例名重复'), t('已存在实例「{v0}」,请为新实例命名:').format(v0=default_id),
                        text=default_id + '-2')
                    if not ok or not instance_id.strip():
                        return
                    instance_id = instance_id.strip()
            except Exception:
                logger.debug('Optional import name preflight failed', exc_info=True)
        self.show_status('正在导入整合包...')
        self.submit(ArchiveImportJob(path, root, mc_version, loader, instance_id).run)
