"""Dismissible information only; security confirmations are never suppressible."""
from launcher_app.core.i18n import t
from PySide6.QtWidgets import QMessageBox


def antivirus_notice(parent, result):
    if not result or result.get('status') in ('no_detection_reported', 'attention_required'):
        return
    from settings import load_settings, update_setting
    settings = load_settings()
    hidden = settings.get('dismissed_notices', [])
    if 'antivirus_unavailable' in hidden:
        return
    from launcher_app.ui.ui_switch import ToggleSwitch, setting_switch_row
    dialog = QMessageBox(parent)
    dialog.setWindowTitle(t('原包尚未完成杀毒检查'))
    dialog.setText(result.get('message', '无法自动完成杀毒检查。'))
    dialog.setInformativeText(t('可打开原包位置，用火绒等本机杀软手动扫描。不再提示只隐藏此类说明，扫描状态与威胁告警仍会显示。\n可在设置 → 系统 → 启动器维护恢复全部提示。'))
    skip = ToggleSwitch(False)
    dialog.layout().addWidget(setting_switch_row(t('以后不再弹出此类说明'), skip),
                              dialog.layout().rowCount(), 0, 1, dialog.layout().columnCount())
    dialog.exec()
    if skip.isChecked():
        update_setting('dismissed_notices', list(dict.fromkeys([*hidden, 'antivirus_unavailable'])))


def reset_optional_notices():
    from settings import load_settings, save_settings
    settings = load_settings()
    settings.update(dismissed_notices=[], ignore_memory_launch_advice=False,
                    backup_remind_on_exit=True, plugin_prompt_declined=[], plugin_prompt_seen=[])
    save_settings(settings)
    return settings
