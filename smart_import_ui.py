"""Optional GUI for smart import; the deterministic core remains headless."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressDialog,
    QPushButton, QTextBrowser, QVBoxLayout)

from background_tasks import BackgroundTask
from smart_import import ai_author_prompt, execute_import_plan, scan_import_source
import paths


_KIND_NAMES = {'client': '安装客户端', 'server': '安装服务端', 'docs': '导入附加资料',
               'unknown': '类型待确认'}


def _report_text(report):
    lines = [f"来源：{report['sourceName']}",
             f"内容：{len(report['files'])} 个文件，约 {report['expandedBytes'] / 1024**2:.1f} MiB", '',
             '检测结果']
    for item in report.get('components', []):
        environment = []
        if item.get('minecraftVersion'):
            environment.append('MC ' + item['minecraftVersion'])
        if item.get('loader'):
            environment.append(str(item['loader']))
        lines.extend([
            f"• {_KIND_NAMES.get(item['type'], item['type'])} · 置信度 {item['confidence']:.0%}",
            f"  根目录：{item.get('root') or '(包根部)'}" + (f" · {' / '.join(environment)}" if environment else ''),
            f"  依据：{'、'.join(item.get('evidence') or ['无'])}",
        ])
    materials = report.get('authorMaterials') or []
    if materials:
        lines.extend(['', f'作者资料（{len(materials)} 项）'])
        for item in materials[:20]:
            note = '可读取文本' if item['kind'] == 'text' else '只登记，暂不自动解析'
            lines.append(f"• {item['path']} · {note}")
        if len(materials) > 20:
            lines.append(f'• 另有 {len(materials) - 20} 项…')
    lines.extend(['', '风险与限制'])
    lines.extend('• ' + value for value in (report.get('risks') or ['未发现额外风险']))
    lines.append('• 所有脚本均不会执行；AI 不参与目录映射与安装决策。')
    return '\n'.join(lines)


class SmartImportPreview(QDialog):
    def __init__(self, report, ai_callback=None, parent=None):
        super().__init__(parent)
        self.report = report
        self.setWindowTitle('智能导入 · 检测结果')
        self.resize(760, 680)
        layout = QVBoxLayout(self)
        intro = QLabel('AMCL 已完成严格扫描。请分别选择要安装的组件；每项独立处理，某一项失败不会撤销其他成功项。')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        body = QTextBrowser()
        body.setPlainText(_report_text(report))
        layout.addWidget(body, 1)
        self.checks = {}
        self.override_boxes = {}
        defaults = set(report.get('defaultSelected') or [])
        for component in report.get('components', []):
            if component['type'] == 'unknown':
                row = QHBoxLayout()
                label = QLabel(f"未确定内容（{component['confidence']:.0%}）：")
                choice = QComboBox()
                choice.addItem('仅查看，不安装', None)
                choice.addItem('我确认它是客户端', 'client')
                choice.addItem('我确认它是服务端', 'server')
                self.override_boxes[component['id']] = choice
                row.addWidget(label)
                row.addWidget(choice, 1)
                layout.addLayout(row)
                continue
            check = QCheckBox(
                f"{_KIND_NAMES.get(component['type'], component['type'])}  "
                f"({component.get('root') or '包根部'} · {component['confidence']:.0%})")
            check.setChecked(component['id'] in defaults)
            self.checks[component['id']] = check
            layout.addWidget(check)
        client = next((item for item in report.get('components', []) if item['type'] == 'client'), None)
        server = next((item for item in report.get('components', []) if item['type'] == 'server'), None)
        unknown = next((item for item in report.get('components', []) if item['type'] == 'unknown'), None)
        form = QFormLayout()
        base_name = Path(report['sourceName']).name
        for suffix in ('.tar.gz', '.tar.xz', '.mrpack', '.zip', '.tgz', '.tar'):
            if base_name.casefold().endswith(suffix):
                base_name = base_name[:-len(suffix)]
                break
        self.client_name = QLineEdit(base_name or '导入的整合包')
        self.server_name = QLineEdit((base_name or '导入的整合包') + '-server')
        self.mc_version = QLineEdit((client or {}).get('minecraftVersion') or '')
        self.loader = QComboBox()
        self.loader.addItems(['(原版 / 未知)', 'fabric', 'forge', 'neoforge', 'quilt'])
        detected_loader = (client or {}).get('loader')
        if detected_loader:
            found = self.loader.findText(str(detected_loader))
            if found >= 0:
                self.loader.setCurrentIndex(found)
        if client or unknown:
            form.addRow('客户端名称：', self.client_name)
            form.addRow('Minecraft 版本：', self.mc_version)
            form.addRow('客户端加载器：', self.loader)
        if server or unknown:
            form.addRow('服务端名称：', self.server_name)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self.ai_button = QPushButton('让 AI 整理作者说明')
        self.ai_button.setEnabled(ai_callback is not None)
        if ai_callback:
            self.ai_button.clicked.connect(lambda: ai_callback(report))
        view_only = QPushButton('仅查看，关闭')
        view_only.clicked.connect(self.reject)
        install = QPushButton('按勾选项导入')
        install.setDefault(True)
        install.clicked.connect(self._accept_checked)
        buttons.addWidget(self.ai_button)
        buttons.addStretch()
        buttons.addWidget(view_only)
        buttons.addWidget(install)
        layout.addLayout(buttons)

    def _accept_checked(self):
        overrides = {key: box.currentData() for key, box in self.override_boxes.items()
                     if box.currentData()}
        if not any(check.isChecked() for check in self.checks.values()) and not overrides:
            QMessageBox.information(self, '没有选择组件', '请勾选至少一个组件，或者选择“仅查看”。')
            return
        client_selected = ((self.checks.get('client') and self.checks['client'].isChecked())
                           or 'client' in overrides.values())
        client = next((item for item in self.report.get('components', []) if item['type'] == 'client'), None)
        if client_selected and not ((client or {}).get('minecraftVersion') or self.mc_version.text().strip()):
            QMessageBox.information(self, '需要 Minecraft 版本', '扫描器无法确定客户端版本，请填写例如 1.20.1。')
            return
        self.accept()

    def selection(self):
        loader = self.loader.currentText()
        overrides = {key: box.currentData() for key, box in self.override_boxes.items()
                     if box.currentData()}
        return {
            'selected': ([key for key, check in self.checks.items() if check.isChecked()]
                         + list(overrides)),
            'type_overrides': overrides,
            'mc_version': self.mc_version.text().strip() or None,
            'loader': None if loader.startswith('(') else loader,
            'client_name': self.client_name.text().strip() or None,
            'server_name': self.server_name.text().strip() or None,
        }


def _choose_source(window):
    choice = QMessageBox(window)
    choice.setWindowTitle('智能导入')
    choice.setText('选择整合包来源。7z / RAR 请先解压成文件夹。')
    choice.setInformativeText(
        '网盘文件请先用浏览器或官方客户端下载；下载完成后，可直接选择压缩包或把文件夹拖进 AMCL。'
    )
    archive = choice.addButton('选择压缩包', QMessageBox.ButtonRole.AcceptRole)
    folder = choice.addButton('选择文件夹', QMessageBox.ButtonRole.ActionRole)
    choice.addButton(QMessageBox.StandardButton.Cancel)
    choice.exec()
    if choice.clickedButton() is archive:
        path, _ = QFileDialog.getOpenFileName(
            window, '选择整合包', '',
            '支持的包 (*.mrpack *.zip *.tar *.tar.gz *.tar.xz *.tgz);;所有文件 (*)')
        return path
    if choice.clickedButton() is folder:
        return QFileDialog.getExistingDirectory(window, '选择整合包文件夹')
    return ''


def _ai_summary(window, report):
    dock = getattr(window, 'ai_dock', None)
    if dock is None:
        QMessageBox.information(window, 'AI 助手不可用', '确定性扫描和导入仍可正常使用。')
        return
    dock.show()
    dock.raise_()
    dock.ask(ai_author_prompt(report))


def _execute(window, report, selection):
    progress = QProgressDialog('正在准备独立导入事务…', '', 0, 0, window)
    progress.setWindowTitle('智能导入')
    progress.setCancelButton(None)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.show()
    def work(task):
        return execute_import_plan(
            report, selection['selected'], paths.GAME_DIR,
            mc_version=selection['mc_version'], loader=selection['loader'],
            client_name=selection['client_name'], server_name=selection['server_name'],
            type_overrides=selection['type_overrides'],
            status_callback=task.report_status,
            progress_callback=lambda done, total: task.report_progress(
                min(1000, int(done * 1000 // max(1, total))), 1000))
    task = BackgroundTask(work, window)
    task.status.connect(progress.setLabelText)
    def completed(results):
        progress.close()
        lines = []
        for item in results:
            name = {'client': '客户端', 'server': '服务端', 'docs': '附加资料'}.get(item['component'], item['component'])
            lines.append(('✅ ' + name + '：' + str(item.get('result'))) if item['ok']
                         else ('❌ ' + name + '：' + item['error']))
        try:
            window.refresh_instances()
            window.home_panel.server_center.refresh()
        except Exception:
            pass
        QMessageBox.information(window, '智能导入结果', '\n\n'.join(lines) or '没有执行任何组件。')
    task.succeeded.connect(completed)
    task.failed.connect(lambda error: (progress.close(), QMessageBox.warning(window, '智能导入失败', error)))
    window._smart_import_task = task
    task.start()


def start_smart_import(window, path=None):
    if getattr(window, '_smart_import_task', None) and window._smart_import_task.is_running:
        QMessageBox.information(window, '智能导入', '已有导入任务正在执行，请稍等。')
        return
    path = path or _choose_source(window)
    if not path:
        return
    progress = QProgressDialog('正在严格扫描来源…', '', 0, 1000, window)
    progress.setWindowTitle('智能导入')
    progress.setCancelButton(None)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.show()
    task = BackgroundTask(
        lambda current: scan_import_source(
            path, status_callback=current.report_status,
            progress_callback=lambda done, total: current.report_progress(
                min(1000, int(done * 1000 // max(1, total))), 1000)), window)
    task.status.connect(progress.setLabelText)
    task.progress.connect(lambda value, total: (
        progress.setRange(0, total), progress.setValue(value)))
    def scanned(report):
        progress.close()
        dialog = SmartImportPreview(report, lambda value: _ai_summary(window, value), window)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            _execute(window, report, dialog.selection())
    task.succeeded.connect(scanned)
    task.failed.connect(lambda error: (progress.close(), QMessageBox.warning(window, '智能导入扫描失败', error)))
    window._smart_import_task = task
    task.start()
