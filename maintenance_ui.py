"""Instance maintenance UI; all writes run through the same service as AI tools."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QComboBox, QMessageBox
from background_tasks import BackgroundTask

DESCRIPTIONS = {
    'repair_core': '重新安装当前游戏版本及当前加载器，备份并替换实例核心。存档、Mod 和配置保留。',
    'complete_files': '校验并补全游戏客户端、依赖库和资源文件。不负责重新下载第三方 Mod。',
    'reset': '备份并移走 launch_options.json、options.txt、optionsof.txt，让游戏重新生成默认设置。存档、Mod 和 Mod 配置保留。',
    'modify': '替换游戏版本或加载器并备份原核心。Mod 不会自动升级。旧存档在新版本中打开后可能无法降级，请先备份存档。',
}


def run(owner, action, **kwargs):
    from instance_maintenance import perform, imported
    if getattr(owner, '_maintenance_task', None) and owner._maintenance_task.is_running:
        QMessageBox.information(owner, '实例维护', '已有维护任务正在执行。')
        return
    instance, root = owner.inst_id, owner.game_dir
    note = DESCRIPTIONS[action]
    if action == 'modify':
        note += f"\n目标：Minecraft {kwargs['version']} / {kwargs['loader'] or '原版'} {kwargs['loader_version'] or ''}"
        note += '\n如果这是导入的整合包，请三思：版本、加载器、脚本和 Mod 往往是配套的，改动后可能无法启动。'
        if imported(owner.inst_dir):
            note += '\n已检测到整合包来源标记，建议先导出备份。'
    if QMessageBox.question(owner, '确认实例维护', f'实例：{instance}\n'+note,
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
        return
    task = BackgroundTask(lambda current: perform(root, instance, action, status=current.report_status, **kwargs), owner)
    owner._maintenance_task = task
    task.status.connect(lambda text: owner.status_msg(text))
    def complete(result):
        QMessageBox.information(owner, '实例维护完成', str(result))
        if owner.inst_id == instance:
            from instances import scan_instances
            info = next((item for item in scan_instances(root) if item['id'] == instance), None)
            if info:
                owner.set_instance(info, root, force=True)
        window = owner.window()
        if hasattr(window, 'load_versions'):
            window.load_versions()
    task.succeeded.connect(complete)
    task.failed.connect(lambda error: QMessageBox.warning(owner, '实例维护未完成', str(error)))
    task.start()


def overview_controls(owner):
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.addWidget(QLabel('维护与修复'))
    row = QHBoxLayout()
    for title, action in (('修补核心', 'repair_core'), ('补全文件', 'complete_files'), ('重置', 'reset')):
        button = QPushButton(title)
        button.setToolTip(DESCRIPTIONS[action])
        button.clicked.connect(lambda checked=False, a=action: run(owner, a))
        row.addWidget(button)
    layout.addLayout(row)
    return widget


def modify_page(owner):
    widget = QWidget()
    layout = QVBoxLayout(widget)
    info = QLabel('更改游戏版本或加载器\n建议先在“备份·存档”备份。导入整合包请三思：Mod、配置和脚本可能不兼容新版本。')
    info.setWordWrap(True)
    layout.addWidget(info)
    layout.addWidget(QLabel('Minecraft 版本'))
    version = QLineEdit(owner._inst_base)
    layout.addWidget(version)
    layout.addWidget(QLabel('加载器'))
    loader = QComboBox()
    for label, key in [('原版', ''), ('Forge', 'forge'), ('Fabric', 'fabric'), ('NeoForge', 'neoforge')]:
        loader.addItem(label, key)
    loader.setCurrentIndex(max(0, loader.findData(owner._inst_loader or '')))
    layout.addWidget(loader)
    number = QLineEdit()
    number.setPlaceholderText('加载器版本，留空由安装器选择')
    number.setEnabled(bool(loader.currentData()))
    loader.currentIndexChanged.connect(lambda: number.setEnabled(bool(loader.currentData())))
    layout.addWidget(number)
    button = QPushButton('安装并修改此实例')
    button.clicked.connect(lambda: run(owner, 'modify', version=version.text().strip(),
                                       loader=loader.currentData(), loader_version=number.text().strip() if loader.currentData() else ''))
    layout.addWidget(button)
    layout.addStretch()
    return widget
