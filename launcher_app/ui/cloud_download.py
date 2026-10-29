"""User-operated share → archive → inspection handoff, no automatic import."""
from launcher_app.core.i18n import t
import json
import re
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QProgressBar, QFileDialog)

from launcher_app.core.background_tasks import BackgroundTask
from launcher_app.resources import cloud_drives as drive
from launcher_app.ui.settings_section import SettingsSection


def extract_url(text):
    match = re.search(r'https?://[^\s<>"，。]+', text)
    if not match:
        raise drive.CloudDriveError('请粘贴网盘分享链接，可以包含分享文案。')
    url = match[0]
    drive.parse_share(url)
    return url


class CloudDownloadDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.host = window
        self.session_id = ''
        self.provider = ''
        self.location = ('0', t('分享根目录'))
        self.history = []
        self.page = 1
        self.has_more = False
        self.original = None
        self.result = None
        self.task = None
        self.source_url = ''
        self.listing_valid = False
        self.setWindowTitle(t('从网盘获取整合包'))
        self.resize(860, 700)
        layout = QVBoxLayout(self)
        source = SettingsSection(t('分享链接'))
        self.url = QLineEdit()
        self.url.setPlaceholderText(t('粘贴夸克、百度或 123 分享链接，无需先登录'))
        self.passcode = QLineEdit()
        self.passcode.setPlaceholderText(t('提取码（链接中已有可留空）'))
        self.passcode.setMaximumWidth(230)
        self.load = QPushButton(t('读取分享目录'))
        self.load.clicked.connect(self.open_share)
        source.content.addWidget(self.url)
        row = QHBoxLayout()
        row.addWidget(self.passcode)
        row.addWidget(self.load)
        row.addStretch()
        source.content.addLayout(row)
        layout.addWidget(source)
        navigation = QHBoxLayout()
        self.back = QPushButton(t('上一级'))
        self.back.clicked.connect(self.go_back)
        self.previous = QPushButton(t('上一页'))
        self.previous.clicked.connect(lambda: self.load_page(self.page - 1))
        self.next = QPushButton(t('下一页'))
        self.next.clicked.connect(lambda: self.load_page(self.page + 1))
        self.breadcrumb = QLabel(t('先读取分享；登录和下载是后续步骤。'))
        self.breadcrumb.setTextFormat(Qt.TextFormat.PlainText)
        self.breadcrumb.setWordWrap(True)
        navigation.addWidget(self.back)
        navigation.addWidget(self.breadcrumb, 1)
        navigation.addWidget(self.previous)
        navigation.addWidget(self.next)
        layout.addLayout(navigation)
        self.files = QTreeWidget()
        self.files.setHeaderLabels([t('文件或目录'), t('大小'), t('提示')])
        self.files.setRootIsDecorated(False)
        self.files.setColumnWidth(0, 440)
        self.files.setColumnWidth(1, 100)
        self.files.itemDoubleClicked.connect(self.enter)
        self.files.itemSelectionChanged.connect(self.update_controls)
        layout.addWidget(self.files, 1)
        self.status = QLabel(t('先找出客户端、服务端候选再选择；文件名和日期只是线索，不保证“最新版”。'))
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.saved_label = QLabel(t('已保存原包：暂无'))
        self.saved_label.setWordWrap(True)
        self.saved_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.saved_label)
        actions = QHBoxLayout()
        self.browser = QPushButton(t('打开分享网页 / 登录'))
        self.browser.clicked.connect(self.open_browser)
        self.connect = QPushButton(t('连接登录凭证…'))
        self.connect.clicked.connect(self.login)
        self.download = QPushButton(t('下载所选原包'))
        self.download.clicked.connect(self.download_selected)
        self.cancel_task = QPushButton(t('取消当前请求'))
        self.cancel_task.clicked.connect(lambda: self.task.cancel() if self.task else None)
        for control in (self.browser, self.connect, self.download, self.cancel_task):
            actions.addWidget(control)
        layout.addLayout(actions)
        handoff = QHBoxLayout()
        self.choose = QPushButton(t('已在浏览器下载，选择本地原包…'))
        self.choose.clicked.connect(self.choose_local)
        self.folder = QPushButton(t('打开原包位置 / 用火绒等杀软检查'))
        self.folder.clicked.connect(self.open_original_folder)
        self.install = QPushButton(t('导入已保存原包…'))
        self.install.clicked.connect(self.import_original)
        for control in (self.choose, self.folder, self.install):
            handoff.addWidget(control)
        layout.addLayout(handoff)
        self.update_controls()

    def busy(self):
        return bool(self.task and self.task.is_running)

    def selected(self):
        item = self.files.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def update_controls(self):
        busy = self.busy()
        self.files.setEnabled(not busy and self.listing_valid)
        for control in (self.load, self.url, self.passcode, self.choose):
            control.setEnabled(not busy)
        self.back.setEnabled(not busy and self.listing_valid and bool(self.history))
        self.previous.setEnabled(not busy and self.listing_valid and bool(self.session_id) and self.page > 1)
        self.next.setEnabled(not busy and self.listing_valid and self.has_more)
        self.browser.setEnabled(not busy and bool(self.source_url))
        self.connect.setEnabled(not busy and bool(self.provider))
        entry = self.selected() or {}
        self.download.setEnabled(not busy and self.listing_valid and bool(entry.get('archive')))
        self.cancel_task.setEnabled(busy)
        self.folder.setEnabled(not busy and bool(self.original))
        # Import is an explicit handoff into the existing scan/preview UI.
        review = (self.result or {}).get('review') or {}
        antivirus = review.get('antivirus') or {}
        self.install.setEnabled(not busy and bool(self.original) and
            (self.result or {}).get('status') == 'downloaded' and
            review.get('kind') in ('modpack-candidate', 'server-candidate') and
            antivirus.get('status') != 'attention_required')

    def run(self, work, done):
        if self.busy():
            return
        self.progress.setRange(0, 0)
        self.task = BackgroundTask(lambda current: json.loads(drive.tool_result(lambda: work(current))), self)
        def deliver(result):
            if result.get('status') in ('needs_user', 'login_required', 'captcha_required'):
                self.status.setText(result.get('message', '请处理登录或验证后重试；原选择保留。'))
                return
            done(result)
        self.task.succeeded.connect(deliver)
        self.task.failed.connect(lambda _: self.status.setText(t('请求未完成，请检查网络或登录状态。原选择保留。')))
        self.task.cancelled_signal.connect(lambda: self.status.setText(t('已取消当前请求。已完成原包保留，可继续浏览或重试。')))
        self.task.progress.connect(self.on_progress)
        self.task.status.connect(self.status.setText)
        def finish():
            self.progress.setRange(0, 100)
            self.update_controls()
        self.task.finished.connect(finish)
        self.task.start()
        self.update_controls()

    def open_share(self):
        try:
            url = extract_url(self.url.text().strip())
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.status.setText(t('正在读取分享目录；无需先登录，原列表会保留到新结果返回。'))
        password = self.passcode.text().strip()
        self.source_url = url
        self.provider = drive.parse_share(url)[0]
        self.listing_valid = False
        self.session_id = ''
        def done(result):
            self.source_url = url
            self.provider = result['provider']
            self.session_id = result['session_id']
            self.history = []
            self.location = ('0', t('分享根目录'))
            self.apply_page(result)
        self.run(lambda current: drive.browse(url, password), done)

    def apply_page(self, result):
        self.listing_valid = True
        self.page = result['page']
        self.has_more = result['has_more']
        self.files.clear()
        for entry in result['items']:
            name = entry['name']
            hint = '双击进入' if entry['directory'] else '可下载原包' if entry['archive'] else '仅查看，不执行'
            item = QTreeWidgetItem([name, '目录' if entry['directory'] else f"{entry['size'] / 1024**2:.1f} MB", hint])
            item.setData(0, Qt.ItemDataRole.UserRole, entry)
            self.files.addTopLevelItem(item)
        self.breadcrumb.setText(t('{v0} · 第 {v1} 页').format(v0=(self.location[1]), v1=(self.page)))
        self.status.setText(t('目录已读取。双击进入文件夹，选中 ZIP/MRPACK 后点击下载；需要登录会保留原选择。'))
        self.update_controls()

    def load_page(self, page, location=None, history=None):
        if not self.session_id or self.busy():
            return
        target = location or self.location
        def done(result):
            if history is not None:
                self.history = history
            self.location = target
            self.apply_page(result)
        self.status.setText(t('正在读取目录，原列表暂供参考…'))
        self.run(lambda current: drive.browse(session_id=self.session_id, folder_id=target[0], page=page), done)

    def enter(self, item, column=0):
        entry = item.data(0, Qt.ItemDataRole.UserRole)
        if entry and entry['directory']:
            self.load_page(1, (entry['id'], entry['name']), [*self.history, self.location])

    def go_back(self):
        if self.history:
            self.load_page(1, self.history[-1], self.history[:-1])

    def login(self):
        from launcher_app.ui.cloud_drive_settings import credentials_dialog
        credentials_dialog(self, self.provider)
        self.status.setText(t('若已连接凭证，请再次点击“下载所选原包”。网页登录本身不会自动授权启动器；也可在网页下载后选择本地原包。'))

    def open_browser(self):
        # Original user-provided share, never an API-issued signed download URL.
        if self.source_url:
            QDesktopServices.openUrl(QUrl(self.source_url))

    def download_selected(self):
        if self.busy() or not self.listing_valid:
            return
        entry = self.selected()
        if not entry or not entry.get('archive'):
            return
        import paths
        game_dir = paths.GAME_DIR
        self.status.setText(t('正在获取「{v0}」的下载权限…').format(v0=(entry['name'])))
        self.run(lambda current: drive.receive(self.session_id, entry['id'], game_dir,
                                               current.report_progress, current.report_status), self.show_received)

    def show_received(self, result):
        self.result = result
        self.original = result.get('path')
        self.saved_label.setText(t('已保存原包：') + (self.original or t('当前文件不可访问')))
        review = result.get('review') or {}
        parts = [result.get('notice', '原包已接收。')]
        parts.extend(review.get('warnings') or [])
        if review.get('antivirus'):
            parts.append(review['antivirus'].get('message', ''))
        if self.original:
            parts.append('原包位置：' + self.original)
        self.status.setText('\n'.join(parts))
        self.progress.setValue(100)
        self.update_controls()

        from launcher_app.ui.optional_notices import antivirus_notice
        antivirus_notice(self, review.get('antivirus'))

    def on_progress(self, done, total):
        if total:
            self.progress.setRange(0, 100)
            self.progress.setValue(min(100, int(done * 100 / total)))

    def choose_local(self):
        path, _ = QFileDialog.getOpenFileName(self, t('选择已下载的原始整合包（文件保留原位置）'), '', t('整合包 (*.zip *.mrpack)'))
        if path:
            self.status.setText(t('正在检查所选原包；不会移动、删除或执行文件…'))
            self.run(lambda current: drive.review_local_archive(path, current.report_status), self.show_received)

    def open_original_folder(self):
        if self.original:
            from os_platform.openpath import open_path
            open_path(str(Path(self.original).parent))

    def import_original(self):
        if self.original and self.install.isEnabled():
            from launcher_app.ui.smart_import_ui import start_smart_import
            start_smart_import(self.host, self.original)

    def closeEvent(self, event):
        if self.busy():
            self.task.cancel()
        super().closeEvent(event)

    def reject(self):
        if self.busy():
            self.task.cancel()
        super().reject()


def start_cloud_download(window):
    dialog = getattr(window, '_cloud_download_dialog', None)
    if dialog is None:
        dialog = CloudDownloadDialog(window)
        window._cloud_download_dialog = dialog
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


def choose_classic_archive(window):
    """Local menu choice opens the local picker without another source prompt."""
    return QFileDialog.getOpenFileName(window, t('选择整合包'), '', t('整合包 (*.mrpack *.zip)'))[0]
