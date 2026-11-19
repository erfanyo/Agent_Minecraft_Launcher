"""Create or change the pinned build for an experimental Horizon instance."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from launcher_app.core.background_tasks import BackgroundTask
from launcher_app.core.i18n import t
from launcher_app.instances.horizon import HORIZON_LAUNCHER_URL, HorizonLauncher
import paths
from settings import load_settings, update_setting


class HorizonPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.target = None
        self._catalog_key = None
        self._catalog_task = None

        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        note = QLabel(t('Horizon 是社区制作的 Rust 版 Minecraft。需要 Java 版正版账号，首次游玩前请在 Horizon Launcher 内登录。'))
        note.setWordWrap(True)
        self.launcher_label = QLabel()
        self.launcher_label.setTextFormat(Qt.TextFormat.PlainText)
        self.launcher_label.setWordWrap(True)

        download = QPushButton(t('获取 Horizon Launcher'))
        download.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(HORIZON_LAUNCHER_URL)))
        select = QPushButton(t('选择已解压的启动器'))
        select.clicked.connect(self._choose_launcher)
        self.login = QPushButton(t('打开 Horizon 登录'))
        self.login.clicked.connect(self._open_login)
        launcher_actions = QHBoxLayout()
        for button in (download, select, self.login):
            launcher_actions.addWidget(button)
        launcher_actions.addStretch()

        self.versions = QComboBox()
        self.reload = QPushButton(t('刷新版本'))
        self.reload.clicked.connect(self.refresh)
        version_row = QHBoxLayout()
        version_row.addWidget(QLabel(t('Horizon 构建')))
        version_row.addWidget(self.versions, 1)
        version_row.addWidget(self.reload)
        self.hint = QLabel()
        self.hint.setTextFormat(Qt.TextFormat.PlainText)
        self.hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(note)
        layout.addWidget(self.launcher_label)
        layout.addLayout(launcher_actions)
        layout.addLayout(version_row)
        layout.addWidget(self.hint)
        layout.addStretch()

    def show_for(self, instance=None):
        self.target = instance
        self.title.setText(t('创建 Horizon 实例') if instance is None else t('更换「{name}」的 Horizon 构建').format(
            name=instance.get('name') or instance['id']))
        root, program = self._configuration()
        if self._catalog_key != (root, program):
            self.refresh()
        elif instance:
            self._select_current_build()

    @staticmethod
    def _configuration():
        return paths.GAME_DIR, load_settings().get('horizon_launcher_path') or ''

    def selection(self):
        root, program = self._configuration()
        version = self.versions.currentData() if self._catalog_key == (root, program) else None
        return {'version': version,
                'instance_id': self.target['id'] if self.target else None,
                'horizon_launcher_path': program}

    def _choose_launcher(self):
        _, program = self._configuration()
        selected, _ = QFileDialog.getOpenFileName(self, t('选择 Horizon Launcher'), program)
        if selected:
            try:
                update_setting('horizon_launcher_path', selected)
            except OSError as exc:
                self.hint.setText(str(exc))
                return
            self.refresh()

    def _open_login(self):
        try:
            HorizonLauncher(*self._configuration()).open_account_ui()
        except (OSError, ValueError) as exc:
            self.hint.setText(str(exc))

    def refresh(self):
        root, program = self._configuration()
        self._catalog_key = (root, program)
        if self._catalog_task is not None:
            self._catalog_task.cancel()
            self._catalog_task = None
        self.launcher_label.setText(program or t('首次设置时请选择上游 Horizon Launcher 的可执行文件。'))
        self.versions.clear()
        self.versions.setEnabled(False)
        self.login.setEnabled(bool(program))
        self.reload.setEnabled(bool(program))
        if not program:
            self.hint.clear()
            return

        self.hint.setText(t('正在获取发行版本…'))
        task = BackgroundTask(lambda _task: HorizonLauncher(root, program).versions(), self)
        self._catalog_task = task

        def loaded(result):
            if task is not self._catalog_task:
                return
            rows, error = result
            for tag, installed in rows:
                self.versions.addItem(t('{tag}（已安装）').format(tag=tag) if installed else tag, tag)
            self.versions.setEnabled(bool(rows))
            self._select_current_build()
            self.hint.setText(error or ('' if rows else t('当前平台没有可用的 Horizon 构建。')))

        def failed(error):
            if task is self._catalog_task:
                self.hint.setText(error)

        def finished():
            if task is self._catalog_task:
                self._catalog_task = None
            task.deleteLater()

        task.succeeded.connect(loaded)
        task.failed.connect(failed)
        task.finished.connect(finished)
        task.start()

    def _select_current_build(self):
        if self.target:
            self.versions.setCurrentIndex(self.versions.findData(self.target.get('base')))
