# -*- coding: utf-8 -*-
"""
Agent Minecraft Launcher — 阶段 1 · 启动核心
功能:
- 版本分类树(大版本 → 正式版 / 折叠的预览版;远古版本单独折叠)
- 选中版本 → 显示详细信息(jar 大小、所需 Java 等)
- 安装所选版本:客户端 jar + 依赖库 + 资源文件(镜像加速 + sha1 校验)
- 启动游戏:自动准备 Java → 拼启动命令 → 拉起进程 → 实时显示游戏日志
"""
from launcher_app.ui.ui_notifications import task_notice, task_warning, inline_notice, inline_warning, action_question
from launcher_app.ui.task_center import task_question, task_choice
import base64
import json
import os
import shutil
import sys
import tempfile
if __name__ == '__main__' and '--amcl-java-probe' in sys.argv:
    _probe_index = sys.argv.index('--amcl-java-probe')
    _probe_java = sys.argv[_probe_index + 1]
    _probe_output = sys.argv[_probe_index + 2]
    from launcher_app.runtime.java_manager import java_version_probe
    _probe_major, _probe_error = java_version_probe(_probe_java)
    with open(_probe_output, 'w', encoding='utf-8') as _probe_file:
        json.dump({'major': _probe_major, 'error': _probe_error}, _probe_file, ensure_ascii=False)
    raise SystemExit(0 if _probe_major else 1)
_CI_STARTUP_SMOKE = __name__ == '__main__' and '--amcl-ci-smoke' in sys.argv
if _CI_STARTUP_SMOKE:
    sys.argv.remove('--amcl-ci-smoke')
    # Windows 单文件包只携带实际使用的 qwindows 平台插件；源码 CI 才用 offscreen。
    if not (getattr(sys, 'frozen', False) and sys.platform == 'win32'):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('AML_DATA_DIR', os.path.join(tempfile.gettempdir(), 'amcl-ci-smoke'))
# Wayland does not expose top-level window coordinates needed to align the
# floating AI wallpaper with the main window. Prefer XWayland when DISPLAY is
# available, with native Wayland as fallback; respect an explicit user choice.
# WSLg also needs software rendering for its translucent Qt window.
# This must run before importing PySide6.
if __name__ == '__main__' and not _CI_STARTUP_SMOKE:
    if sys.platform.startswith('linux') and os.environ.get('DISPLAY'):
        os.environ.setdefault('QT_QPA_PLATFORM', 'xcb;wayland')
    try:
        from os_platform.system import is_wsl
        if is_wsl():
            os.environ.setdefault('QT_OPENGL', 'software')
            os.environ.setdefault('LIBGL_ALWAYS_SOFTWARE', '1')
    except Exception:
        pass
if __name__ == '__main__' and '--amcl-memory-relief' in sys.argv:
    from launcher_app.runtime.memory_relief import main as memory_relief_main
    raise SystemExit(memory_relief_main(sys.argv[sys.argv.index('--amcl-memory-relief') + 1]))
# Dispatch before importing Qt or constructing the launcher in the helper process.
if __name__ == '__main__' and '--amcl-plugin-web-window' in sys.argv:
    from launcher_app.extensions.plugin_web_worker import main as web_window_main
    raise SystemExit(web_window_main())
if __name__ == '__main__' and '--amcl-server-host' in sys.argv:
    from launcher_app.servers.server_host import main as server_host_main
    _server_host_index = sys.argv.index('--amcl-server-host')
    raise SystemExit(server_host_main(sys.argv[_server_host_index + 1:]))
import time
from datetime import datetime

import requests
from launcher_app.core.log_privacy import redact_text
from launcher_app.resources.downloader import failure_advice

from PySide6.QtCore import Qt, QSize, QTimer, QFileSystemWatcher, QEvent, QRectF, QPoint, QLockFile
from PySide6.QtGui import (QColor, QCursor, QGuiApplication, QFont, QIcon, QImageReader, QPainter,
                           QPainterPath, QPalette, QPixmap, QRegion)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QMenu,
    QScrollArea,
    QSplashScreen,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QDockWidget,
)

import launcher_app.core.updater as updater  # 自动更新(检查 GitHub 新版本 / 下载 / 替换)
from launcher_app.core.bridge_mod_dist import BRIDGE_MOD_VERSION  # bridge-mod 当前版本
from launcher_app.core.task_controllers import DownloadTaskController, VersionManifestController
from launcher_app.core.background_tasks import BackgroundTask
from launcher_app.ai.assistant import AIChatDock, AI_DOCK_RETURN_MIME, permission_instructions  # AI 助手(右侧停靠对话栏)
from launcher_app.ai.ai_actions import plain_language_instructions
from launcher_app.ui.download_indicator import DownloadDetailWidget, DownloadIndicator  # 左下角下载指示器
from launcher_app.ui.updater_dialog import UpdateDialog  # 检查更新对话框(独立模块)
from launcher_app.resources.download_tab import DownloadTab  # 下载新实例选项卡(左侧菜单 + 分类面板)
from launcher_app.resources.fetch_versions import fetch_version_detail, fetch_version_manifest  # 网络模块
import launcher_app.core.i18n as i18n  # 界面语言(跟随系统,可设置覆盖)
from launcher_app.core.i18n import t
from launcher_app.instances.instance_install_service import InstanceInstallService
from launcher_app.instances.game_launch_service import GameLaunchService, LoginRequiredError
from launcher_app.runtime.game_session_controller import GameSessionController
from launcher_app.instances.crash_diagnostics import GameRunEvidence
from launcher_app.instances.instance_catalog_service import InstanceCatalogService
from launcher_app.resources.modpack import import_modpack as import_modpack_file  # 整合包导入
from launcher_app.resources.modrinth import download_mod  # Modrinth 搜索与下载(含中文名支持)
import paths  # 游戏目录(可配置,设置/引导里可改)
from paths import GAME_DIR, RUNTIME_DIR  # 兼容旧引用(测试用);内部统一用 paths.GAME_DIR
from os_platform.openpath import open_path  # 跨平台打开文件/文件夹(替代 os.startfile)
from settings import load_settings, save_settings  # 启动器配置
from launcher_app.extensions.skill_manager import SkillManager, SkillManagerDialog  # 技能(运行时辅助)系统
from launcher_app.ui.version_tree import fill_version_tree  # 版本树构建(与下载选项卡共用)


def application_icon() -> QIcon:
    """统一窗口/任务栏图标；源码和 PyInstaller 单文件版都从 icons/ 读取。"""
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return QIcon(os.path.join(root, "icons", "grass_block.png"))


def startup_splash() -> QSplashScreen:
    """轻量启动屏：主窗口构建期间给出确定的视觉反馈，不引入额外 UI 框架。"""
    palette = QApplication.palette()
    background = palette.color(QPalette.ColorRole.Window)
    text = palette.color(QPalette.ColorRole.WindowText)
    muted = palette.color(QPalette.ColorRole.PlaceholderText)
    if not muted.isValid():
        muted = palette.color(QPalette.ColorRole.Text)
    pixmap = QPixmap(540, 300)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(background)
    painter.drawRoundedRect(1, 1, 538, 298, 20, 20)
    icon = application_icon().pixmap(QSize(58, 58))
    painter.drawPixmap(44, 58, icon)
    painter.setPen(text)
    title_font = QFont()
    title_font.setPointSize(20)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.drawText(122, 88, "AMCL")
    painter.setPen(muted)
    sub_font = QFont()
    sub_font.setPointSize(10)
    painter.setFont(sub_font)
    painter.drawText(122, 116, "正在准备你的游戏与工具…")
    painter.end()
    splash = QSplashScreen(
        pixmap,
        Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
    )
    splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    return splash


def startup_message_color() -> QColor:
    """Keep splash progress text readable in the current system theme."""
    color = QApplication.palette().color(QPalette.ColorRole.PlaceholderText)
    return color if color.isValid() else QApplication.palette().color(QPalette.ColorRole.Text)





