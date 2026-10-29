'本体浏览器助手设置：用户授权后连接已有浏览器扩展。'
from launcher_app.core.i18n import t
FEATURE_ID = 'browser_assistant'
FEATURE_NAME = '浏览器助手'
FEATURE_DESCRIPTION = '连接 Playwright 扩展，让 AI 使用你选定的浏览器标签页。'
FEATURE_VERSION = '0.1.0'
FEATURE_API_VERSION = 1


def register(api):
    def build():
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton
        from settings import load_settings
        settings = load_settings()
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel(t('连接已安装的 Playwright 扩展。点击“一键配置”准备连接组件。\n已有 Node.js 时直接使用；缺少时下载官方安装程序，并弹出 Windows 系统授权。\n仅 Node.js 安装程序使用管理员权限，启动器和浏览器操作保持普通权限。\n不会下载浏览器内核；首次配置需要联网。\n读取页面无需逐次确认；点击、输入、导航等交互需确认。\n不开放脚本执行、文件上传、Cookie 导出或浏览器配置修改。\n令牌保存在本机配置中（未加密），请勿分享 AMCL 配置文件。\n保存后重新打开 AI 对话；禁用后断开本地连接。'))
        label.setWordWrap(True)
        layout.addWidget(label)
        from launcher_app.browser.browser_setup import ready, configure
        status = QLabel(t('连接组件已就绪') if ready() else t('连接组件尚未配置'))
        status.setWordWrap(True)
        layout.addWidget(status)
        setup = QPushButton(t('一键配置 / 修复'))
        layout.addWidget(setup)

        def start_setup():
            from launcher_app.core.background_tasks import BackgroundTask
            setup.setEnabled(False)
            setup.setText(t('正在配置…'))
            status.setText(t('正在检查运行组件…'))
            task = BackgroundTask(lambda current: configure(current.report_status), widget)
            widget._browser_setup_task = task
            task.status.connect(status.setText)
            task.succeeded.connect(status.setText)
            task.failed.connect(status.setText)

            def finished():
                setup.setEnabled(True)
                setup.setText(t('一键配置 / 修复'))

            task.finished.connect(finished)
            task.start()

        setup.clicked.connect(start_setup)
        widget._browser_setup_button = setup
        widget._browser_setup_status = status
        from launcher_app.ui.ui_switch import ToggleSwitch, setting_switch_row
        enabled = ToggleSwitch(bool(settings.get('browser_agent_enabled', False)))
        layout.addWidget(setting_switch_row(t('允许 AI 连接浏览器'), enabled))
        token = QLineEdit()
        token.setEchoMode(QLineEdit.EchoMode.Password)
        token.setPlaceholderText(t('粘贴扩展中的连接令牌'))
        token.setText(settings.get('browser_extension_token', ''))
        layout.addWidget(token)
        widget._browser_agent_fields = (enabled, token)
        layout.addStretch()
        return widget
    api.register_settings_page(build)
