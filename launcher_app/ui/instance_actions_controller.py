"""Instance action dialogs; filesystem operations belong to InstanceActions."""
from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox
from launcher_app.core.i18n import t
from launcher_app.ui.ui_notifications import inline_notice, inline_warning, task_warning, action_question


class InstanceActionsController:
    def __init__(self, *, parent, service_factory, busy_any, busy_instance, settings,
                 save_last_played, refresh, select, reload_versions, show_status, log_feedback):
        self.parent, self.service_factory = parent, service_factory
        self.busy_any, self.busy_instance, self.settings = busy_any, busy_instance, settings
        self.save_last_played = save_last_played
        self.refresh, self.select, self.reload_versions = refresh, select, reload_versions
        self.show_status, self.log_feedback = show_status, log_feedback

    def backup(self, instance):
        try:
            result = self.service_factory().backup(instance['id'])
        except Exception as exc:
            task_warning(self.parent, t('备份失败'), str(exc))
            return
        self.show_status(f'已备份到:{result}')

    def rename(self, instance):
        if self.busy_any():
            inline_notice(self.parent,t('稍等一下'),t('游戏或安装任务还在运行，结束后再改名吧。'))
            return
        service = self.service_factory()
        name, accepted = QInputDialog.getText(
            self.parent, t('重命名实例'),
            t('新名称（中文、英文、数字和空格均可）：\n不能留空，不能包含 \\ / : * ? " < > |\n不能以下划线开头、以句点结尾，或使用 CON、NUL、COM1 等系统保留名。\n不能与已有实例重名。安装目录和版本文件会同步改名，存档与配置保留。'),
            QLineEdit.EchoMode.Normal, instance.get('name') or instance['id'])
        if not accepted:
            return
        try:
            new_id = service.rename(instance['id'], name)
        except (OSError, ValueError, RuntimeError) as exc:
            inline_warning(self.parent,t('名称暂时没改成'),str(exc))
            return
        settings = self.settings()
        if settings.get('last_played_instance') == instance['id']:
            settings['last_played_instance'] = new_id
            try:
                self.save_last_played(new_id)
            except OSError as exc:
                self.log_feedback(f'实例已改名，但最近游玩记录保存失败：{exc}')
        self.refresh()
        self.select(new_id)
        self.show_status(f'实例和安装目录已改名为：{new_id}')

    def delete(self, instance):
        if self.busy_instance(instance['id']):
            inline_notice(self.parent,t('稍等一下'),t('游戏正在运行，或文件还在准备中，结束后再删除实例吧。'))
            return
        service = self.service_factory()
        if action_question(self.parent,t('确认删除'),
                t('确定删除实例 {v0} 吗?\n(只删该实例,共用文件保留)').format(v0=instance['id']),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
            return
        try:
            service.delete(instance['id'])
        except (OSError,ValueError) as exc:
            task_warning(self.parent,t('确认删除'),str(exc))
            return
        self.show_status(f"实例已删除:{instance['id']}")
        self.refresh()

    def clear(self):
        if self.busy_any():
            inline_notice(self.parent, t('稍等一下'), t('游戏正在运行，或文件还在准备中，结束后再删除实例吧。'))
            return
        service = self.service_factory()
        if action_question(self.parent,t('确认'),t('确定要删除所有实例吗?\n(versions 目录会被清空,共用文件保留)'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
            return
        try:
            result = service.clear_all()
        except (OSError,ValueError) as exc:
            task_warning(self.parent,t('确认'),str(exc))
            return
        self.reload_versions()
        self.refresh()
        if result.failures:
            task_warning(self.parent,t('确认'), '\n'.join(f'{name}: {error}' for name,error in result.failures))
        else:
            self.show_status('所有实例已清空')
