"""Background preflight; threat warnings cannot be dismissed globally."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog
from launcher_app.core.background_tasks import BackgroundTask
from launcher_app.core.i18n import t


def check_before_import(window, path, ready):
    if getattr(window, '_import_safety_task', None) and window._import_safety_task.is_running:
        return
    from settings import load_settings
    from launcher_app.resources.import_safety import prepare_import
    enabled = bool(load_settings().get('cloud_drive_defender_scan', True))
    progress = QProgressDialog(t('智能导入'), '', 0, 0, window)
    progress.setCancelButton(None)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.show()
    task = BackgroundTask(lambda current: prepare_import(
        path, scan_enabled=enabled, status_callback=current.report_status), window)
    task.status.connect(progress.setLabelText)
    def done(result):
        progress.close()
        antivirus = result['antivirus']
        if antivirus['status'] == 'attention_required':
            QMessageBox.warning(window, t('原包尚未完成杀毒检查'), antivirus['message'])
            return
        from launcher_app.ui.optional_notices import antivirus_notice
        antivirus_notice(window, antivirus)
        warnings = list(dict.fromkeys(warning for layer in result['layers']
            for warning in layer['review']['warnings']))
        for layer in result['layers']:
            review = layer['review']
            if review.get('executable_or_script_count'):
                warnings.append('程序/脚本：' + str(review['executable_or_script_count'])
                    + '\n' + '\n'.join(review['executable_or_script_examples'][:10]))
        # This is a user-reviewed import, not an automatic cloud import.
        text = '\n'.join([*warnings, antivirus['message'],
            '原包保留：' + result['original'],
            '后续下载的模组不在本次原包检查范围内。',
            '导入可能安装官方加载器；不会启动游戏或执行包内启动脚本。'])
        if QMessageBox.question(window, t('智能导入'), text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            ready(result['path'])
    task.succeeded.connect(done)
    task.failed.connect(lambda error: (progress.close(), QMessageBox.warning(
        window, t('智能导入扫描失败'), error)))
    window._import_safety_task = task
    task.start()
