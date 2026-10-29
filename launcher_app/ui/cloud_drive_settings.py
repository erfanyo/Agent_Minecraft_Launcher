"""User-only, memory-only credential handoff; never a model tool argument."""
from launcher_app.core.i18n import t
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QVBoxLayout, QLabel, QFileDialog,
                               QComboBox, QLineEdit, QPushButton)
from launcher_app.ui.settings_section import SettingsSection


def connection_section(parent=None):
    section = SettingsSection(t('整合包安全检查'), parent)
    from settings import load_settings
    from launcher_app.ui.ui_switch import ToggleSwitch, setting_switch_row
    section.defender_scan = ToggleSwitch(bool(load_settings().get('cloud_drive_defender_scan', True)))
    section.content.addWidget(setting_switch_row(
        t('原包下载完成后请求杀毒检查（优先 Defender）'), section.defender_scan))
    hint = QLabel(t('只检测、不请求清除；Defender 不可用时尝试已安装的 ESET。无法自动检查时可手动扫描。'))
    hint.setWordWrap(True)
    section.content.addWidget(hint)
    scan = QPushButton(t('选择已有原包，用本机杀软检查…'))
    status = QLabel()
    status.setWordWrap(True)
    section.content.addWidget(scan)
    section.content.addWidget(status)
    def check_existing():
        path, _ = QFileDialog.getOpenFileName(section, t('选择要检查的原始整合包'), '', t('整合包 (*.zip *.mrpack)'))
        if not path:
            return
        from launcher_app.core.background_tasks import BackgroundTask
        from launcher_app.resources.antivirus import scan_available_archive
        scan.setEnabled(False)
        status.setText(t('正在请求 Defender 检查原包，不执行包内程序…'))
        task = BackgroundTask(lambda current: scan_available_archive(path), section)
        section._scan_task = task
        def done(result):
            message = result['message']
            if result.get('report_path'):
                message += '\n本机扫描报告：' + result['report_path']
            status.setText(message)
            from launcher_app.ui.optional_notices import antivirus_notice
            antivirus_notice(section, result)
        task.succeeded.connect(done)
        task.failed.connect(lambda _: status.setText(t('扫描未完成，请检查系统杀软状态，不能认定文件已通过。')))
        task.finished.connect(lambda: scan.setEnabled(True))
        task.start()
    scan.clicked.connect(check_existing)
    return section


def credentials_dialog(parent, selected_provider=None):
    from launcher_app.resources.cloud_drives import set_credential, _credential
    dialog = QDialog(parent)
    dialog.setWindowTitle(t('本机网盘登录接续'))
    dialog.resize(600, 380)
    layout = QVBoxLayout(dialog)
    provider = QComboBox()
    provider.addItem(t('夸克网盘（Cookie）'), 'quark')
    provider.addItem(t('123 云盘（Authorization）'), '123')
    provider.addItem(t('百度网盘（Cookie）'), 'baidu')
    if selected_provider:
        provider.setCurrentIndex(max(0, provider.findData(selected_provider)))
    layout.addWidget(provider)
    instructions = QLabel()
    instructions.setWordWrap(True)
    layout.addWidget(instructions)
    login = QPushButton(t('在浏览器打开官网登录'))
    login.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(
        {'quark': 'https://pan.quark.cn/', '123': 'https://www.123pan.com/', 'baidu': 'https://pan.baidu.com/'}[provider.currentData()])))
    layout.addWidget(login)
    secret = QLineEdit()
    secret.setEchoMode(QLineEdit.EchoMode.Password)
    secret.setPlaceholderText(t('仅在这里粘贴，不要发到 AI 聊天'))
    secret.setMaxLength(16384)
    layout.addWidget(secret)
    status = QLabel()
    status.setWordWrap(True)
    layout.addWidget(status)
    clear = QPushButton(t('清除当前网盘凭证'))
    layout.addWidget(clear)
    def refresh():
        secret.clear()
        field = 'Authorization' if provider.currentData() == '123' else 'Cookie'
        origin = {'quark': 'drive-pc.quark.cn', '123': 'yun.123pan.com', 'baidu': 'pan.baidu.com'}[provider.currentData()]
        instructions.setText(t('1. 用浏览器登录官网。\n2. 按 F12 打开开发者工具，切到 Network（网络），刷新网盘列表。\n3. 选择 {v0} 的列表请求，在 Request Headers（请求头）复制 {v1} 的值，粘贴到下方。\n不需要复制完整请求，也不要运行网页提供的命令。凭证具有账号权限，只在本次启动中保存在内存，不写配置、不交给模型；关闭启动器后需要重新连接。').format(v0=(origin), v1=(field)))
        status.setText(t('已提供凭证，需通过实际请求验证是否有效。') if _credential(provider.currentData()) else t('尚未提供凭证，可先尝试免登录浏览分享。浏览器登录不会自动授权启动器。'))
    def save():
        try:
            set_credential(provider.currentData(), secret.text())
        except ValueError:
            status.setText(t('格式不正确，请只粘贴单行凭证值。'))
            return
        secret.clear()
        dialog.accept()
    def forget():
        set_credential(provider.currentData(), '')
        refresh()
    clear.clicked.connect(forget)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(save)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    provider.currentIndexChanged.connect(refresh)
    refresh()
    dialog.exec()
    secret.clear()