class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Agent Minecraft Launcher")
        self.setMinimumSize(700, 560)
        self.selected_version = None  # 记住当前选中的版本,供"下载"按钮使用
        self.settings = load_settings()  # 启动器配置(用户名/内存/版本隔离)
        self.instance_installer = InstanceInstallService(
            lambda: paths.GAME_DIR,
            lambda: bool(self.settings.get("version_isolation")),
        )
        self.game_launcher = GameLaunchService(
            lambda: paths.GAME_DIR,
            lambda: paths.RUNTIME_DIR,
            lambda: self.settings,
            save_settings,
            self.instance_installer.game_dir_for,
        )
        self.instance_catalog = InstanceCatalogService(
            lambda: paths.GAME_DIR,
            self.instance_installer.game_dir_for,
        )
        # 预留:自定义配色主题(以后 UI 可能出自定义配色方案)。从设置读 ui_custom_colors 应用。
        from launcher_app.ui.ui_style import load_theme_from_settings
        load_theme_from_settings(self.settings)
        from launcher_app.ui.ui_anim import set_animations_enabled
        set_animations_enabled(self.settings.get("ui_animations_enabled", True))
        i18n.set_language(self.settings.get("language", "auto"))  # 界面语言(跟随系统/设置)

        # ---- 语言包(第三方/玩梗语言):加载 内置语言包 + AMCL/languages/*.json + 插件注册的包 ----
        # 语言包 = 用 {"原文": "替换文本"} 覆盖启动器所有文本;可选,切换后重启生效。
        try:
            import launcher_app.core.i18n as _i18n
            import os as _os
            _n = 0
            # ① 内置产品数据语言包(仓库根 languages/,如机翻生成的 en/fr/es...json)
            _bundle_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "languages")
            _n += _i18n.load_packs_from_dir(_bundle_dir)
            # ② 用户第三方语言包(AMCL/languages/)
            _user_dir = paths.data_dir("languages")
            _n += _i18n.load_packs_from_dir(_user_dir)
            _lang = self.settings.get("language", "auto")
            # Resolve auto again after packs load, so English systems also use
            # the bundled English overlay rather than only the legacy table.
            _i18n.set_language(_lang)
            QApplication.instance().setLayoutDirection(
                Qt.LayoutDirection.RightToLeft if _i18n.is_rtl() else Qt.LayoutDirection.LeftToRight)
            print(f"[语言包] 内置+用户共加载 {_n} 个(内置:{_bundle_dir}, 用户:{_user_dir});当前语言 {_i18n.get_language()}")
        except Exception as e:
            print(f"[语言包] 加载异常:{type(e).__name__}: {e}")

        # ---- 插件系统:启动时静态装载插件(plugins/*.py),登记工具/页面/设置/技能 ----
        # 被禁用的插件(settings["plugins_disabled"])跳过;默认关闭的插件需显式启用。
        # 提前到这里装载(先于 设置中心/技能管理器 创建),让插件登记内容立即可见。
        try:
            import launcher_app.extensions.plugin_manager as plugin_manager
            _loaded = plugin_manager.load_all(self.settings, include_builtin=True)
            from launcher_app.features.registry import FEATURE_IDS
            print(f"[本体] 注册 {len(FEATURE_IDS)} 项功能")
            print(f"[插件] 装载 {len([k for k, v in _loaded.items() if v])} 个插件")
        except Exception as e:
            print(f"[插件] 装载异常:{type(e).__name__}: {e}")

        # ---- 无边框自定义标题栏(名称位置按平台,见 frameless_titlebar.py) ----
        self.setWindowTitle("AMCL")   # 任务栏/系统标题
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        if sys.platform.startswith(('linux', 'win')):
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        from launcher_app.ui.frameless_titlebar import FramelessTitleBar
        self._running_instances = set()
        self._running_label = QLabel("")     # 放在标题栏(悬停看具体实例)
        self._running_label.setMaximumWidth(160)
        self._server_running_label = QLabel(t('尚未启动服务端'))
        self._server_running_label.setMaximumWidth(160)
        self._server_running_label.setToolTip(t('显示由 AMCL 托管的运行中服务端'))
        self._server_running_task = None
        running_status = QWidget()
        running_status_layout = QHBoxLayout(running_status)
        running_status_layout.setContentsMargins(0, 0, 0, 0)
        running_status_layout.setSpacing(14)
        running_status_layout.addWidget(self._running_label)
        running_status_layout.addWidget(self._server_running_label)
        self.title_bar = FramelessTitleBar(self, "AMCL",
                                           trailing_widget=running_status)
        self._ai_focus_mode = False
        self._ai_transition = None
        self.ai_mode_button = QPushButton(t('AI 模式'))
        self.ai_mode_button.setToolTip(t('进入全屏对话工作台'))
        self.online_button = QPushButton(t('联机'))
        self.online_button.setToolTip(t('联机方案中心'))
        self.settings_button = QPushButton(t('设置'))
        self.settings_button.setToolTip(t('启动器设置'))
        self.title_nav = QWidget(self.title_bar)
        nav_layout = QHBoxLayout(self.title_nav)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(8)
        for button in (self.ai_mode_button, self.online_button, self.settings_button):
            button.setProperty('titleNav', True)
            button.setFixedSize(110, 28)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            nav_layout.addWidget(button)
        self.title_bar.set_center_widget(self.title_nav)
        self.ai_mode_button.clicked.connect(self._on_mode_button_clicked)
        self.settings_button.clicked.connect(lambda: self.open_settings())
        self.online_button.clicked.connect(self._toggle_online_center)
        self.title_bar.refresh_theme()
        # 边缘缩放手柄(Linux 无边框窗口专用;Windows 走 WM_NCHITTEST,手柄不影响)
        self._setup_resize_handles()
        # 菜单栏已取消(2026-08-25):「文件/查看/设置/AI/联机/帮助」全部移除。
        # - 导入整合包 → 下载新资源 → 实例 →「导入整合包」按钮
        # - 检查更新 / 引导教程(重播) → 放到 设置 → 系统
        # - 打开游戏目录 / 清空实例 / 刷新版本列表 意义不大,不再放外层入口
        # 相关方法(load_versions/import_modpack/open_game_dir/clear_instances/open_update_dialog)仍保留可调用。

        # ---- Tab「我的实例」:仿 PCL2 首页(左 1/3 登录+当前选择+启动按钮,右 2/3 实例/更新日志/动态) ----
        from launcher_app.ui.version_home import VersionHome
        tab_a = VersionHome()
        self.home_panel = tab_a                     # 保留引用,便于刷新登录显示等
        self.instance_list = tab_a.instance_list    # 版本列表(兼容旧引用:右键/视图/双击)
        self.launch_btn = tab_a.launch_btn          # 启动游戏大按钮
        # 双击仍直接启动；左侧主按钮由 VersionHome 按客户端/服务端模式分派。
        self.instance_list.itemDoubleClicked.connect(
            lambda item: self.launch_selected_instance(item.data(Qt.ItemDataRole.UserRole)))
        # 键盘导航(遥控器式):实例列表按回车 → 启动选中实例(itemActivated)
        tab_a.launch_requested.connect(self.launch_selected_instance)
        tab_a.refresh_requested.connect(self.refresh_instances)
        # 新首页抛出的信号 → 启动器处理
        tab_a.open_instance_manager_requested.connect(self._home_open_instance_manager)
        tab_a.open_settings_requested.connect(self.open_settings)
        tab_a.login_changed.connect(self._on_login_changed)
        tab_a.one_click_config_requested.connect(self._one_click_config_kind)
        tab_a.import_modpack_requested.connect(self.import_modpack)
        from launcher_app.ui.browser_downloads import start_cloud_browser_import
        tab_a.import_cloud_requested.connect(lambda: start_cloud_browser_import(self))
        tab_a.open_resources_requested.connect(self._open_resource_page)
        tab_a.tutorial_requested.connect(self.open_tutorial)
        # 左侧「实例详情」大按钮:客户端实例 → 实例详情页;服务端 → 服务端详情页
        tab_a.instance_details_requested.connect(self._open_details_for_current)
        tab_a.smart_import_requested.connect(self._smart_import_path)

        # ---- 「下载新资源」综合入口:左侧菜单 + 首页/实例/Mod/光影/数据包/资源包 ----
        from launcher_app.ui.resource_center import ResourceCenter
        # 版本清单由 MainWindow.load_versions 统一加载，避免下载页构造时重复请求。
        self.resource_center = ResourceCenter(auto_load_versions=False)
        self.resource_center.set_ui_mode(self.settings.get("ui_mode", "beginner"))
        # 兼容旧引用:download_tab 是资源中心内的实例向导
        self.download_tab = self.resource_center.download_tab
        self.resource_center.set_hooks(
            instance_dir=self.game_dir_for,
            on_download=self._resource_download,
            on_start_instance=self.start_instance_download,
            on_import_modpack=self.import_modpack,
            on_modpack_download=self._resource_download_modpack)


        # 右键菜单:实例(启动/打开目录/删除)
        self.instance_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.instance_list.customContextMenuRequested.connect(self._instance_menu)
        from launcher_app.resources.folder_instance_import import start_import
        self.instance_list.folders_dropped.connect(lambda folders: start_import(self, folders))

        # ---- 主选项卡(我的实例 / 共用详情 / 下载新资源) ----
        self.main_tabs = QTabWidget()
        from launcher_app.ui.ui_style import tab_style, card_btn_style, set_style
        set_style(self.main_tabs, tab_style)   # 外层标签页:圆角+字体放大(14px)
        self.main_tabs.addTab(tab_a, t("MY_INSTANCES"))
        self._my_inst_tab_idx = 0   # 「我的实例」= 主标签第 0 页(拖入文件 → 当作整合包安装)
        # 客户端与服务端详情共用一个顶层标签页。
        from launcher_app.ui.instance_manager import InstanceManagerDialog
        self.instance_details = InstanceManagerDialog()
        self.instance_details.setObjectName("instance_details")
        tab_a.instance_selected.connect(self._on_instance_selected)
        from launcher_app.servers.server_details import ServerDetailsView
        self.server_details = ServerDetailsView()
        self.server_details.setObjectName("server_details")
        tab_a.server_center.selection_changed.connect(self._on_server_selected)
        tab_a.server_center.running_changed.connect(lambda _running: self._scan_running_servers())
        self.details_stack = QStackedWidget()
        self.details_placeholder = QLabel(t('请先在“我的实例”中选择一个实例或服务端。'))
        self.details_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details_stack.addWidget(self.details_placeholder)
        self.details_stack.addWidget(self.instance_details)
        self.details_stack.addWidget(self.server_details)
        self._details_tab_idx = self.main_tabs.addTab(self.details_stack, t("INSTANCE_DETAILS"))
        self.main_tabs.addTab(self.resource_center, t("RESOURCES"))
        # 联机使用非模态独立窗口，不参与主窗口 Dock 布局。
        from launcher_app.ui.online_center import OnlineCenter
        from PySide6.QtWidgets import QDialog
        self.online_dock = QDialog(self, Qt.WindowType.Window)
        self.online_dock.setWindowTitle(t('联机 · AMCL'))
        self.online_dock.setModal(False)
        self.online_dock.resize(960, 720)
        self.online_dock.setMinimumSize(560, 400)
        self.online_dock.setSizeGripEnabled(True)
        from launcher_app.ui.ui_style import current_color
        set_style(self.online_dock, lambda: (
            f'QDialog {{ background: {current_color("bg1")}; }}'))
        online_window_layout = QVBoxLayout(self.online_dock)
        online_window_layout.setContentsMargins(0, 0, 0, 0)
        from launcher_app.ui.ui_background import BackgroundWidget
        self.online_surface = BackgroundWidget(self.online_dock)
        self.online_surface.setMinimumWidth(0)
        online_body = QVBoxLayout(self.online_surface)
        online_body.setContentsMargins(0, 0, 0, 0)
        self.online_center = OnlineCenter(self.online_surface)
        self.online_center.setMinimumWidth(0)
        self.online_center.setObjectName("online_center")
        online_body.addWidget(self.online_center)
        online_window_layout.addWidget(self.online_surface)
        # 设置页嵌入主窗口，由两种模式共用。
        from settings.center import SettingsCenter
        self.settings_center = SettingsCenter(self.settings)
        self.settings_center.applied.connect(self._on_settings_applied)
        self.settings_center.visual_changed.connect(self._on_visual_settings_changed)
        self.settings_center.runtime_changed.connect(self._on_runtime_settings_changed)

        # ---- 插件注册的主标签页(与下载新资源平级) ----
        try:
            import launcher_app.extensions.plugin_manager as plugin_manager
            for _label, _build in plugin_manager.MAIN_TABS:
                try:
                    self.main_tabs.addTab(_build(), _label)
                except Exception:
                    pass
        except Exception:
            pass
        self.main_tabs.currentChanged.connect(self._on_main_tab_changed)

        # ---- 启动器日志:已作为「我的实例 → 启动器日志」子标签页(与 MC 动态同级) ----
        self.log_view = tab_a.log_view   # 复用首页子标签页里的常驻日志 view(流持续追加)
        # 启动器尽可能把所有反馈(状态/异常/操作)记进日志,方便 AI 定位问题
        self._log_feedback_setup()

        # ---- 组装整个窗口(背景引擎:BackgroundWidget 垫底画壁纸+遮罩)----
        from launcher_app.ui.ui_background import BackgroundWidget
        central = BackgroundWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.main_tabs)
        from launcher_app.ai.ai_focus_mode import AIFocusSidebar
        self.ai_focus_sidebar = AIFocusSidebar(self)
        self.ai_focus_sidebar.installEventFilter(self)
        self.settings_page = BackgroundWidget()
        settings_layout = QVBoxLayout(self.settings_page)
        settings_layout.setContentsMargins(12, 12, 12, 12)
        settings_layout.addWidget(self.settings_center)
        self._central_stack = QStackedWidget()
        self._central_stack.addWidget(central)
        self._central_stack.addWidget(self.ai_focus_sidebar)
        self._central_stack.addWidget(self.settings_page)
        self._central_stack.setCurrentWidget(central)
        self._settings_open = False
        self.setCentralWidget(self._central_stack)
        self._position_resize_handles()
        self._background = central
        central.installEventFilter(self)
        self.apply_background()

        # ---- 全局键盘导航(遥控器式):顶部分类标签 左右切换;当前页左菜单 上下切换;Enter 进入分项 ----
        # 焦点在实例列表/按钮/输入框等"自己会消费按键"的控件上时不抢键(防回归)。
        try:
            from launcher_app.ui.keyboard_nav import install_global_nav

            def _current_page_menu(win):
                """返回当前主标签页内的左菜单(QWidget)或 None。"""
                idx = win.main_tabs.currentIndex()
                page = win.main_tabs.widget(idx) if idx >= 0 else None
                if page is None:
                    return None
                # 各页左菜单属性名
                for attr in ("menu", "shell"):
                    m = getattr(page, attr, None)
                    if m is not None:
                        return m
                # 兜底:递归找一个 LeftMenu
                from launcher_app.ui.left_menu import LeftMenu
                return page.findChild(LeftMenu)

            install_global_nav(self, _current_page_menu)
        except Exception:
            pass

        # 标题栏作为顶部 dock(全宽),让右侧 AI dock 从标题栏下方开始,
        # 右上角留给 最小化/关闭(标题栏不顶住 dock 的上边缘)
        self.title_dock = QDockWidget(self)
        self.title_dock.setAllowedAreas(Qt.DockWidgetArea.TopDockWidgetArea)
        self.title_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.title_dock.setTitleBarWidget(QWidget())   # 隐藏 dock 自带标题栏
        self.title_dock.setWidget(self.title_bar)
        self.title_dock.setAutoFillBackground(True)
        self.title_bar.setAutoFillBackground(True)
        self._paint_title_background()
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.title_dock)
        # 修复 dock"放不回去":允许嵌套/标签 + 动画(拖出后能顺利拖回边缘复原)
        self.setDockOptions(QMainWindow.DockOption.AllowNestedDocks
                            | QMainWindow.DockOption.AllowTabbedDocks
                            | QMainWindow.DockOption.AnimatedDocks)

        # ---- AI 助手/游戏日志:停靠在右侧,做成"标签页"(tab)形式 ----
        # 允许拖动(可浮出成子窗口)、可关闭;标签页之间点击切换显示/隐藏。
        self.ai_dock = AIChatDock(self, self.settings)
        self.ai_dock.archive_changed.connect(self.ai_focus_sidebar.refresh_sessions)
        self.ai_dock.conversation_changed.connect(self.ai_focus_sidebar.refresh_sessions)
        def log_pin(pos):
            selected = self.log_view.textCursor().selectedText()
            return {"id": "game-log", "name": "游戏日志选段" if selected else "最近游戏日志",
                    "kind": "log", "content": selected.replace("\u2029", "\n") if selected
                    else self.log_view.toPlainText()[-4000:]}
        self.log_view.ai_pin_provider = log_pin
        self.ai_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.ai_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                                 | QDockWidget.DockWidgetFeature.DockWidgetFloatable
                                 | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.ai_dock)
        self.ai_dock.installEventFilter(self)
        self.ai_dock.visibilityChanged.connect(self._on_ai_visibility)
        self.ai_dock.topLevelChanged.connect(lambda _floating: QTimer.singleShot(0, self._update_window_shape))
        self.ai_dock.visibilityChanged.connect(lambda _visible: QTimer.singleShot(0, self._update_window_shape))
        self.ai_dock.show()
        self.online_dock.hide()

        # 游戏日志已挪进实例详情,不再有独立 dock(AI 助手单独在右侧作标签页)

        # ---- AI 助手被 × / 隐藏时:收窄成贴在右边缘的小条(留「展开」) ----
        self._build_ai_strip()

        # ---- 技能管理器(游戏运行时辅助功能,可插拔) ----
        self.skill_mgr = SkillManager(self, self.settings)
        self.home_panel.set_smart_import_enabled(
            self.skill_mgr.is_enabled('smart_import'))

        # 游戏进程相关的运行时状态
        self.game_process = None
        self._launch_task = None
        self.game_sessions = GameSessionController(self)
        self.game_sessions.line_received.connect(self._on_game_log_line)
        self.game_sessions.exited.connect(self._on_game_process_exited)
        self.game_sessions.background_exited.connect(self._scan_running_games)
        from launcher_app.runtime.running_games import RunningGames
        self.running_games = RunningGames()
        self._running_scan_task = None
        self._running_scan_timer = QTimer(self)
        self._running_scan_timer.setInterval(2500)
        self._running_scan_timer.timeout.connect(self._scan_running_games)
        self._running_scan_timer.start()
        QTimer.singleShot(0, self._scan_running_games)
        self.download_tasks = DownloadTaskController(self)
        self.download_tasks.status.connect(self._on_download_status)
        self.download_tasks.progress.connect(self._on_download_progress)
        self.download_tasks.completed.connect(self._on_download_done)
        self.download_tasks.cancelled.connect(self._on_download_cancelled)
        self.version_manifest = VersionManifestController(fetch_version_manifest, self)
        self.version_manifest.loaded.connect(self._apply_version_manifest)
        self.version_manifest.failed.connect(self._on_version_manifest_failed)
        self._manifest_retry_delay_ms = 3000
        self._manifest_retry_timer = QTimer(self)
        self._manifest_retry_timer.setSingleShot(True)
        self._manifest_retry_timer.timeout.connect(self.load_versions)

        # 应用视图模式(图标/列表,来自设置)
        self.set_view_mode(self.instance_list,
                           self.settings.get("view_icons_instances", False), "instances")

        self.refresh_instances()
        self.statusBar().showMessage("就绪")

        # 监听 versions/ 目录文件变动 → 实例列表自动刷新(如外部新增/删除实例文件夹)
        self._setup_instance_watcher()

        # 状态球作为内容区子控件，Wayland 下也能正常定位和拖动。
        self._dl_log = []                      # 本次下载的状态消息流
        self._dl_progress = (0, 1)
        # 下载球 = 悬浮球:置顶、可拖动,默认在内容区右下角(AI 子窗口左侧、主窗口侧外部)
        self.dl_indicator = DownloadIndicator(self._background)
        from launcher_app.ui.task_center import TaskCenter
        self.task_center = TaskCenter(self.dl_indicator, self)
        from launcher_app.ui.import_recovery import ImportRecoveryController
        self._import_recovery = ImportRecoveryController(self, self.task_center)
        self.dl_indicator.clicked.connect(self.open_download_detail)
        self.dl_indicator.shown.connect(self._place_download_ball)
        self.dl_indicator.show()
        self.dl_indicator.raise_()

        # 拖放:把文件(整合包)拖进窗口 → 覆盖层提示"松手尝试安装" → 松手导入
        self.setAcceptDrops(True)
        self._build_drop_overlay()

        # 运行中的实例指示:已在标题栏显示"已有 x 个运行中的实例"(悬停看具体是哪个)
        # (self._running_instances / _running_label 已在创建标题栏时初始化)
        self._update_running_label()

        # 状态栏隐藏:信息走启动器日志 / 下载球 / 提示条;自绘状态栏留待后续
        self.statusBar().hide()
        self.apply_background()   # AI dock 已建好,再刷一次让 dock 也带上壁纸(幂等)

        # 启动阶段结束标记。详情页已改为「用户点开才显示」的覆盖层,不再需要在
        # 这里挡住自动挂载;保留该标记供外部/测试判断窗口是否已完成初始化。
        self._ui_ready = True
        from launcher_app.ui.ui_anim import install_interaction_feedback
        self._interaction_feedback = install_interaction_feedback(self)
        # 窗口大小/位置:放在最后恢复,确保其它控件已建好、不会在显示过程中被挤压
        self._restore_window_geometry()
        QTimer.singleShot(0, self._place_download_ball)

    # ---- 设置 ----
    def open_settings(self, tab: str | None = None):
        """在主窗口中打开两种模式共用的设置页。"""
        self.settings_center.refresh_backup_settings()
        if tab == "mirror":
            self.settings_center.shell.switch_by_label(t("MIRROR"))
        if self._settings_open:
            return
        self._settings_restore = {
            'dock_visible': self.ai_dock.isVisible(),
            'strip_visible': self.ai_strip_dock.isVisible(),
            'download_visible': self.dl_indicator.isVisible(),
        }
        self._settings_open = True
        self.ai_dock.hide()
        self.ai_strip_dock.hide()
        self.dl_indicator.hide()
        self._central_stack.setMaximumWidth(16777215)
        self._central_stack.setCurrentWidget(self.settings_page)
        self._update_mode_button()
        self._recompute_wallpaper()
        from launcher_app.ui.ui_anim import reveal
        reveal(self.settings_page)

    def _close_settings(self):
        self.settings_center.flush_autosave()
        if not self._settings_open:
            return
        saved = self._settings_restore
        self._settings_open = False
        if self._ai_focus_mode:
            self._central_stack.setMaximumWidth(300)
            self._central_stack.setCurrentWidget(self.ai_focus_sidebar)
        else:
            self._central_stack.setCurrentWidget(self._background)
            self.main_tabs.setCurrentIndex(self._my_inst_tab_idx)
        self.ai_dock.setVisible(saved['dock_visible'])
        self.ai_strip_dock.setVisible(saved['strip_visible'])
        self.dl_indicator.setVisible(saved['download_visible'])
        self._update_mode_button()
        self._recompute_wallpaper()
        from launcher_app.ui.ui_anim import reveal
        reveal(self._central_stack.currentWidget())

    def _on_mode_button_clicked(self):
        if self._settings_open:
            self._close_settings()
        else:
            self._toggle_ai_focus_mode()

    def _update_mode_button(self):
        other_page = self._settings_open
        if other_page:
            self.ai_mode_button.setText(t('主页'))
            self.ai_mode_button.setToolTip(t('返回当前模式的主页'))
        elif self._ai_focus_mode:
            self.ai_mode_button.setText(t('常规模式'))
            self.ai_mode_button.setToolTip(t('退出 AI 模式'))
        else:
            self.ai_mode_button.setText(t('AI 模式'))
            self.ai_mode_button.setToolTip(t('进入全屏对话工作台'))

    def _on_settings_applied(self):
        """设置窗口保存后:刷新本窗口与各处联动。"""
        s = self.settings_center.settings
        self.settings = s
        from launcher_app.ui.ui_anim import set_animations_enabled
        set_animations_enabled(s.get("ui_animations_enabled", True))
        self.ai_dock.apply_settings(s)
        self.skill_mgr.settings = s
        self.resource_center.set_ui_mode(s.get("ui_mode", "beginner"))
        self.refresh_instances()   # 游戏目录可能被改了,重新扫描
        self._watch_versions_dir()   # 游戏目录若变更,把监听指向新的 versions/
        self._on_visual_settings_changed()   # 主题/壁纸/遮罩变化 → 立即生效
        self.statusBar().showMessage("设置已保存")

    def _on_visual_settings_changed(self):
        """颜色/壁纸/动画自动保存后只刷新外观，避免重扫实例和重载 AI。"""
        self.settings = self.settings_center.settings
        from launcher_app.ui.ui_style import (set_theme_mode, apply_global_dark_palette,
                              popup_menu_style, refresh_theme)
        set_theme_mode(self.settings.get('ui_theme', 'system'))
        apply_global_dark_palette(QApplication.instance())
        refresh_theme()
        self.title_bar.refresh_theme()
        self._paint_title_background()
        self.ai_dock._dock_header.refresh_theme()
        from launcher_app.ui.ui_anim import set_animations_enabled
        set_animations_enabled(self.settings.get("ui_animations_enabled", True))
        self.apply_background()
        self._apply_dock_separator_style()
        self.dl_indicator.update()
        self.home_panel.refresh_visual()

    def _on_system_color_scheme_changed(self, *_):
        """System mode selects an app theme, then refreshes all app surfaces."""
        if self.settings_center.theme_combo.currentData() != 'system':
            return
        self.settings_center.refresh_wallpaper_defaults()
        self._on_visual_settings_changed()

    def _on_runtime_settings_changed(self):
        """Java 首选等设置保存后立即供启动服务读取，不做昂贵的界面刷新。"""
        self.settings = self.settings_center.settings

    def apply_background(self):
        """按设置应用背景壁纸 + 遮罩 + 面板/按钮/文本框透明化(阶段 2 · 决策 2)。"""
        from launcher_app.ui.ui_background import (load_wallpaper, mask_strength,
                                   input_style_qss, scroll_surface_qss)
        from launcher_app.ui.ui_tokens import set_wallpaper_active, is_wallpaper_active
        pix = load_wallpaper(self.settings)
        mask = mask_strength(self.settings)
        active = pix is not None
        self._wallpaper_source = pix
        self._wallpaper_mask = mask
        self._recompute_wallpaper()
        # 文本框透明化(全局 QSS,仅壁纸模式;无壁纸时清空回 QPalette)
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            new_qss = scroll_surface_qss() + (input_style_qss() if active else "")
            if app.styleSheet() != new_qss:   # 样式串没变就别重设,避免无谓 re-polish
                app.setStyleSheet(new_qss)
        # 壁纸激活态变了 → 切换面板/按钮不透明度并全量重刷样式(否则跳过,省成本)
        if is_wallpaper_active() != active:
            set_wallpaper_active(active)
            from launcher_app.ui.ui_style import refresh_theme
            refresh_theme()
        self._apply_dock_separator_style()

    def _apply_dock_separator_style(self):
        """Give the AI dock a visible, generous resize seam."""
        from launcher_app.ui.ui_style import current_color
        base = current_color('btn_border')
        hover = current_color('accent')
        self.setStyleSheet(
            f'QMainWindow::separator {{ background: {base}; width: 7px; height: 7px; }}'
            f'QMainWindow::separator:hover {{ background: {hover}; }}')

    def _paint_title_background(self):
        """Keep the top dock opaque when the Linux window itself is translucent."""
        from launcher_app.ui.ui_style import current_color
        color = QColor(current_color('bg1'))
        for widget in (self.title_dock, self.title_bar):
            palette = widget.palette()
            palette.setColor(QPalette.ColorRole.Window, color)
            widget.setPalette(palette)

    def _recompute_wallpaper(self):
        """Publish the asset to active views; keep dock compatibility state here."""
        from launcher_app.ui.wallpaper_presenter import present_wallpaper
        settings_open = getattr(self, '_settings_open', False)
        focus = getattr(self, '_ai_focus_mode', False) and not settings_open
        canvas = present_wallpaper(
            getattr(self, '_wallpaper_source', None),
            getattr(self, '_wallpaper_mask', 0.55),
            background=getattr(self, '_background', None),
            online=getattr(self, 'online_surface', None),
            settings_surface=self.settings_page if settings_open else None,
            focus_surface=self.ai_focus_sidebar if focus else None,
            focus_width=self.width() if focus else 0,
            dock_width=self._ai_dock_width() if not settings_open and not focus else 0,
        )
        if canvas is not None:
            self._wallpaper_scaled = canvas.pixmap
            self._wallpaper_ox, self._wallpaper_oy = canvas.x, canvas.y
            self._sync_ai_wallpaper()

    def _ai_dock_width(self) -> int:
        """右侧 AI dock 的当前宽度(用于共享画布覆盖「中央 + dock」的左右跨度)。
        用 isHidden 而非 isVisible:初始布局阶段 isVisible 可能尚未置真。"""
        try:
            d = getattr(self, "ai_dock", None)
            if d is not None and not d.isHidden():
                return max(0, d.width())
        except Exception:
            pass
        return 0

    def _sync_ai_wallpaper(self):
        """把共享壁纸片段同步给 AI dock 与收起窄条(按相对中央区位置)。"""
        if hasattr(self, "ai_dock") and hasattr(self.ai_dock, "_sync_wallpaper_view"):
            self.ai_dock._sync_wallpaper_view()
        self._sync_strip_wallpaper()

    def _sync_strip_wallpaper(self):
        """把共享壁纸片段同步给收起窄条。"""
        strip = getattr(self, "ai_strip", None)
        central = getattr(self, "_background", None)
        if strip is None or central is None:
            return
        scaled = getattr(self, "_wallpaper_scaled", None)
        if scaled is None:
            strip.clear()
            return
        ox = getattr(self, "_wallpaper_ox", 0)
        oy = getattr(self, "_wallpaper_oy", 0)
        mask = getattr(self, "_wallpaper_mask", 0.6)
        dg = strip.mapToGlobal(strip.rect().topLeft())
        cg = central.mapToGlobal(central.rect().topLeft())
        strip.set_shared_view(scaled, ox + dg.x() - cg.x(), oy + dg.y() - cg.y(), mask)

    def open_update_dialog(self):
        """设置 → 检查更新:AMCL 启动器 + bridge-mod(帮助菜单已移除,入口并入设置菜单)"""
        dlg = UpdateDialog(self)
        dlg.exec()

    def nativeEvent(self, eventType, message):
        """Windows:WM_NCHITTEST → 无边框窗口四边/四角均可拉拽缩放;并补齐任务栏最小化样式。"""
        if sys.platform == "win32" and eventType == b"windows_generic_MSG":
            import ctypes
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0084:   # WM_NCHITTEST
                if not (self.isMaximized() or self.isFullScreen()):
                    lparam = int(msg.lParam)
                    sx = ctypes.c_short(lparam & 0xFFFF).value
                    sy = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                    from launcher_app.ui.win_frameless import hit_test
                    hit = hit_test(int(self.winId()), sx, sy)
                    if hit != 1:
                        return True, hit
        return super().nativeEvent(eventType, message)

    # ---- 跨平台边缘拉拽缩放(Linux/macOS/Windows 均生效) ----
    # Windows:优先走 nativeEvent + WM_NCHITTEST(已覆盖);下面的逻辑不干预。
    # Linux/macOS:透明边缘手柄直接接收鼠标事件，优先请求窗口管理器缩放。
    class _ResizeHandle(QWidget):
        """透明边缘手柄：覆盖在窗口某条边上，接收鼠标事件实现拖拽缩放。"""
        def __init__(self, edge, main_win):
            super().__init__(main_win)
            self._edge = edge          # Qt.Edge
            self._win = main_win
            self._drag_origin = None   # QPoint(屏幕坐标)
            self._geo_origin = None
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        def mousePressEvent(self, e):
            if e.button() == Qt.MouseButton.LeftButton and not self._win.isMaximized():
                self._drag_origin = None
                self._geo_origin = None
                handle = self._win.windowHandle()
                if handle is not None and handle.startSystemResize(self._edge):
                    e.accept()
                    return
                if sys.platform.startswith('linux'):
                    # Even in an XWayland session, changing x and width together
                    # can apply the left-edge displacement twice. Never use the
                    # geometry fallback there; only the compositor can anchor it.
                    self._win.statusBar().showMessage(
                        f'当前窗口系统（{QGuiApplication.platformName()}）未接管边缘缩放。', 5000)
                    e.accept()
                    return
                # Use one desktop coordinate source throughout the fallback drag.
                self._drag_origin = QCursor.pos()
                self._geo_origin  = self._win.geometry()
                e.accept()
        def mouseMoveEvent(self, e):
            if self._drag_origin is None:
                return
            mp  = QCursor.pos()
            d   = mp - self._drag_origin
            g   = self._geo_origin
            edge = self._edge
            minw = self._win.minimumWidth()
            minh = self._win.minimumHeight()
            nx, ny, nw, nh = g.x(), g.y(), g.width(), g.height()
            if edge & Qt.Edge.RightEdge:
                nw = max(minw, g.width()  + d.x())
            if edge & Qt.Edge.BottomEdge:
                nh = max(minh, g.height() + d.y())
            if edge & Qt.Edge.LeftEdge:
                nw = max(minw, g.width()  - d.x())
                nx = g.x() + (g.width() - nw)
            if edge & Qt.Edge.TopEdge:
                nh = max(minh, g.height() - d.y())
                ny = g.y() + (g.height() - nh)
            # 防止重入
            if hasattr(self._win, '_resize_guard') and self._win._resize_guard:
                return
            self._win._resize_guard = True
            self._win.setGeometry(nx, ny, nw, nh)
            self._win._resize_guard = False
            e.accept()
        def mouseReleaseEvent(self, e):
            self._drag_origin = None
            self._geo_origin  = None
            e.accept()

    def _setup_resize_handles(self):
        """在窗口四边/四角各放一个透明手柄，始终保持在内容之上。"""
        C = self._ResizeHandle
        self._resize_handles = {
            # 角(先放，四边在上面裁剪)
            'tl': C(Qt.Edge.TopEdge | Qt.Edge.LeftEdge,   self),
            'tr': C(Qt.Edge.TopEdge | Qt.Edge.RightEdge,  self),
            'bl': C(Qt.Edge.BottomEdge | Qt.Edge.LeftEdge, self),
            'br': C(Qt.Edge.BottomEdge | Qt.Edge.RightEdge, self),
            # 边
            't': C(Qt.Edge.TopEdge,    self),
            'b': C(Qt.Edge.BottomEdge, self),
            'l': C(Qt.Edge.LeftEdge,   self),
            'r': C(Qt.Edge.RightEdge,  self),
        }
        self._resize_guard = False
        self._position_resize_handles()
        # 光标样式
        cursor_map = {
            'l': Qt.CursorShape.SizeHorCursor, 'r': Qt.CursorShape.SizeHorCursor,
            't': Qt.CursorShape.SizeVerCursor, 'b': Qt.CursorShape.SizeVerCursor,
            'tl': Qt.CursorShape.SizeFDiagCursor, 'br': Qt.CursorShape.SizeFDiagCursor,
            'tr': Qt.CursorShape.SizeBDiagCursor, 'bl': Qt.CursorShape.SizeBDiagCursor,
        }
        for k, w in self._resize_handles.items():
            w.setCursor(cursor_map[k])
            w.show()
            w.raise_()

    def _position_resize_handles(self):
        """根据当前窗口尺寸，定位所有边缘手柄。"""
        if not hasattr(self, '_resize_handles'):
            return
        if self.isMaximized() or self.isFullScreen():
            for handle in self._resize_handles.values():
                handle.hide()
            return
        m = 9   # 缩放区贴住窗口外沿，少侵入内容/标题栏按钮
        c = 22  # 底角保留较大的对角缩放命中区
        W, H = self.width(), self.height()
        h = self._resize_handles
        # 顶部两个角只覆盖最外侧 7px；原来的 24px 方块压住了右上角 X。
        h['tl'].setGeometry(0, 0, c, 7)
        h['tr'].setGeometry(W - c, 0, c, 7)
        h['bl'].setGeometry(0, H - c, c, c)
        h['br'].setGeometry(W - c, H - c, c, c)
        # 左右边缘从标题栏下方开始，避免覆盖窗口控制按钮。
        h['t'].setGeometry(c, 0, max(0, W - 2*c), 7)
        h['b'].setGeometry(c, H - m, max(0, W - 2*c), m)
        h['l'].setGeometry(0, 36, m, max(0, H - c - 36))
        h['r'].setGeometry(W - m, 36, m, max(0, H - c - 36))
        for handle in h.values():
            handle.show()
            handle.raise_()

    def mouseMoveEvent(self, e):
        # Only the dedicated 6px handles use resize cursors. Global-position
        # hit testing here misclassifies empty content on Linux/Wayland.
        super().mouseMoveEvent(e)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._update_window_shape()
        self._position_resize_handles()
        if sys.platform == "win32" and getattr(self, "_win_patched", False) is False:
            try:
                from launcher_app.ui.win_frameless import apply_win_styles
                apply_win_styles(int(self.winId()))
                self._win_patched = True
            except Exception:
                pass
        # 布局落定后再重算一次共享壁纸(此时中央区/dock 尺寸已正确)
        if getattr(self, "_wallpaper_source", None) is not None:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._recompute_wallpaper)
        # 「检测到 mod → 问要不要装插件」放在窗口真正显示之后:一来不挡启动,
        # 二来窗口还没露脸就弹模态框很奇怪(未显示的窗口不提示,见该方法)。
        if not getattr(self, "_plugin_prompt_scheduled", False):
            self._plugin_prompt_scheduled = True
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1200, self.maybe_prompt_plugin_for_mods)

    # ---- 窗口几何:记住大小与位置 ----
    def _restore_window_geometry(self):
        """启动时恢复上次的窗口大小/位置;没有记录或记录不可见则用默认尺寸。

        最大化/最小化不写入记录(见 window_geometry.capture),所以这里恢复的
        始终是一个普通状态的尺寸,用户在标题栏还能自己最大化。
        """
        import launcher_app.ui.window_geometry as wg
        try:
            target = wg.restore_target(self.settings.get(wg.SETTINGS_KEY),
                                       QApplication.screens(),
                                       QApplication.primaryScreen())
        except Exception:
            # 任何异常都退回默认尺寸,绝不让「记不住尺寸」变成「打不开窗口」
            target = {'x': 60, 'y': 60, 'w': wg.DEFAULT_SIZE[0],
                      'h': wg.DEFAULT_SIZE[1]}
        self.setGeometry(target['x'], target['y'], target['w'], target['h'])

    def _save_window_geometry(self):
        """关闭时保存几何;最大化/全屏时不覆盖已有记录。"""
        try:
            import launcher_app.ui.window_geometry as wg
            geom = wg.capture(self)
            if geom is None:
                return
            data = load_settings()
            data[wg.SETTINGS_KEY] = geom
            save_settings(data)
        except Exception:
            pass      # 记不住尺寸不该影响关窗

    def reset_window_geometry(self):
        """「恢复默认尺寸」:回到默认大小并居中(标题栏按钮调用)。"""
        import launcher_app.ui.window_geometry as wg
        target = wg.default_geometry(QApplication.screens(),
                                     QApplication.primaryScreen())
        if self.isMaximized() or self.isFullScreen():
            self.showNormal()
        self.setGeometry(target['x'], target['y'], target['w'], target['h'])
        # 立刻落盘,用户不必再关一次窗口才生效
        self._save_window_geometry()
        self.statusBar().showMessage('窗口已恢复默认尺寸', 3000)

    def maybe_prompt_plugin_for_mods(self):
        """检测到对应 Mod 后，以不阻断操作的卡片提示可选插件。

        见 ``plugin_prompt`` 与 docs/PLUGIN_IDEAS.md 的红线:**只问一次**、把拒绝也
        记住、绝不静默启用。这里仅在启动后调用一次。
        """
        try:
            import launcher_app.extensions.plugin_prompt as pp
            installed = pp.installed_mod_names(paths.GAME_DIR)
            if not installed:
                return
            pending = pp.pending_prompts(self.settings, installed,
                                         pp.missing_candidates(self.settings))
        except Exception:
            return                       # 探测失败不该影响启动
        if not pending or not self.isVisible():
            return                       # 测试/后台场景不展示
        self._plugin_notice_queue = list(pending)
        self._show_next_plugin_notice()

    def _show_next_plugin_notice(self):
        """一次只展示一个提示；没有 modal event loop，其他页面始终可操作。"""
        if getattr(self, '_plugin_notice', None) is not None:
            return
        queue = getattr(self, '_plugin_notice_queue', [])
        if not queue:
            return
        item = queue.pop(0)
        dock = QDockWidget('发现可用插件', self)
        dock.setObjectName('PluginDiscoveryNotice')
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        content = QWidget(dock)
        layout = QHBoxLayout(content)
        layout.setContentsMargins(10, 5, 10, 5)
        label = QLabel(
            t('检测到 {v0}；插件「{v1}」可提供对应的管理界面。启用后下次启动生效，也能在「设置 → 插件」里调整。').format(v0=(', '.join(item['mods'])), v1=(item['name'])))
        label.setWordWrap(True)
        layout.addWidget(label, 1)
        enable = QPushButton(t('启用插件'))
        later = QPushButton(t('暂不启用'))
        layout.addWidget(enable)
        layout.addWidget(later)
        dock.setWidget(content)
        self._plugin_notice = dock
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

        def finish(*, declined):
            import launcher_app.extensions.plugin_prompt as pp
            data = pp.remember(load_settings(), item['id'], declined=declined)
            if not declined:
                enabled = set(data.get('plugins_enabled', []) or [])
                enabled.add(item['id'])
                data['plugins_enabled'] = sorted(enabled)
                disabled = set(data.get('plugins_disabled', []) or [])
                disabled.discard(item['id'])
                data['plugins_disabled'] = sorted(disabled)
            save_settings(data)
            self.settings = data
            self.removeDockWidget(dock)
            dock.deleteLater()
            self._plugin_notice = None
            self.statusBar().showMessage(
                '已启用插件，下次启动生效' if not declined else '已记住，下次不再提醒该插件', 4000)
            QTimer.singleShot(0, self._show_next_plugin_notice)

        enable.clicked.connect(lambda: finish(declined=False))
        later.clicked.connect(lambda: finish(declined=True))
        dock.show()

    def closeEvent(self, event):
        self.settings_center.flush_autosave()
        if getattr(self.home_panel.server_center, '_busy', False):
            inline_notice(self, t('服务端任务尚未结束'), t('请等待服务端扫描、导入或补全任务结束后再关闭启动器。'))
            event.ignore()
            return
        """窗口关闭:卸载本地 AI 引擎(llama-server),确保无残留进程。"""
        self._save_window_geometry()
        self.download_tasks.cancel()
        if self._launch_task is not None:
            self._launch_task.cancel()
        self.version_manifest.cancel()
        self.game_sessions.detach()
        self._stop_in_game_ai()
        memory = getattr(self, '_memory_launch_controller', None)
        if memory is not None:
            memory.close()
        self._running_scan_timer.stop()
        if self._running_scan_task is not None:
            self._running_scan_task.cancel()
        if self._server_running_task is not None:
            self._server_running_task.cancel()
        if hasattr(self, "ai_dock"):
            try:
                self.ai_dock.shutdown()
            except Exception:
                pass
        super().closeEvent(event)

    # ---- AI 助手 ----
    def _toggle_ai_focus_mode(self):
        """Play the full transition before switching between launcher and AI layouts."""
        if getattr(self, '_ai_transition', None) is not None:
            return
        from launcher_app.ai.ai_focus_mode import AIFocusTransition
        entering = not self._ai_focus_mode
        transition = AIFocusTransition(self, entering)
        self._ai_transition = transition
        top = self.title_dock.height() if hasattr(self, 'title_dock') else 36
        transition.setGeometry(0, top, self.width(), max(0, self.height() - top))
        transition.finished.connect(lambda: self._finish_ai_focus_mode(entering))
        self.ai_mode_button.setEnabled(False)
        transition.start()

    def _finish_ai_focus_mode(self, entering):
        """Reuse the live AI dock so its messages, tools and input stay intact."""
        if entering:
            dock = self.ai_dock
            self._ai_focus_restore = {
                'visible': dock.isVisible(),
                'floating': dock.isFloating(),
                'geometry': dock.geometry(),
                'width': dock.width(),
                'features': dock.features(),
                'tab': dock.tabs.currentIndex(),
                'status_visible': self.statusBar().isVisible(),
                'download_visible': self.dl_indicator.isVisible(),
            }
            self.ai_focus_sidebar.refresh_from_home()
            if dock.isFloating():
                dock.setFloating(False)
            dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
            dock.tabs.setCurrentIndex(0)
            dock.set_focus_mode(True)
            current = self.instance_list.currentItem()
            dock.update_focus_target(
                current.data(Qt.ItemDataRole.UserRole) if current else None)
            header = dock._dock_header
            header.archive_button.hide()
            header.float_button.hide()
            header.close_button.hide()
            header.chat_button.setText(t('对话'))
            self._central_stack.setCurrentWidget(self.ai_focus_sidebar)
            self._central_stack.setMaximumWidth(300)
            self.ai_strip_dock.hide()
            dock.show()
            self.statusBar().hide()
            self.dl_indicator.hide()
            self._ai_focus_mode = True
            self._recompute_wallpaper()
            QTimer.singleShot(0, lambda: self.resizeDocks(
                [dock], [max(320, self.width() - self.ai_focus_sidebar.width() - 12)],
                Qt.Orientation.Horizontal))
            QTimer.singleShot(0, self._recompute_wallpaper)
            QTimer.singleShot(0, dock.input.setFocus)
        else:
            saved = getattr(self, '_ai_focus_restore', {})
            self._ai_focus_mode = False
            self._central_stack.setMaximumWidth(16777215)
            self._central_stack.setCurrentWidget(self._background)
            dock = self.ai_dock
            dock.set_focus_mode(False)
            header = dock._dock_header
            header.archive_button.show()
            header.float_button.show()
            header.close_button.show()
            header.chat_button.setText(t('聊天'))
            dock.setFeatures(saved.get('features', dock.features()))
            dock.tabs.setCurrentIndex(saved.get('tab', 0))
            if saved.get('floating'):
                dock.setFloating(True)
                dock.setGeometry(saved['geometry'])
            else:
                QTimer.singleShot(0, lambda: self.resizeDocks(
                    [dock], [saved.get('width', 360)], Qt.Orientation.Horizontal))
            dock.setVisible(saved.get('visible', True))
            self.statusBar().setVisible(saved.get('status_visible', True))
            self.dl_indicator.setVisible(saved.get('download_visible', False))
            self._ai_focus_restore = None
        self._update_mode_button()
        self.ai_mode_button.setEnabled(True)
        transition = self._ai_transition
        self._ai_transition = None
        if transition is not None:
            transition.hide()
            transition.deleteLater()
        QTimer.singleShot(0, self._refresh_central_geometry)

    def _toggle_ai(self, checked: bool):
        """显示/隐藏右侧 AI 对话栏(靠其自身标题/关闭控制,不再有菜单入口)"""
        if hasattr(self, "ai_dock"):
            self.ai_dock.setVisible(bool(checked))

    def open_online_center(self):
        """打开可拖动、缩放的联机浮窗，保留主窗口原有布局。"""
        if not getattr(self, '_online_window_positioned', False):
            area = self.screen().availableGeometry()
            width = min(960, area.width())
            height = min(720, area.height())
            self.online_dock.resize(width, height)
            self.online_dock.move(area.center() - QPoint(width // 2, height // 2))
            self._online_window_positioned = True
        was_visible = self.online_dock.isVisible()
        self.online_dock.showNormal()
        self.online_dock.raise_()
        self.online_dock.activateWindow()
        self.online_surface.set_wallpaper(
            getattr(self, '_wallpaper_source', None), getattr(self, '_wallpaper_mask', 0.55))
        if not was_visible:
            from launcher_app.ui.ui_anim import reveal
            QTimer.singleShot(0, lambda: reveal(self.online_surface)
                              if self.online_dock.isVisible() else None)

    def _close_online_center(self):
        self.online_dock.hide()

    def _toggle_online_center(self):
        if self.online_dock.isVisible():
            self._close_online_center()
        else:
            self.open_online_center()

    def _open_resource_page(self, page_index: int):
        """首页常用操作直达资源中心，避免新建游戏/下载 Mod 被埋进二级菜单。"""
        if not hasattr(self, "resource_center") or not hasattr(self, "main_tabs"):
            return
        idx = self.main_tabs.indexOf(self.resource_center)
        if idx >= 0:
            self.main_tabs.setCurrentIndex(idx)
        self.resource_center.switch_to(int(page_index))

    def open_tutorial(self):
        """Keep older tutorial entry points on the current spotlight walkthrough."""
        self.open_guide_demo()

    def open_guide_demo(self, intro: bool = False):
        """用聚光遮罩引导首次下载、选版本/加载器和启动；不执行下载。"""
        # 兼容显式请求旧基础知识页的调用；首次引导和设置重播均直接进入遮罩。
        if intro:
            try:
                from launcher_app.ui.tutorial_intro import TutorialIntroDialog
                if TutorialIntroDialog(self).exec() != 1:
                    return   # 用户跳过基础知识 → 不继续引导
            except Exception:
                pass

        from launcher_app.ui.guide_overlay import GuideDriver
        from launcher_app.ui.tutorial_steps import first_game_steps
        self._guide_driver = GuideDriver(self, first_game_steps())
        self._guide_driver.finished.connect(lambda: self.statusBar().showMessage("引导教程演示结束"))
        self._guide_driver.start()

    def open_skill_manager(self):
        """打开技能与可选功能管理，勾选后立即切换对应工作流。"""
        dlg = SkillManagerDialog(self.skill_mgr, self)
        dlg.exec()
        self.home_panel.set_smart_import_enabled(
            self.skill_mgr.is_enabled('smart_import'))

    def send_game_command_dialog(self):
        """手动给运行中的游戏发指令(如 /summon zombie)。也可在 AI 输入框直接输 / 开头。"""
        from PySide6.QtWidgets import QInputDialog
        from launcher_app.instances.game_command import send_command
        cmd, ok = QInputDialog.getText(self, t('发送游戏指令'),
                                       t('输入游戏指令(如 summon zombie,可省略开头的 /):'))
        if not ok or not cmd.strip():
            return
        result = send_command(cmd, self)
        if "\n" in result:
            QMessageBox.information(self, t('游戏指令'), result)
        else:
            self.statusBar().showMessage(result)

    def _on_ai_visibility(self, visible: bool):
        """AI 对话栏可见性变化:X 掉/隐藏 → 收窄成贴右边缘小条(留「展开」);显示 → 收起小条。
        变化会影响右侧内容区宽度 → 重摆下载悬浮球 + 重算共享壁纸。"""
        if hasattr(self, "ai_strip_dock"):
            self.ai_strip_dock.setVisible(not visible and not self._ai_focus_mode)
        if hasattr(self, "dl_indicator"):
            QTimer.singleShot(0, self._place_download_ball)
        if getattr(self, "_wallpaper_source", None) is not None:
            self._recompute_wallpaper()

    def _build_ai_strip(self):
        """AI 被收起时贴在主窗口右边缘的超窄竖条:一个竖排「▶」按钮,点它展开。"""
        from launcher_app.ui.ui_background import BackgroundWidget
        self.ai_strip = BackgroundWidget()   # 窄条也透明,画共享壁纸片段
        self.ai_strip.setFixedWidth(22)
        sv = QVBoxLayout(self.ai_strip)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(0)
        expand_btn = QPushButton("▶")
        expand_btn.setFixedSize(22, 72)
        expand_btn.setToolTip(t('展开 AI 助手'))
        from launcher_app.ui.ui_style import set_style, accent_border_style
        set_style(expand_btn, accent_border_style)
        expand_btn.clicked.connect(self._expand_ai)
        sv.addWidget(expand_btn)
        sv.addStretch()
        self.ai_strip_dock = QDockWidget(t("AI_ASSISTANT"), self)
        self.ai_strip_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.ai_strip_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.ai_strip_dock.setTitleBarWidget(QWidget())   # 隐藏标题栏,只留窄条
        self.ai_strip_dock.setWidget(self.ai_strip)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.ai_strip_dock)
        self.ai_strip_dock.hide()

    def _expand_ai(self):
        """点边缘小条的「展开」:收起小条,把 AI 助手恢复为【停靠】状态(不浮成子窗口;
        想要独立窗口,直接拖 AI 标题栏 拖出即可)。"""
        if hasattr(self, "ai_strip_dock"):
            self.ai_strip_dock.hide()
        if hasattr(self, "ai_dock"):
            self.ai_dock.setFloating(False)   # 回到停靠,不再作为浮窗
            self.ai_dock.raise_()
            self.ai_dock.show()

    def ai_context(self) -> str:
        from launcher_app.ai.context_builder import launcher_context
        item = self.instance_list.currentItem()
        instance = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return launcher_context(self.settings, instance, i18n.get_language(), self.skill_mgr.ai_hints())

    # ---- 查看:图标/列表视图切换 ----
    def set_view_mode(self, list_widget: QListWidget, icon_mode: bool, key: str):
        """切换列表控件的大图标 / 列表视图,并记住设置"""
        if icon_mode:
            list_widget.setViewMode(QListWidget.ViewMode.IconMode)
            list_widget.setIconSize(QSize(64, 64))
            list_widget.setGridSize(QSize(130, 130))
            list_widget.setMovement(QListWidget.Movement.Static)
            list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
            list_widget.setSpacing(8)
        else:
            list_widget.setViewMode(QListWidget.ViewMode.ListMode)
            list_widget.setIconSize(QSize(20, 20))
        self.settings[f"view_icons_{key}"] = icon_mode
        from settings import update_setting
        update_setting(f"view_icons_{key}", icon_mode)

    # ---- 文件菜单动作 ----
    def open_game_dir(self):
        """打开游戏目录(所有版本共用文件的根目录)"""
        os.makedirs(paths.GAME_DIR, exist_ok=True)
        open_path(paths.GAME_DIR)

    def clear_instances(self):
        self._instance_actions().clear()

    def _pack_imports(self):
        controller = getattr(self, '_pack_import_controller', None)
        if controller is None:
            from launcher_app.ui.pack_import_controller import PackImportController
            from launcher_app.ui.smart_import_ui import start_smart_import
            from launcher_app.ui.cloud_download import choose_classic_archive
            from launcher_app.ui.import_safety import check_before_import
            from launcher_app.resources.folder_instance_import import start_import
            controller = PackImportController(
                parent=self,
                smart_enabled=lambda: getattr(getattr(self, 'skill_mgr', None), 'is_enabled', lambda _: False)('smart_import') is True,
                smart_import=lambda path, **kw: start_smart_import(self, path, **kw),
                choose_archive=lambda: choose_classic_archive(self),
                check_archive=lambda path, ready: check_before_import(self, path, ready),
                import_server=self._import_server_archive,
                import_directory=lambda path: start_import(self, [path]),
                submit=self._run_download, game_root=lambda: paths.GAME_DIR,
                show_status=lambda text: self.statusBar().showMessage(text))
            self._pack_import_controller = controller
        return controller

    def _import_server_archive(self, path):
        self.home_panel.tabs.setCurrentIndex(self.home_panel._server_tab_index)
        self.home_panel.server_center.scan_import(path)

    def import_modpack(self, path=None, *, safety_checked=False):
        return self._pack_imports().import_archive(path, safety_checked=safety_checked)

    # ---- 下载新实例:左侧菜单 → 分类面板 → 后台下载 ----
    def start_instance_download(self):
        """读取 DownloadTab 的汇总选择,后台线程创建实例(不卡界面)"""
        st = self.download_tab.state()
        if not st["version"]:
            self.download_tab.set_status("请先选一个游戏版本")
            return
        from launcher_app.instances.install_requests import InstanceCreateJob
        job = InstanceCreateJob(st, paths.GAME_DIR, self.settings.get('version_isolation'))
        self._run_download(job.run)

    # ---- 后台下载:统一任务对象用 Qt 信号把进度搬回主线程 ----
    def _run_download(self, worker_fn):
        """后台执行下载任务，并统一处理状态、进度、结果和异常。"""
        if self.download_tasks.is_running or (self._launch_task is not None and self._launch_task.is_running):
            self.statusBar().showMessage("已有下载任务正在进行，请等待它完成")
            return
        self._busy_download(True)
        # 左下角指示器:显示 + 归零;下载 tab 进度条也归零
        self._dl_log = []
        self._dl_progress = (0, 1)
        self.dl_indicator.set_progress(0, 1)
        self.dl_indicator.set_completed(False)
        if hasattr(self, 'task_center'):
            self._ensure_dl_overlay(create_download=True)
            self.task_center.begin_task('下载', task_id='download', cancel=self._cancel_current_task)
        self.dl_indicator.setToolTip(t('下载中,点击查看详情'))
        self.dl_indicator.show()
        try:
            self.download_tab.set_progress(0, 1)
        except Exception:
            pass

        if not self.download_tasks.start(worker_fn):
            self._busy_download(False)
            self.statusBar().showMessage("已有下载任务正在进行，请等待它完成")

    def _on_download_status(self, message: str):
        message = redact_text(message, self.settings)
        self.download_tab.set_status(message)
        self.statusBar().showMessage(message)
        self._dl_log.append(message)
        if hasattr(self, 'task_center'):
            self.task_center.update_task('download', message=message)

    def _on_download_progress(self, done: int, total: int):
        self.download_tab.set_progress(done, total)
        self.dl_indicator.set_progress(done, total)
        self._dl_progress = (done, total)
        if hasattr(self, 'task_center'):
            self.task_center.update_task('download', done=done, total=total)

    def _on_download_done(self, ok: bool, error: str):
        error = redact_text(error, self.settings)
        if hasattr(self, 'task_center'):
            self.task_center.finish_task('download', 'completed' if ok else 'failed', error or '下载完成')
        if ok:
            self.statusBar().showMessage("下载任务完成")
            self._dl_log.append("✅ 下载任务完成")
            self.dl_indicator.setToolTip(t('下载完成,点击查看详情'))
            self.dl_indicator.set_completed(True)
        else:
            self.statusBar().showMessage(f"下载失败: {error}")
            self._dl_log.append(f"❌ 下载失败: {error}")
            self.dl_indicator.setToolTip(t('下载失败,点击查看详情'))
            self.dl_indicator.set_completed(False)
        self.dl_indicator.set_progress(1, 1)
        self.dl_indicator.set_completed(ok)
        self.dl_indicator.set_failed(not ok)
        if not ok:
            advice = failure_advice(error)
            self._dl_log.append(advice)
            self.download_tab.set_status(f"下载失败：{error}\n{advice}")
            self.dl_indicator.setToolTip(t('下载失败\n{v0}\n点击查看详情').format(v0=(advice)))
        self._dl_finish(ok)
        if not ok and '[CF_MISSING_REPORT]' in error:
            from launcher_app.resources.cf_manual import show_missing_dialog
            show_missing_dialog(self, error, self._retry_download)

    def _on_download_cancelled(self):
        if hasattr(self, 'task_center'):
            self.task_center.finish_task('download', 'cancelled', '已取消')
        if self._launch_task is not None:
            self._stop_launch_button_animation()
        self._dl_log.append("已取消下载。已校验的文件会保留，重试时会尽量复用。")
        self.dl_indicator.set_progress(0, 1)
        self.dl_indicator.set_waiting()
        self.dl_indicator.setToolTip(t('下载已取消，点击查看详情'))
        self._busy_download(False)

    def _cancel_current_task(self):
        if self._launch_task is not None and self._launch_task.is_running:
            self._launch_task.cancel()
        else:
            self.download_tasks.cancel()
        self.dl_indicator.setToolTip(t('正在收尾，稍等一下…'))

    def _retry_download(self):
        if self.download_tasks.state not in {'failed', 'cancelled'}:
            return
        worker = self.download_tasks.last_worker
        if worker is not None:
            self._run_download(worker)

    def _ensure_dl_overlay(self, *, create_download=False, task_title="下载"):
        """惰性创建下载详情覆盖层(ContentOverlay + DownloadDetailWidget,复用不重复建)。"""
        if getattr(self, "_dl_overlay", None) is not None:
            return
        if hasattr(self, 'task_center'):
            if 'launcher-log' not in self.task_center.tasks:
                self.task_center.begin_task('启动器日志', task_id='launcher-log', page=self.log_view)
                self.task_center.update_task('launcher-log', state='idle')
            elif self.task_center.tabs.count() == 0:
                self.task_center.register_page('launcher-log', self.log_view)
            if create_download and 'download' not in self.task_center.tasks:
                def live():
                    return (list(self._dl_log), self._dl_progress[0], self._dl_progress[1])
                page = DownloadDetailWidget(self._dl_log, self._dl_progress[0], self._dl_progress[1],
                    live=live, cancel=self._cancel_current_task, retry=self._retry_download,
                    running=lambda: self.download_tasks.is_running or (self._launch_task is not None and self._launch_task.is_running),
                    retryable=lambda: self.download_tasks.state in {'failed', 'cancelled'},
                    flat=True)
                self.task_center.begin_task(task_title, task_id='download', page=page,
                                            cancel=self._cancel_current_task)
                self.task_center.update_task('download', state='idle')
            return
        from launcher_app.ui.ui_overlay import ContentOverlay

        def live():
            return (list(self._dl_log), self._dl_progress[0], self._dl_progress[1])

        self._dl_overlay = ContentOverlay(self._background)
        self._dl_overlay.set_title("状态与日志")
        self._dl_overlay.backRequested.connect(self._on_dl_back)
        self._dl_overlay.set_content(
            DownloadDetailWidget(self._dl_log, self._dl_progress[0], self._dl_progress[1],
                                 live=live, cancel=self._cancel_current_task,
                                 retry=self._retry_download,
                                 running=lambda: self.download_tasks.is_running or (self._launch_task is not None and self._launch_task.is_running),
                                 retryable=lambda: self.download_tasks.state in {'failed', 'cancelled'},
                                 launcher_log_view=self.log_view))

    def _on_dl_back(self):
        """下载详情返回:收起覆盖层,恢复主内容。"""
        if getattr(self, "_dl_overlay", None) is not None:
            self._dl_overlay.hide_overlay()
        self.main_tabs.show()
        self.dl_indicator.show()
        self.dl_indicator.raise_()

    def open_download_detail(self):
        """点击下载球:隐藏主内容,在主窗显示半透明下载详情覆盖层(返回按钮回原页)。"""
        self._ensure_dl_overlay()
        if hasattr(self, 'task_center'):
            self.task_center.present()
            return
        self.main_tabs.hide()   # 隐藏主内容,让半透明覆盖层直接压在壁纸上
        self.dl_indicator.hide()
        self._dl_overlay.show_overlay()

    def _dl_finish(self, _ok):
        self._busy_download(False)
        self.load_versions()
        self.refresh_instances()

    def _log_feedback_setup(self):
        """启动器反馈进日志:状态栏消息 + 未捕获异常 → 「启动器日志」(并写文件供 AI 读取)。"""
        self.log_view.setMaximumBlockCount(20000)
        self.statusBar().messageChanged.connect(
            lambda m: self._log_feedback(m, "状态"))
        # 日志文件(供 AI 定位问题读取):.minecraft/logs/launcher.log
        try:
            self._launcher_log_path = os.path.join(paths.GAME_DIR, "logs", 'launcher.log')
            os.makedirs(os.path.dirname(self._launcher_log_path), exist_ok=True)
        except Exception:
            self._launcher_log_path = None
        # 未捕获异常 → 记录(主线程);worker 线程由各自 try/except 报
        import sys as _sys
        _sys.excepthook = self._excepthook

    def _log_feedback(self, text, tag="", force=False):
        """把一条反馈写进「启动器日志」(线程安全:经 QTimer 回主线程 append)+ 日志文件。"""
        text = redact_text(text, self.settings).strip()
        if not text:
            return
        line = f"[{time.strftime('%H:%M:%S')}]{(' ' + str(tag)) if tag else ''} {text}"
        def _ap():
            self.log_view.appendPlainText(line)
            self.log_view.verticalScrollBar().setValue(
                self.log_view.verticalScrollBar().maximum())
            if self._launcher_log_path:
                try:
                    with open(self._launcher_log_path, "a", encoding="utf-8") as f:
                        f.write(line + "\n")
                except Exception:
                    pass
        QTimer.singleShot(0, _ap)

    def _excepthook(self, etype, evalue, tb):
        import traceback
        self._log_feedback("未捕获异常:\n" + "".join(traceback.format_exception(etype, evalue, tb)),
                           "异常", force=True)

    def _build_drop_overlay(self):
        """拖入文件时的覆盖层:整窗发白,提示「松手 → 尝试作为整合包安装」。"""
        ov = QWidget(self)
        ov.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        ov.setObjectName("dropOverlay")
        ov.setStyleSheet("background: rgba(255,255,255,0.90);")
        lay = QVBoxLayout(ov)
        lay.setContentsMargins(20, 20, 20, 20)
        lbl = QLabel(t("RELEASE_TO_INSTALL_AS_MODPACK"))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#222; font-size:17px; font-weight:bold; background: transparent;")
        lay.addWidget(lbl)
        ov.setGeometry(self.rect())
        ov.raise_()
        ov.hide()
        self._drop_overlay = ov

        # AI 浮窗专用落点；使用 Qt 拖放协议而非顶层窗口坐标，Wayland 也能识别。
        dock_hint = QLabel(t('松开，将 AI 助手停靠回右侧'), self)
        dock_hint.setObjectName("aiDockDropHint")
        dock_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dock_hint.setWordWrap(True)
        dock_hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        dock_hint.setStyleSheet(
            "QLabel { background: rgba(59,142,234,0.22); color: #1e6fd9;"
            " border: 2px dashed #3b8eea; border-radius: 12px;"
            " font-size: 16px; font-weight: bold; padding: 14px; }")
        dock_hint.hide()
        self._ai_dock_drop_hint = dock_hint

    def _show_ai_dock_drop_hint(self):
        hint = getattr(self, '_ai_dock_drop_hint', None)
        if hint is None:
            return
        width = min(300, max(180, self.width() // 4))
        hint.setGeometry(self.width() - width - 18, 54,
                         width, max(100, self.height() - 72))
        hint.raise_()
        hint.show()

    def _hide_ai_dock_drop_hint(self):
        hint = getattr(self, '_ai_dock_drop_hint', None)
        if hint is not None:
            hint.hide()

    def _is_ai_dock_return_drag(self, event):
        dock = getattr(self, 'ai_dock', None)
        return (dock is not None and dock.isFloating()
                and event.mimeData().hasFormat(AI_DOCK_RETURN_MIME))

    def _on_my_instances_page(self) -> bool:
        """当前是否在「我的实例」页(只有在这页,拖入文件才当作整合包安装)。"""
        return getattr(self, "_my_inst_tab_idx", 0) == self.main_tabs.currentIndex()

    def dragEnterEvent(self, e):
        if self._is_ai_dock_return_drag(e):
            self._show_ai_dock_drop_hint()
            e.acceptProposedAction()
            return
        if e.mimeData().hasUrls() and self._on_my_instances_page():
            e.acceptProposedAction()
            if hasattr(self, "_drop_overlay"):
                self._drop_overlay.setGeometry(self.rect())
                self._drop_overlay.raise_()
                self._drop_overlay.show()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if self._is_ai_dock_return_drag(e):
            e.acceptProposedAction()
            return
        if e.mimeData().hasUrls() and self._on_my_instances_page():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._hide_ai_dock_drop_hint()
        if hasattr(self, "_drop_overlay"):
            self._drop_overlay.hide()

    def dropEvent(self, e):
        self._hide_ai_dock_drop_hint()
        if self._is_ai_dock_return_drag(e):
            self._expand_ai()
            e.setDropAction(Qt.DropAction.MoveAction)
            e.accept()
            return
        if hasattr(self, "_drop_overlay"):
            self._drop_overlay.hide()
        if e.mimeData().hasUrls() and self._on_my_instances_page():
            folders = []
            for u in e.mimeData().urls():
                path = u.toLocalFile()
                if u.isLocalFile() and os.path.isdir(path):
                    folders.append(path)
                elif u.isLocalFile() and path:
                    self.install_modpack_from_path(path)
            if folders:
                enabled = getattr(getattr(self, 'skill_mgr', None), 'is_enabled',
                                  lambda _name: False)('smart_import') is True
                if enabled:
                    for folder in list(dict.fromkeys(folders)):
                        self.install_modpack_from_path(folder)
                else:
                    from launcher_app.resources.folder_instance_import import start_import
                    start_import(self, list(dict.fromkeys(folders)))
            e.setDropAction(Qt.DropAction.CopyAction)
            e.accept()
        else:
            e.ignore()   # 其它页面:不当作整合包,交由该页控件处理(如实例详情列表拷入文件夹)

    def install_modpack_from_path(self, path: str, *, safety_checked=False):
        return self._pack_imports().import_archive(path, safety_checked=safety_checked, classic=False)

    def _place_download_ball(self):
        """状态球在内容区右下角；手动拖动后按相对位置随窗口缩放。"""
        if not hasattr(self, "dl_indicator"):
            return
        if self.dl_indicator._dragging is not None:
            return
        central = self._background
        if central is None or central.width() <= 0 or central.height() <= 0:
            return
        margin = 12
        width = max(0, central.width() - self.dl_indicator.width())
        height = max(0, central.height() - self.dl_indicator.height())
        relative = self.dl_indicator._relative_position
        if relative is None:
            x, y = max(0, width - margin), max(0, height - margin)
        else:
            x, y = round(width * relative[0]), round(height * relative[1])
        self.dl_indicator.move(x, y)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if getattr(self, '_ai_transition', None) is not None:
            top = self.title_dock.height() if hasattr(self, 'title_dock') else 36
            self._ai_transition.setGeometry(0, top, self.width(), max(0, self.height() - top))
        # QMainWindow 先收到尺寸事件，中央区和 dock 随后才完成布局。
        # 在布局落定后一起重算 mask，否则右侧仍被旧宽度裁掉。
        QTimer.singleShot(0, self._refresh_central_geometry)
        self._position_resize_handles()

    def eventFilter(self, watched, event):
        central = getattr(self, '_background', None)
        dock = getattr(self, 'ai_dock', None)
        resized = event.type() == QEvent.Type.Resize
        moved_while_docked = (watched is dock and event.type() == QEvent.Type.Move
                              and not dock.isFloating())
        focus_sidebar = getattr(self, 'ai_focus_sidebar', None)
        if (watched is central or watched is dock or watched is focus_sidebar) and (resized or moved_while_docked):
            # Dock 拖宽/浮出只改变子控件，不一定触发主窗口 resizeEvent。
            # 两者的输入 mask 必须在新几何下同步，否则旧宽度外无法交互。
            QTimer.singleShot(0, self._refresh_central_geometry)
        return super().eventFilter(watched, event)

    def _refresh_central_geometry(self):
        if not hasattr(self, '_background'):
            return
        self._update_window_shape()
        self._place_download_ball()
        if getattr(self, '_wallpaper_source', None) is not None:
            self._recompute_wallpaper()

    def paintEvent(self, event):
        # Window masks are not guaranteed to clip visible pixels on every
        # compositor. Clear corners, then paint an antialiased background.
        super().paintEvent(event)
        if sys.platform.startswith(('linux', 'win')):
            from launcher_app.ui.ui_style import current_color
            painter = QPainter(self)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if self.isMaximized() or self.isFullScreen():
                painter.fillRect(self.rect(), QColor(current_color('bg1')))
            else:
                path = QPainterPath()
                path.addRoundedRect(QRectF(self.rect()), 14, 14)
                painter.fillPath(path, QColor(current_color('bg1')))
            painter.end()

    def _update_window_shape(self):
        """Clip frameless Windows/Linux corners without changing resize edges."""
        if not sys.platform.startswith(('linux', 'win')):
            return
        if self.isMaximized() or self.isFullScreen():
            self.clearMask()
            self._mask_outer_children(None)
            return
        width, height, radius = self.width(), self.height(), 14
        if width < 2 * radius or height < 2 * radius:
            return
        region = QRegion(0, radius, width, height - 2 * radius)
        region |= QRegion(radius, 0, width - 2 * radius, height)
        for x in (0, width - 2 * radius):
            for y in (0, height - 2 * radius):
                region |= QRegion(x, y, 2 * radius, 2 * radius,
                                  QRegion.RegionType.Ellipse)
        self.setMask(region)
        self._mask_outer_children(region)

    def _mask_outer_children(self, outer_region):
        """Clip child backgrounds too; the root mask may not clip their pixels."""
        children = (getattr(self, 'title_dock', None), self.centralWidget(),
                    getattr(self, 'ai_dock', None), self.statusBar())
        for child in children:
            if child is None or (isinstance(child, QDockWidget) and child.isFloating()):
                continue
            if outer_region is None:
                child.clearMask()
                continue
            pos = child.mapTo(self, QPoint(0, 0))
            clipped = outer_region.translated(-pos.x(), -pos.y()) & QRegion(child.rect())
            child.setMask(clipped)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._update_window_shape()
            self._position_resize_handles()

    def _scan_running_servers(self):
        if self._server_running_task is not None and self._server_running_task.is_running:
            return
        from launcher_app.servers.server_packs import list_servers
        from launcher_app.servers.server_host_client import managed_status
        game_root = paths.GAME_DIR
        def scan(task):
            from launcher_app.core.task_context import checkpoint
            running = []
            seen = set()
            for server in list_servers(game_root):
                checkpoint()
                state = managed_status(server['path'])
                if state and state.get('running') and state.get('pid') not in seen:
                    seen.add(state.get('pid'))
                    running.append((server['name'], state.get('pid')))
            return running
        task = BackgroundTask(scan, self)
        self._server_running_task = task
        task.succeeded.connect(self._apply_running_servers)
        task.start()

    def _apply_running_servers(self, running):
        from launcher_app.ui.ui_style import success_color, muted_color
        label = self._server_running_label
        if running:
            text = ('已启动服务端:' + running[0][0] if len(running) == 1
                    else f'已启动服务端:{len(running)}个')
            label.setText(label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, 160))
            label.setToolTip(t('运行中的服务端:\n') + '\n'.join(
                f'{name} · PID {pid}' for name, pid in running))
            label.setStyleSheet(f'color: {success_color()}; font-weight: bold;')
        else:
            label.setText(t('尚未启动服务端'))
            label.setToolTip(t('显示由 AMCL 托管的运行中服务端'))
            label.setStyleSheet(f'color: {muted_color()};')

    def _scan_running_games(self):
        self._update_running_label()
        self._scan_running_servers()
        if self._running_scan_task is not None and self._running_scan_task.is_running:
            return
        from launcher_app.instances.instances import scan_instances, detect_running_clients
        directories = {row['id']: self.game_dir_for(row['id']) for row in scan_instances()}
        task = BackgroundTask(lambda current: detect_running_clients(directories), self)
        self._running_scan_task = task
        task.succeeded.connect(self._apply_running_games)
        task.start()

    def _apply_running_games(self, clients):
        self.running_games.set_detected(clients)
        self._update_running_label()

    def _update_running_label(self):
        """刷新顶部的"已有 x 个运行中的实例"(悬停显示具体实例)"""
        from launcher_app.ui.ui_style import muted_color, success_color
        live = self.running_games.live(self.game_sessions.running_processes)
        self._running_instances = set(live.values()) - {''}
        n = len(live)
        if n:
            running_text = f"已启动实例:{n}个" if n > 1 else "已启动实例：" + next(iter(live.values()))
            self._running_label.setText(
                self._running_label.fontMetrics().elidedText(
                    running_text, Qt.TextElideMode.ElideRight, 160))
            self._running_label.setToolTip(t('运行中的实例:\n') + "\n".join(
                f"{name}（PID {pid}）" for pid, name in live.items()))
            self._running_label.setStyleSheet(f"color: {success_color()}; font-weight: bold;")
        else:
            self._running_label.setText(t('尚未启动游戏'))
            self._running_label.setToolTip(t('启动实例后这里会显示运行中的游戏'))
            self._running_label.setStyleSheet(f"color: {muted_color()};")
        QTimer.singleShot(0, self.title_bar._place_center_widget)

    def _busy_download(self, busy: bool):
        self.download_tab.set_busy(busy)
        self.launch_btn.setEnabled(not busy)

    def _set_progress(self, done: int, total: int):
        """通用进度回调(实例下载 / Java 下载共用):显示在左下角圆环指示器上"""
        self.dl_indicator.set_progress(done, total)
        if done < total:
            self.dl_indicator.set_completed(False)
        self.dl_indicator.setToolTip(t('下载中,点击查看详情'))
        self.dl_indicator.show()

    def report_download_progress(self, title: str, status: str, done: int, total: int):
        """通用下载进度入口(本地模型 / AI 发起的 Mod 下载共用):写进下载日志 + 更新左下角圆环指示器。
        title 用作圆环 tooltip/详情里的标识;status 为状态消息(可为空)。这样点圆环 → 下载详情也能看到。"""
        status = redact_text(status, self.settings)
        if status:
            self._dl_log.append(redact_text(status, self.settings))
        self._dl_progress = (done, total)
        self.dl_indicator.set_progress(done, total)
        if done < total:
            self.dl_indicator.set_completed(False)
        if status and "失败" in status:
            self.dl_indicator.setToolTip(t('{v0}失败,点击查看详情').format(v0=(title)))
        elif status and ("完成" in status or "已就绪" in status.lower()):
            self.dl_indicator.setToolTip(t('{v0}完成,点击查看详情').format(v0=(title)))
        else:
            self.dl_indicator.setToolTip(t('正在下载{v0},点击查看详情').format(v0=(title)))
        self.dl_indicator.show()

    def report_download_done(self, title: str, ok: bool, msg: str):
        """通用下载结束入口:写日志 + 满环 + 收起(2s)。"""
        msg = redact_text(msg, self.settings)
        self._dl_log.append(msg)
        self._dl_progress = (1, 1)
        self.dl_indicator.set_progress(1, 1)
        self.dl_indicator.set_completed(ok)
        self.dl_indicator.setToolTip(f"{title}" + (t('完成,点击查看详情') if ok else t('失败,点击查看详情')))
        self.dl_indicator.set_failed(not ok)
        if not ok:
            advice = failure_advice(msg)
            self._dl_log.append(advice)
            self.dl_indicator.setToolTip(t('{v0}失败\n{v1}\n点击查看详情').format(v0=(title), v1=(advice)))
        self.dl_indicator.show()

    def model_download_progress(self, status: str, done: int, total: int):
        """本地模型下载进度回调:写进下载日志 + 更新左下角圆环指示器,
        这样点圆环 → 下载详情也能看到模型下载进度(不只是主界面圆环动)。"""
        self.report_download_progress("本地模型", status, done, total)

    def model_download_done(self, ok: bool, msg: str):
        """本地模型下载结束:写日志 + 满环 + 收起(2s)。"""
        self.report_download_done("本地模型", ok, msg)

    def game_dir_for(self, version_id: str) -> str:
        """PCL2 风格:versions/<版本ID>/ 就是该版本的实例(游戏目录)。
        版本隔离关闭时所有版本共用一个目录。"""
        return self.instance_installer.game_dir_for(version_id)

    def load_version_data(self, v: dict) -> dict:
        """取版本的完整数据:本地的(Mod 版本)从磁盘读并解析继承链,
        原版从 Mojang 清单拉取。"""
        return self.game_launcher.load_version_data(v)

    # ---- 工具函数:把版本 v 作为叶子节点加进树,并藏好数据 ----
    def _add_version(self, parent, v):
        item = QTreeWidgetItem([f"{v['id']}  ({v['type']})"])
        item.setData(0, Qt.ItemDataRole.UserRole, v)  # 版本数据藏在第 0 列
        parent.addChild(item)

    def load_versions(self):
        """后台拉取版本清单，主窗口先显示并保持可操作。"""
        self.statusBar().showMessage("正在获取版本列表...")
        self.version_manifest.refresh()

    def _on_version_manifest_failed(self, error: str):
        """离线启动后持续低频重试，网络恢复时自动补上版本列表。"""
        delay = self._manifest_retry_delay_ms
        self.statusBar().showMessage(
            f"暂时无法联网，恢复网络后会自动刷新版本列表（{delay // 1000} 秒后重试）")
        if not self._manifest_retry_timer.isActive():
            self._manifest_retry_timer.start(delay)
        self._manifest_retry_delay_ms = min(delay * 2, 30000)

    def _apply_version_manifest(self, manifest: dict):
        """只在 GUI 线程更新版本相关控件。"""
        if not isinstance(manifest, dict) or not manifest.get("latest"):
            self.statusBar().showMessage("版本列表格式无效")
            return

        self._manifest_retry_timer.stop()
        self._manifest_retry_delay_ms = 3000

        self.resource_center.set_latest_versions(manifest['latest']['release'],
                                                 manifest['latest']['snapshot'])
        self.download_tab._fill_tree(manifest)
        guide = getattr(self, '_guide_driver', None)
        if guide is not None:
            QTimer.singleShot(0, guide.refresh_current_target)

        # 填充各资源浏览器的全局游戏版本树(按大版本分组)
        for br in self.resource_center.browsers.values():
            br.populate_game_versions(manifest)

        self.statusBar().showMessage(f"加载完成(最新正式版 {manifest['latest']['release']})")

    def on_select_version(self, current, _previous):
        """选中某个版本时,拉取并显示它的详细信息(分组节点没有数据,忽略)"""
        if current is None:
            return
        v = current.data(0, Qt.ItemDataRole.UserRole)
        if v is None:
            return
        self.selected_version = v  # 记住,供"开始下载实例"按钮使用
        self.statusBar().showMessage(f"选中: {v['id']} ({v['type']})")

    def install_selected(self):
        """安装当前选中版本(等价于向导里选"原版 + 无加载器")"""
        v = self.selected_version
        if v is None or v.get("local"):
            self.statusBar().showMessage("请先选中一个原版版本")
            return
        self.statusBar().showMessage(f"正在获取 {v['id']} 的安装信息...")
        try:
            d = fetch_version_detail(v["url"])
        except Exception as e:
            self.statusBar().showMessage(f"获取版本信息失败: {e}")
            return
        if self._install_detail(d):
            self.statusBar().showMessage(f"安装完成:{d['id']} 所有文件已就绪 ✅")

    def install_version(self, version_id: str, status_cb=None, progress_cb=None,
                        repository_only: bool = False) -> bool:
        """兼容旧调用；安装业务由 InstanceInstallService 处理。"""
        return self.instance_installer.install_version(
            version_id,
            status_cb or self.statusBar().showMessage,
            progress_cb or self._set_progress,
            repository_only,
        )

    def _install_detail(self, d: dict, status_cb=None, progress_cb=None,
                        repository_only: bool = False) -> bool:
        """兼容旧调用；安装已获取的版本详情。"""
        return self.instance_installer.install_detail(
            d,
            status_cb or self.statusBar().showMessage,
            progress_cb or self._set_progress,
            repository_only,
        )

    def _start_launch_button_animation(self):
        """Keep launch progress visible inside the primary button."""
        from launcher_app.ui.ui_anim import is_animations_enabled
        if not hasattr(self, '_launch_button_timer'):
            self._launch_button_timer = QTimer(self)
            self._launch_button_timer.setInterval(180)
            self._launch_button_timer.timeout.connect(self._advance_launch_button_animation)
        self._launch_button_generation = getattr(self, '_launch_button_generation', 0) + 1
        self._launch_button_frame = 0
        self.launch_btn.setText(t('启动中…'))
        self.ai_focus_sidebar.set_launch_state("starting")
        if is_animations_enabled():
            self._launch_button_timer.start()

    def _advance_launch_button_animation(self):
        self._launch_button_frame = (self._launch_button_frame + 1) % 4
        if self.home_panel.tabs.currentIndex() != self.home_panel._server_tab_index:
            self.launch_btn.setText(t('启动中') + '·' * self._launch_button_frame)

    def _stop_launch_button_animation(self):
        self._launch_button_generation = getattr(self, '_launch_button_generation', 0) + 1
        timer = getattr(self, '_launch_button_timer', None)
        if timer is not None:
            timer.stop()
        if self.home_panel.tabs.currentIndex() != self.home_panel._server_tab_index:
            self.home_panel._update_client_launch_target(self.home_panel.current_instance())
        self.ai_focus_sidebar.set_launch_state("idle")

    def _show_launch_button_success(self):
        timer = getattr(self, '_launch_button_timer', None)
        if timer is not None:
            timer.stop()
        self._launch_button_generation = getattr(self, '_launch_button_generation', 0) + 1
        generation = self._launch_button_generation
        if self.home_panel.tabs.currentIndex() != self.home_panel._server_tab_index:
            self.launch_btn.setText(t('✓ 启动成功'))
        self.ai_focus_sidebar.set_launch_state("success")
        QTimer.singleShot(1800, lambda: self._stop_launch_button_animation()
                          if self._launch_button_generation == generation else None)

    def launch_selected(self, _processes_checked=False):
        """启动当前选中版本:准备 Java → 拼命令 → 拉起进程 → 日志实时显示"""
        v = self.selected_version
        if v is None:
            self.statusBar().showMessage("请先在列表里选中一个版本")
            return
        preparation = getattr(self, '_launch_preparation', None)
        if ((self._launch_task is not None and self._launch_task.is_running)
                or (preparation is not None and preparation.busy) or self.download_tasks.is_running):
            self.statusBar().showMessage("正在准备或安装，等这一小步完成再启动吧")
            return

        if not _processes_checked:
            from launcher_app.instances.instances import scan_instances, detect_running_clients
            directories = {row['id']: self.game_dir_for(row['id']) for row in scan_instances()}
            task = BackgroundTask(lambda current: detect_running_clients(directories), self)
            self._launch_task = task
            self.launch_btn.setEnabled(False)
            self.statusBar().showMessage('正在检测已启动的游戏…')

            def detected(clients):
                self._launch_task = None
                self.launch_btn.setEnabled(True)
                self._apply_running_games(clients)
                self.launch_selected(_processes_checked=True)

            task.succeeded.connect(detected)
            task.failed.connect(self._on_launch_prepare_failed)
            task.start()
            return

        self._update_running_label()
        if self._running_instances:
            if action_question(self, t('启动另一个实例'),
                    t('已有游戏正在运行，是否继续启动「{v0}」？\n多开会增加内存占用，同一实例共用存档时请勿同时进入同一个世界。').format(v0=(v['id'])),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
                return

        self.statusBar().showMessage(f"正在获取 {v['id']} 的启动信息...")

        from launcher_app.instances.launch_preparation import LaunchRequest
        from launcher_app.runtime.launch_preparation_controller import LaunchPreparationController
        controller = getattr(self, '_launch_preparation', None)
        if controller is None:
            controller = LaunchPreparationController(lambda: paths.GAME_DIR, self)
            controller.status.connect(self._on_download_status)
            controller.progress.connect(self._on_download_progress)
            controller.failed.connect(self._on_launch_prepare_failed)
            controller.cancelled.connect(self._on_download_cancelled)
            controller.prepared.connect(self._start_prepared_game)
            self._launch_preparation = controller
        request = LaunchRequest.capture(v, load_settings(), paths.GAME_DIR, paths.RUNTIME_DIR)
        task = controller.create_task(request)
        self._launch_task = task
        self.launch_btn.setEnabled(False)
        self._start_launch_button_animation()
        self._dl_log = []
        self._dl_progress = (0, 1)
        self.dl_indicator.set_progress(0, 1)
        self.dl_indicator.setToolTip(t('正在准备启动，点击查看详情'))
        if hasattr(self, 'task_center'):
            self._ensure_dl_overlay(create_download=True, task_title='启动准备')
            self.task_center.begin_task('启动准备', task_id='download', cancel=self._cancel_current_task)
        self.dl_indicator.show()
        task.start()

    def _on_launch_prepare_failed(self, error):
        if hasattr(self, 'task_center'):
            self.task_center.finish_task('download', 'failed', redact_text(error, self.settings))
        self._stop_launch_button_animation()
        self.ai_focus_sidebar.set_launch_state("failed")
        self.launch_btn.setEnabled(True)
        self.dl_indicator.set_failed(True)
        self.dl_indicator.setToolTip(t('启动准备失败，点击查看状态与日志'))
        task_warning(self, t('启动准备没完成'), redact_text(error, self.settings))

    def _start_prepared_game(self, plan, v):
        # 准备阶段可能刷新了正版令牌；下次启动须读取刚保存的凭证。
        self.settings = load_settings()
        if self._memory_actions().offer(plan, v, self._start_game_after_memory):
            return
        self._start_game_after_memory(plan, v)

    def _local_ai_process(self):
        return getattr(getattr(self.ai_dock, '_local_engine', None), 'proc', None)

    def _memory_actions(self):
        controller = getattr(self, '_memory_launch_controller', None)
        if controller is None:
            from settings import update_setting
            from launcher_app.ui.memory_launch_card import MemoryLaunchController, MemoryLaunchPorts
            controller = MemoryLaunchController(self, MemoryLaunchPorts(
                read_settings=load_settings, write_setting=update_setting,
                current_process=lambda: self.game_process, local_ai_process=self._local_ai_process,
                stop_local_ai=self.ai_dock.stop_local_engine,
                history_dir=lambda instance: os.path.join(paths.GAME_DIR, 'versions', instance)))
            self._memory_launch_controller = controller
        return controller

    def _start_game_after_memory(self, plan, v, exit_after=False):
        self._start_launch_button_animation()
        d = plan.detail
        game_dir = plan.game_dir
        java_exe = plan.java_exe
        cmd = plan.command

        # 3) 展开日志面板,显示要执行的命令(方便你理解"启动"到底是什么)
        # 3) 清空并写入要执行的命令到游戏日志(在「实例详情 → 游戏日志」里看)
        self.log_view.clear()
        self.log_view.appendPlainText(redact_text("> " + " ".join(cmd), self.settings))
        # 首次运行提示:还没生成过完整游戏目录(saves/配置)时告诉用户
        if plan.first_run:
            self.statusBar().showMessage(
                f"首次运行 {d['id']}:将生成完整游戏目录(存档/配置在 {game_dir})")
        else:
            self.statusBar().showMessage("游戏启动中...")
        self.launch_btn.setEnabled(False)

        self._game_integrations().before_launch(self.settings)

        try:
            launched = self._game_runtime().start(plan, v, paths.GAME_DIR, independent=exit_after)
            self.game_process = launched.process
        except Exception as e:
            self._stop_launch_button_animation()
            self.ai_focus_sidebar.set_launch_state("failed")
            self.statusBar().showMessage(f"启动失败: {e}")
            self.dl_indicator.set_failed(True)
            self.dl_indicator.setToolTip(t('启动失败，点击查看状态与日志'))
            if hasattr(self, 'task_center'):
                self.task_center.finish_task('download', 'failed', redact_text(str(e), self.settings))
            self.launch_btn.setEnabled(True)
            return

        self._show_launch_button_success()
        self.launch_btn.setEnabled(True)
        self.dl_indicator.set_completed(True)
        self.dl_indicator.setToolTip(t('游戏已启动，点击查看状态与日志'))
        if hasattr(self, 'task_center'):
            self.task_center.finish_task('download', message='游戏已启动')

        self._game_runtime().record_started(self.settings)
        self._running_instances.add(launched.runtime_id)
        self._update_running_label()
        from copy import deepcopy
        self._game_integrations().started(
            self.game_process, launched.instance_id, deepcopy(self.settings), launched.game_root, self.ai_context())

        if exit_after:
            self._memory_actions().exit_when_ready(self.game_process)

    def _on_game_log_line(self, line: str):
        line = redact_text(line, self.settings)
        self.log_view.appendPlainText(line)
        self._game_integrations().log(line)

    def _on_game_process_exited(self, code: int):
        self._stop_launch_button_animation()
        self.launch_btn.setEnabled(True)
        self.statusBar().showMessage(f"游戏进程已退出(退出码 {code})")
        current = self._game_runtime().current
        inst_id = current.instance_id if current is not None else None
        if inst_id:
            self._running_instances.discard(inst_id)
        self._update_running_label()
        self._scan_running_games()
        self._game_integrations().stopped(code, next(iter(self.game_sessions.running_processes), None))
        if code not in (0, None):
            self.dl_indicator.set_failed(True)
            self.dl_indicator.setToolTip(t('游戏异常退出（{v0}），点击查看日志').format(v0=(code)))
            self._auto_debug(code)
        elif self._detect_log_crash():
            self.dl_indicator.set_failed(True)
            self.dl_indicator.setToolTip(t('发现崩溃报告，点击查看日志'))
            self._auto_debug(0)

    def _game_runtime(self):
        runtime = getattr(self, '_runtime_game', None)
        if runtime is None:
            from settings import update_setting
            from launcher_app.runtime.game_runtime import GameRuntime
            runtime = GameRuntime(self.game_sessions, self.running_games,
                                  lambda instance: update_setting('last_played_instance', instance))
            self._runtime_game = runtime
        return runtime

    def _game_integrations(self):
        integration = getattr(self, '_game_integration', None)
        if integration is None:
            from launcher_app.ai.game_integration import GameIntegration, GameIntegrationPorts
            integration = GameIntegration(GameIntegrationPorts(
                stop_local_engine=self.ai_dock.stop_local_engine,
                game_running=self.ai_dock.set_game_running, game_stopped=self.ai_dock.set_game_stopped,
                skill_started=self.skill_mgr.on_game_start, skill_stopped=self.skill_mgr.on_game_stop,
                skill_log=self.skill_mgr.on_game_log,
                show_status=lambda text: self.statusBar().showMessage(text)))
            self._game_integration = integration
        return integration

    def _start_in_game_ai(self, instance_id: str):
        from copy import deepcopy
        self._game_integrations().start_bridge(instance_id, deepcopy(self.settings), paths.GAME_DIR, self.ai_context())

    def _stop_in_game_ai(self):
        integration = getattr(self, '_game_integration', None)
        if integration is not None:
            integration.stop_bridge()

    def _toggle_log(self, checked: bool):
        """打开共用详情标签，并切到当前实例的游戏日志。"""
        if hasattr(self, "instance_details") and self.instance_details.shell is not None:
            inst = self.home_panel.current_instance()
            if inst is None:
                return
            self._show_instance_details(inst)
            self.instance_details.shell.switch_by_label("游戏日志")

    # ---- 自动 debug:游戏异常退出时收集日志,让 AI 分析 ----
    def _detect_log_crash(self) -> bool:
        """很多崩溃(如 F3+C 调试崩溃、Mod 崩溃)退出码是 0,但留下了崩溃报告或日志特征。
        这里只判断"本次运行是否发生崩溃",不弹窗。"""
        return self._game_runtime().has_crash()

    def _auto_debug(self, code: int):
        """游戏异常退出(退出码非 0 或检测到本次崩溃):自动抓最新日志 + 崩溃报告,问用户是否让 AI 分析"""
        runtime = self._game_runtime()
        if runtime.current is None:
            return
        msg = runtime.crash_report(code)
        preview = msg[:400] + ("…" if len(msg) > 400 else "")
        if QMessageBox.question(
                self, t('游戏异常退出'),
                t('{v0}\n\n要让 AI 助手分析原因并给出解决办法吗?').format(v0=(preview)), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes) == QMessageBox.StandardButton.Yes:
            self.ai_dock.ask(f"我的游戏异常退出了(退出码 {code}),帮我分析原因和解决办法:\n{msg}")

    def create_instance(self, version: str, loader_key, modrinth_loader,
                        shader: bool, optimize: bool,
                        loader_version: str | None = None,
                        shader_version: str | None = None,
                        optimize_versions: dict | None = None,
                        fabric_api_version: str | None = None,
                        status_cb=None, progress_cb=None):
        """兼容窗口和插件旧调用；实际流程由安装服务执行。"""
        return self.instance_installer.create_instance(
            version, loader_key, modrinth_loader, shader, optimize,
            loader_version=loader_version,
            shader_version=shader_version,
            optimize_versions=optimize_versions,
            fabric_api_version=fabric_api_version,
            status_cb=status_cb or self.statusBar().showMessage,
            progress_cb=progress_cb or self._set_progress,
        )

    def _install_mod(self, slug: str, game_version: str, loader: str,
                     mods_dir: str, kind: str, version_number: str | None = None,
                     status_cb=None, progress_cb=None):
        """兼容旧调用；下载一个可选 Mod。"""
        return self.instance_installer.install_mod(
            slug, game_version, loader, mods_dir, kind, version_number,
            status_cb or self.statusBar().showMessage, progress_cb,
        )

    # ---- 下载 Mod 选项卡 ----
    def refresh_instances(self):
        """扫描实例,刷新:我的版本列表 + 下载 Mod 卡片 + versions 里的实例记录"""
        from launcher_app.instances.instance_catalog_service import fingerprint
        scanned_fingerprint = fingerprint(paths.GAME_DIR)
        shown = self.instance_catalog.refresh()

        # 1) 我的版本列表(带封面)
        # 保留当前选中:versions/ 目录变动会触发防抖自动刷新(500ms),clear() 会把当前项
        # 清成 None → currentItemChanged(None) → 详情页被"自动取消"。这里 blockSignals
        # 重建列表、按 id 复原选中,最后统一同步一次 UI(恢复选中 / 实例真的没了→None)。
        _cur_item = self.instance_list.currentItem()
        _cur_id = (_cur_item.data(Qt.ItemDataRole.UserRole) or {}).get("id") if _cur_item else None
        # 首次打开首页没有当前选中项时，优先恢复上次成功启动的实例；刷新中
        # 用户刚手动选过的项优先级更高，避免列表自动刷新抢走选择。
        _preferred_id = _cur_id or str(self.settings.get("last_played_instance") or "")
        self.instance_list.blockSignals(True)
        try:
            self.instance_list.clear()
            for inst in shown:
                item = QListWidgetItem(inst["label"])
                item.setData(Qt.ItemDataRole.UserRole, inst)
                icon = self._instance_icon(inst["id"])
                if icon:
                    item.setIcon(icon)
                self.instance_list.addItem(item)
            _restore = None
            if _preferred_id:
                for _i in range(self.instance_list.count()):
                    _d = self.instance_list.item(_i).data(Qt.ItemDataRole.UserRole)
                    if _d and _d.get("id") == _preferred_id:
                        _restore = self.instance_list.item(_i)
                        break
            if _restore is not None:
                self.instance_list.setCurrentItem(_restore)
        finally:
            self.instance_list.blockSignals(False)
        # 刷新后统一同步一次当前选择(复原的实例,或已消失→None)
        self.home_panel._on_selection_changed(self.instance_list.currentItem(), None)
        # 同步到首页面板(实例数量 + 当前选择态)
        self.home_panel.set_current_instances(shown)
        if getattr(self, '_ai_focus_mode', False):
            self.ai_focus_sidebar.refresh_from_home()

        # 3) 实例记录(实例清单备忘,可手动编辑补充)
        self.instance_catalog.write_record(shown)

        # 4) 资源中心的目标实例卡片(Mod/光影/数据包浏览器)
        self.resource_center.refresh_browser_instances(shown)
        self._instance_fingerprint = scanned_fingerprint
        self._watch_versions_dir()

    # ---- 实例目录文件变动 → 自动刷新实例列表 ----
    def _setup_instance_watcher(self):
        """监听 versions/ 目录:子文件夹新增/删除 → 防抖后刷新「实例(共x个)」列表。"""
        self._inst_watcher = None
        self._inst_refresh_timer = QTimer(self)
        self._inst_refresh_timer.setSingleShot(True)
        self._inst_refresh_timer.setInterval(500)   # 防抖:多次文件变动合并成一次刷新
        self._inst_refresh_timer.timeout.connect(self._on_instance_dir_debounced)
        self._inst_poll_timer = QTimer(self)
        self._inst_poll_timer.setInterval(3000)
        self._inst_poll_timer.timeout.connect(self._on_instance_dir_debounced)
        self._inst_poll_timer.start()
        try:
            self._inst_watcher = QFileSystemWatcher(self)
            self._inst_watcher.directoryChanged.connect(self._on_instance_dir_changed)
            self._watch_versions_dir()
        except Exception as e:
            self._inst_watcher = None
            self._log_feedback(f"实例目录监听初始化失败:{e}", "警告")

    def _watch_versions_dir(self):
        """(重新)把监听指向当前游戏目录的 versions/。游戏目录变更时也调用。"""
        if getattr(self, '_inst_watcher', None) is None:
            return
        try:
            dirs = self._inst_watcher.directories()
            if dirs:
                self._inst_watcher.removePaths(dirs)
            versions_dir = os.path.join(paths.GAME_DIR, "versions")
            if os.path.isdir(paths.GAME_DIR):
                self._inst_watcher.addPath(paths.GAME_DIR)
            if os.path.isdir(versions_dir):
                self._inst_watcher.addPath(versions_dir)
                with os.scandir(versions_dir) as entries:
                    children = [entry.path for entry in entries
                                if entry.is_dir() and not entry.name.startswith('_')]
                if children:
                    self._inst_watcher.addPaths(children)
        except Exception as e:
            self._log_feedback(f"监听 versions/{os.path.basename(paths.GAME_DIR)} 失败:{e}", "警告")

    def _on_instance_dir_changed(self, _path: str):
        """versions/ 目录有变动:重启防抖计时器(合并连续变动)。"""
        # 正在游戏内/下载等忙时也允许,但防抖+避免 TidyBase 迁移又触发自身
        self._inst_refresh_timer.start()

    def _on_instance_dir_debounced(self):
        """防抖到期:确实有变动才刷新。避免 refresh→tidy→目录变动→refresh 死循环。"""
        try:
            from launcher_app.instances.instance_catalog_service import fingerprint
            if fingerprint(paths.GAME_DIR) == getattr(self, '_instance_fingerprint', None):
                return
            self.refresh_instances()
        except Exception as e:
            self._log_feedback(f"实例目录变动刷新失败:{e}", "警告")

    def _resource_downloads(self):
        controller = getattr(self, '_resource_download_controller', None)
        if controller is None:
            from launcher_app.ui.resource_download_controller import ResourceDownloadController
            controller = ResourceDownloadController(
                parent=self, submit=self._run_download,
                show_status=lambda text: self.statusBar().showMessage(text),
                game_root=lambda: paths.GAME_DIR)
            self._resource_download_controller = controller
        return controller

    def _resource_download(self, hit, version, inst, target_dir, sub_dir):
        return self._resource_downloads().download(hit, version, inst, target_dir, sub_dir)

    def _resource_download_modpack(self, hit, version):
        return self._resource_downloads().download_pack(hit, version)

    def _tidy_base_versions(self):
        """兼容旧调用；整理逻辑由实例目录服务负责。"""
        self.instance_catalog.tidy_base_versions()

    @staticmethod
    def _instance_icon(instance_id: str):
        """Prefer a modpack/launcher icon, then JSON favicon, then fallback."""
        instance_dir = os.path.join(paths.GAME_DIR, "versions", instance_id)
        for relative in ("icon.png", "instance.png", "pack.png", "logo.png",
                         os.path.join("PCL", "Logo.png"),
                         os.path.join(".minecraft", "icon.png"),
                         os.path.join(".minecraft", "instance.png")):
            image_path = os.path.join(instance_dir, relative)
            try:
                if (not os.path.isfile(image_path) or os.path.islink(image_path)
                        or os.path.getsize(image_path) > 5 * 1024 * 1024):
                    continue
                reader = QImageReader(image_path)
                dimensions = reader.size()
                if (dimensions.width() <= 0 or dimensions.height() <= 0
                        or dimensions.width() > 4096 or dimensions.height() > 4096):
                    continue
                reader.setScaledSize(dimensions.scaled(
                    QSize(64, 64), Qt.AspectRatioMode.KeepAspectRatio))
                image = reader.read()
                if not image.isNull():
                    return QIcon(QPixmap.fromImage(image))
            except (OSError, TypeError, ValueError):
                continue
        try:
            vjson = os.path.join(instance_dir, instance_id + ".json")
            with open(vjson, encoding="utf-8") as f:
                data = json.load(f)
            favicon = data.get("favicon")
            if favicon:
                pixmap = QPixmap()
                if pixmap.loadFromData(base64.b64decode(favicon)):
                    return QIcon(pixmap)
        except Exception:
            pass
        return MainWindow._placeholder_icon(instance_id)

    @staticmethod
    def _placeholder_icon(instance_id: str):
        """生成占位封面:按名字哈希选颜色,画上名字前两个字符"""
        palette = ["#5B8DEF", "#6BCB77", "#FF6B6B", "#FFD93D", "#B980F0",
                   "#4ECDC4", "#F78FB3", "#82B74B", "#E07B54", "#3E7CB1"]
        idx = sum(ord(c) for c in instance_id) % len(palette)
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(palette[idx]))
        painter = QPainter(pixmap)
        painter.setPen(QColor("white"))
        font = painter.font()
        font.setPointSize(20)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, instance_id[:2])
        painter.end()
        return QIcon(pixmap)

    def write_cheat_sheet(self, instances: list):
        """兼容旧调用；写入实例记录并保留用户备注。"""
        self.instance_catalog.write_record(instances)

    def launch_selected_instance(self, inst=None):
        """启动"我的版本"里选中的实例(双击或按钮)"""
        if inst is None:
            item = self.instance_list.currentItem()
            inst = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(inst, dict) or not inst.get('id'):
            self.statusBar().showMessage("请先选一个实例(双击也可以直接启动)")
            return
        self.selected_version = {**inst, "local": True, "type": "instance"}
        self.statusBar().showMessage(f"启动实例: {inst['id']}")
        self.launch_selected()

    # ---- 右键菜单 ----
    def _instance_menu(self, pos):
        """实例右键:一键配置 / 重命名 / 备份 / 打开目录 / 删除实例"""
        item = self.instance_list.itemAt(pos)
        if item is None:
            return
        inst = item.data(Qt.ItemDataRole.UserRole)
        self._show_instance_menu(inst, self.instance_list.mapToGlobal(pos))

    def _show_instance_menu(self, inst, global_pos):
        """常规模式与 AI 模式共用同一份实例操作菜单。"""
        if not inst or not inst.get('id'):
            return
        menu = QMenu(self)
        from launcher_app.ui.ui_style import popup_menu_style
        menu.setStyleSheet(popup_menu_style())
        config_menu = menu.addMenu("一键配置")
        config_menu.addAction(t('Bridge Mod（推荐）…'), lambda: self._one_click_bridge_for(inst))
        rcon_menu_item = config_menu.addAction(t('RCON（临时方案）…'), lambda: self._one_click_rcon_for(inst))
        rcon_menu_item.setToolTip(t('临时方案:需要 Lan Server Properties + 进世界按 ESC → 对局域网开放'))
        # 联机 mod 一键配置:按实例版本+加载器判断支持才显示(不支持不出现)
        self._add_online_mod_menu_items(config_menu, inst)
        menu.addAction(t('重命名实例…'), lambda: self._rename_instance(inst))
        menu.addAction(t('备份实例'), lambda: self.backup_current_instance(inst))
        menu.addAction(t('打开实例目录'), lambda: open_path(self.game_dir_for(inst["id"])))
        menu.addSeparator()
        menu.addAction(t('删除实例…'), lambda: self._delete_instance(inst))
        menu.exec(global_pos)

    def _current_instance(self):
        """「我的版本」当前选中的实例;没选中返回 None"""
        item = self.instance_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _command_setup(self):
        controller = getattr(self, '_command_setup_controller', None)
        if controller is None:
            from launcher_app.ui.command_setup_controller import CommandSetupController
            controller = CommandSetupController(
                parent=self, game_dir_for=self.game_dir_for, submit=self._run_download,
                show_status=self.statusBar().showMessage, clear_status=self.statusBar().clearMessage)
            self._command_setup_controller = controller
        return controller

    def _one_click_config_kind(self, kind: str):
        """「我的版本」首页「一键配置 ▾」按钮 → 按用户选择执行 bridge-mod / RCON / 自动。"""
        inst = self._current_instance()
        if inst is None:
            inline_notice(self, t('一键配置'), t('请先在「我的版本」里选中一个实例'))
            return
        if kind == "bridge":
            self._one_click_bridge_for(inst)
        elif kind == "rcon":
            self._one_click_rcon_for(inst)
        elif kind in ("essential", "e4mc"):
            self._one_click_online_mod_for(inst, kind)
        else:
            self._one_click_config_for(inst)

    def _one_click_config_current(self):
        """「我的版本」顶部:一键配置下拉菜单(未来扩展更多配置项)"""
        inst = self._current_instance()
        if inst is None:
            inline_notice(self, t('一键配置'), t('请先在「我的版本」里选中一个实例'))
            return
        self._one_click_config_for(inst)

    # ---- 一键配置:bridge-mod(正式方案,本地指令口) ----
    def _one_click_bridge_current(self):
        inst = self._current_instance()
        if inst is None:
            inline_notice(self, t('一键配置'), t('请先在「我的版本」里选中一个实例'))
            return
        self._one_click_bridge_for(inst)

    def _one_click_bridge_for(self, inst):
        return self._command_setup()._one_click_bridge_for(inst)

    def _check_bridge_async(self, inst, on_ready):
        return self._command_setup()._check_bridge_async(inst, on_ready)

    def _on_bridge_status_ready(self, inst, payload):
        return self._command_setup()._on_bridge_status_ready(inst, payload)

    # ---- 一键配置:RCON(临时方案,需要开局域网) ----
    def _one_click_rcon_current(self):
        inst = self._current_instance()
        if inst is None:
            inline_notice(self, t('一键配置'), t('请先在「我的版本」里选中一个实例'))
            return
        self._one_click_rcon_for(inst)

    def _one_click_rcon_for(self, inst):
        return self._command_setup()._one_click_rcon_for(inst)

    def _add_online_mod_menu_items(self, menu, inst):
        return self._command_setup()._add_online_mod_menu_items(menu, inst)

    def _one_click_online_mod_for(self, inst, slug):
        return self._command_setup()._one_click_online_mod_for(inst, slug)

    def _one_click_config_for(self, inst):
        return self._command_setup()._one_click_config_for(inst)

    def _on_config_auto_ready(self, inst, payload):
        return self._command_setup()._on_config_auto_ready(inst, payload)

    def _install_bridge_mod(self, inst):
        return self._command_setup()._install_bridge_mod(inst)

    def _install_lan_server_properties(self, inst):
        return self._command_setup()._install_lan_server_properties(inst)

    def open_instance_manager(self, inst):
        """打开共用详情标签中的客户端实例详情。"""
        if inst is not None:
            self._show_instance_details(inst)
        else:
            self._sync_details_tab()
            self.main_tabs.setCurrentIndex(self._details_tab_idx)

    def _on_instance_selected(self, inst):
        """同步 AI 目标；详情标签可见时同步当前客户端实例。"""
        if (hasattr(self, 'details_stack') and self.main_tabs.currentWidget() is self.details_stack
                and not getattr(self.home_panel, '_server_mode', False)):
            self._sync_details_tab()
        if hasattr(self, 'ai_dock'):
            self.ai_dock.update_focus_target(inst)

    def _sync_details_tab(self):
        """按首页当前模式，在同一个标签里显示客户端或服务端详情。"""
        if getattr(self.home_panel, '_server_mode', False):
            self.main_tabs.setTabText(self._details_tab_idx, '服务端详情')
            server = self.home_panel.server_center.selected()
            if server is None:
                self.details_placeholder.setText(t('请先在“我的实例”中选择一个服务端。'))
                self.details_stack.setCurrentWidget(self.details_placeholder)
            else:
                self.server_details.set_server(server)
                self.details_stack.setCurrentWidget(self.server_details)
        else:
            self.main_tabs.setTabText(self._details_tab_idx, t('INSTANCE_DETAILS'))
            inst = self.home_panel.current_instance()
            if inst is None:
                self.details_placeholder.setText(t('请先在“我的实例”中选择一个实例。'))
                self.details_stack.setCurrentWidget(self.details_placeholder)
            else:
                self.instance_details.set_instance(inst, paths.GAME_DIR)
                self.details_stack.setCurrentWidget(self.instance_details)

    def _show_instance_details(self, inst, switch: bool = True):
        self.instance_details.set_instance(inst, paths.GAME_DIR)
        self.main_tabs.setTabText(self._details_tab_idx, t('INSTANCE_DETAILS'))
        self.details_stack.setCurrentWidget(self.instance_details)
        if switch:
            self._details_skip_sync_once = self.main_tabs.currentWidget() is not self.details_stack
            self.main_tabs.setCurrentIndex(self._details_tab_idx)

    def _hide_instance_details(self):
        self._sync_details_tab()

    # ---- 服务端详情(与实例详情同构) ----
    def _on_server_selected(self, server):
        """详情标签可见时同步当前服务端。"""
        if (self.main_tabs.currentWidget() is self.details_stack
                and getattr(self.home_panel, '_server_mode', False)):
            self._sync_details_tab()

    def _show_server_details(self, server, switch: bool = True):
        self.server_details.set_server(server)
        self.main_tabs.setTabText(self._details_tab_idx, '服务端详情')
        self.details_stack.setCurrentWidget(self.server_details)
        if switch:
            self._details_skip_sync_once = self.main_tabs.currentWidget() is not self.details_stack
            self.main_tabs.setCurrentIndex(self._details_tab_idx)

    def _hide_server_details(self):
        self._sync_details_tab()

    def _open_details_for_current(self):
        """左侧「实例详情」按钮:按当前左侧面板所处模式决定打开哪个详情页。

        客户端模式未选实例时给出提示,而不是默默什么都不做——那是之前
        「点了没反应」的问题来源。
        """
        home = self.home_panel
        if getattr(home, '_server_mode', False):
            server = home.server_center.selected()
            if server is None:
                inline_notice(self, t('实例详情'), t('请先在右侧选中一个服务端。'))
                return
            self._show_server_details(server)
            return
        inst = home.current_instance()
        if inst is None:
            inline_notice(self, t('实例详情'), t('请先在右侧选中一个实例。'))
            return
        self._show_instance_details(inst)

    def _smart_import_path(self, path: str):
        """「导入服务端 → 智能导入」:交给既有的智能导入流程。"""
        from launcher_app.ui.smart_import_ui import start_smart_import
        start_smart_import(self, path)

    def _on_main_tab_changed(self, idx: int):
        """主标签页切换时短暂显现新页面。"""
        from launcher_app.ui.ui_anim import reveal
        w = self.main_tabs.widget(idx) if 0 <= idx < self.main_tabs.count() else None
        if w is getattr(self, 'details_stack', None):
            if getattr(self, '_details_skip_sync_once', False):
                self._details_skip_sync_once = False
            else:
                self._sync_details_tab()
        if w is not None:
            reveal(w)
        if w is self.resource_center and self.download_tab.version_tree.topLevelItemCount() == 0:
            self.load_versions()
        self._update_mode_button()

    def _home_open_instance_manager(self, inst):
        """「我的版本」首页 → 实例设置/版本设置 需要打开实例管理时调用。

        没选中实例就提示,避免打开一个空管理界面让人困惑。"""
        if inst is None:
            inline_notice(self, t("INSTANCE_SETTINGS"),
                                    t("SELECT_AN_INSTANCE_ON_THE_RIGHT_FIRST"))
            return
        self.open_instance_manager(inst)

    def _on_login_changed(self):
        """首页登录卡片改了离线昵称 → 重读设置,刷新登录显示。"""
        self.settings = load_settings()
        self.home_panel.refresh_login()
        if hasattr(self, "ai_focus_sidebar"):
            self.ai_focus_sidebar.login_card.refresh()
        self.statusBar().showMessage(t("LOGIN_INFO_UPDATED"))

    def _instance_actions(self):
        from launcher_app.instances.instance_actions import InstanceActions
        from launcher_app.ui.instance_actions_controller import InstanceActionsController
        from settings import update_setting
        preparing = lambda: self.download_tasks.is_running or (self._launch_task is not None and self._launch_task.is_running)
        return InstanceActionsController(
            parent=self, service_factory=lambda: InstanceActions(paths.GAME_DIR),
            busy_any=lambda: bool(self._running_instances) or preparing(),
            busy_instance=lambda instance: instance in self._running_instances or preparing(),
            settings=lambda: self.settings,
            save_last_played=lambda instance: update_setting('last_played_instance', instance),
            refresh=self.refresh_instances, select=self._select_instance_by_id,
            reload_versions=self.load_versions, show_status=self.statusBar().showMessage,
            log_feedback=self._log_feedback)

    def _select_instance_by_id(self, instance_id):
        for index in range(self.instance_list.count()):
            item = self.instance_list.item(index)
            if (item.data(Qt.ItemDataRole.UserRole) or {}).get('id') == instance_id:
                self.instance_list.setCurrentItem(item)
                break

    def backup_current_instance(self, inst):
        self._instance_actions().backup(inst)

    def _rename_instance(self, inst):
        self._instance_actions().rename(inst)

    def _delete_instance(self, inst):
        self._instance_actions().delete(inst)

def _open_auto_tutorial_safe(window):
    """首次启动选「新手」后自动开引导式教程;失败只记日志,不影响使用。"""
    try:
        window.open_guide_demo()
    except Exception as e:
        try:
            window._log_feedback(f"自动新手教程启动失败:{e}", "警告")
        except Exception:
            pass

if __name__ == "__main__":
    import sys as _sys
    if "--mcp" in _sys.argv:
        # MCP 服务模式(stdio):供外部 AI 宿主调用启动器工具,不启动 GUI
        from launcher_app.browser.mcp_server import serve
        serve()
        raise SystemExit(0)
    if "--mcp-http" in _sys.argv:
        # MCP Streamable-HTTP 模式:POST /mcp → 供「http」连接。--mcp-http [port]
        from launcher_app.browser.mcp_server import serve_http
        port = 8766
        try:
            i = _sys.argv.index("--mcp-http")
            if i + 1 < len(_sys.argv) and _sys.argv[i + 1].isdigit():
                port = int(_sys.argv[i + 1])
        except Exception:
            pass
        serve_http(port=port)
        raise SystemExit(0)
    print("正在获取版本列表(首次约几秒,请稍等)...")
    app = QApplication(sys.argv)
    # Fusion gives custom-styled controls the same geometry on Windows 10/11.
    app.setStyle("Fusion")
    app.setWindowIcon(application_icon())
    from launcher_app.ui.ui_style import apply_global_dark_palette, set_theme_mode
    set_theme_mode(load_settings().get('ui_theme', 'system'))
    apply_global_dark_palette(app)   # 系统深色 → 全局深色调色板,统一对话框/菜单/标签页

    # 退出兜底:强制回收本地模型 llama-server 子进程,避免孤儿(关闭走 closeEvent.shutdown,
    # 但异常退出/多路径时可能漏;atexit + aboutToQuit 双保险,配合 local_ai._TRACKED_PROCS)。
    try:
        from launcher_app.ai.local_ai import _reap_tracked as _reap_llama
        app.aboutToQuit.connect(_reap_llama)
    except Exception:
        pass

    # Protect one launcher data directory across processes on Windows, Linux,
    # and macOS. Keep the lock object alive for the full GUI lifetime.
    _instance_lock = None
    if not _CI_STARTUP_SMOKE:
        _instance_lock = QLockFile(os.path.join(paths.CONFIG_DIR, 'launcher_app.instances.launcher.lock'))
        _instance_lock.setStaleLockTime(0)
        if not _instance_lock.tryLock(0):
            if _instance_lock.error() == QLockFile.LockError.LockFailedError:
                answer = action_question(
                    None,
                    t('启动器已在运行'),
                    t('检测到这个数据目录已有一个启动器进程。\n\n仍要再启动一个吗？多个窗口可能同时修改配置、下载或操作同一实例。'),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    raise SystemExit(0)
            else:
                QMessageBox.critical(
                    None,
                    t('无法检查启动器是否已运行'),
                    t('无法创建单实例锁文件：{v0}\n请检查 AMCL 文件夹的写入权限后重试。').format(v0=(_instance_lock.fileName())),
                )
                raise SystemExit(1)

    splash = startup_splash()
    splash.show()
    splash.showMessage("正在读取启动器设置…", Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                       startup_message_color())
    app.processEvents()

    # 首次启动:还没配置过游戏目录 → 弹引导界面(选路径 + 首次配置 AI + 新手/老手)
    first = not _CI_STARTUP_SMOKE and not (load_settings().get("game_dir") or "").strip()
    _auto_tutorial = False
    if first:
        splash.hide()
        from launcher_app.ui.onboarding import OnboardingDialog
        od = OnboardingDialog()
        od.exec()
        # 新手:配置完成后自动走一遍引导式新手教程(老手跳过,设置→界面可重播)
        if getattr(od, "want_tutorial", False):
            _auto_tutorial = True

        splash.show()
        splash.showMessage("正在加载启动器组件…", Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                           startup_message_color())
        app.processEvents()

    splash.showMessage("正在加载功能模块与界面…", Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                       startup_message_color())
    app.processEvents()
    window = MainWindow()
    app.styleHints().colorSchemeChanged.connect(window._on_system_color_scheme_changed)
    window.setWindowIcon(application_icon())
    splash.showMessage("正在扫描已有实例…", Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                       startup_message_color())
    app.processEvents()
    if not _CI_STARTUP_SMOKE:
        window.load_versions()  # 启动时先加载一次
    window.show()
    splash.finish(window)
    # 更新脚本只有收到这个“主窗口已显示”标记才会删除旧版备份；否则自动回退。
    updater.confirm_pending_update(paths.BASE_DIR)
    _rollback_notice = updater.consume_rollback_notice(paths.BASE_DIR)
    if _rollback_notice:
        QTimer.singleShot(
            500,
            lambda message=_rollback_notice: inline_notice(
                window, t('已恢复旧版本'), message),
        )
    _startup_smoke_status = 0
    if _CI_STARTUP_SMOKE:
        from ci_smoke import _report, packaged_file_errors
        _startup_errors = packaged_file_errors()
        if _startup_errors:
            _startup_smoke_status = 1
            for _error in _startup_errors:
                _report("SMOKE FAIL: " + _error, error=True)
        else:
            app.processEvents()
            _report("SMOKE OK: packaged launcher reached its first usable window")
        QTimer.singleShot(250, app.quit)
    # 首次启动选了「新手」→ 自动走一遍引导式新手教程(用 QTimer 延迟到首帧后,保证控件就绪)
    if _auto_tutorial:
        QTimer.singleShot(400, lambda: _open_auto_tutorial_safe(window))
    _app_exit_code = app.exec()
    sys.exit(_startup_smoke_status if _CI_STARTUP_SMOKE else _app_exit_code)
