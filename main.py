# -*- coding: utf-8 -*-
"""
Agent Minecraft Launcher — 阶段 1 · 启动核心
功能:
- 版本分类树(大版本 → 正式版 / 折叠的预览版;远古版本单独折叠)
- 选中版本 → 显示详细信息(jar 大小、所需 Java 等)
- 安装所选版本:客户端 jar + 依赖库 + 资源文件(镜像加速 + sha1 校验)
- 启动游戏:自动准备 Java → 拼启动命令 → 拉起进程 → 实时显示游戏日志
"""
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
    from java_manager import java_version_probe
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
    from memory_relief import main as memory_relief_main
    raise SystemExit(memory_relief_main(sys.argv[sys.argv.index('--amcl-memory-relief') + 1]))
# Dispatch before importing Qt or constructing the launcher in the helper process.
if __name__ == '__main__' and '--amcl-plugin-web-window' in sys.argv:
    from plugin_web_worker import main as web_window_main
    raise SystemExit(web_window_main())
if __name__ == '__main__' and '--amcl-server-host' in sys.argv:
    from server_host import main as server_host_main
    _server_host_index = sys.argv.index('--amcl-server-host')
    raise SystemExit(server_host_main(sys.argv[_server_host_index + 1:]))
import time
from datetime import datetime

import requests
from log_privacy import redact_text
from downloader import failure_advice

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

import updater  # 自动更新(检查 GitHub 新版本 / 下载 / 替换)
from bridge_mod_dist import BRIDGE_MOD_VERSION  # bridge-mod 当前版本
from task_controllers import DownloadTaskController, VersionManifestController
from background_tasks import BackgroundTask
from assistant import AIChatDock, AI_DOCK_RETURN_MIME, permission_instructions  # AI 助手(右侧停靠对话栏)
from ai_actions import plain_language_instructions
from download_indicator import DownloadDetailWidget, DownloadIndicator  # 左下角下载指示器
from updater_dialog import UpdateDialog  # 检查更新对话框(独立模块)
from download_tab import DownloadTab  # 下载新实例选项卡(左侧菜单 + 分类面板)
from fetch_versions import fetch_version_detail, fetch_version_manifest  # 网络模块
import i18n  # 界面语言(跟随系统,可设置覆盖)
from i18n import t
from instance_install_service import InstanceInstallService
from game_launch_service import GameLaunchService, LoginRequiredError
from game_process_controller import GameProcessController
from crash_diagnostics import collect_crash_report, detect_crash
from instance_catalog_service import InstanceCatalogService
from modpack import import_modpack as import_modpack_file  # 整合包导入
from modrinth import download_mod  # Modrinth 搜索与下载(含中文名支持)
import paths  # 游戏目录(可配置,设置/引导里可改)
from paths import GAME_DIR, RUNTIME_DIR  # 兼容旧引用(测试用);内部统一用 paths.GAME_DIR
from os_platform.openpath import open_path  # 跨平台打开文件/文件夹(替代 os.startfile)
from settings import load_settings, save_settings  # 启动器配置
from skill_manager import SkillManager, SkillManagerDialog  # 技能(运行时辅助)系统
from version_tree import fill_version_tree  # 版本树构建(与下载选项卡共用)


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
        from ui_style import load_theme_from_settings
        load_theme_from_settings(self.settings)
        from ui_anim import set_animations_enabled
        set_animations_enabled(self.settings.get("ui_animations_enabled", True))
        i18n.set_language(self.settings.get("language", "auto"))  # 界面语言(跟随系统/设置)

        # ---- 语言包(第三方/玩梗语言):加载 内置语言包 + AMCL/languages/*.json + 插件注册的包 ----
        # 语言包 = 用 {"原文": "替换文本"} 覆盖启动器所有文本;可选,切换后重启生效。
        try:
            import i18n as _i18n
            import os as _os
            _n = 0
            # ① 内置产品数据语言包(仓库根 languages/,如机翻生成的 en/fr/es...json)
            _bundle_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "languages")
            _n += _i18n.load_packs_from_dir(_bundle_dir)
            # ② 用户第三方语言包(AMCL/languages/)
            _user_dir = paths.data_dir("languages")
            _n += _i18n.load_packs_from_dir(_user_dir)
            _lang = self.settings.get("language", "auto")
            if _lang in _i18n.list_packs():
                _i18n.set_language(_lang)
            print(f"[语言包] 内置+用户共加载 {_n} 个(内置:{_bundle_dir}, 用户:{_user_dir});当前语言 {_i18n.get_language()}")
        except Exception as e:
            print(f"[语言包] 加载异常:{type(e).__name__}: {e}")

        # ---- 插件系统:启动时静态装载插件(plugins/*.py),登记工具/页面/设置/技能 ----
        # 被禁用的插件(settings["plugins_disabled"])跳过;默认关闭的插件需显式启用。
        # 提前到这里装载(先于 设置中心/技能管理器 创建),让插件登记内容立即可见。
        try:
            import plugin_manager
            _loaded = plugin_manager.load_all(self.settings)
            print(f"[插件] 装载 {len([k for k, v in _loaded.items() if v])} 个插件")
        except Exception as e:
            print(f"[插件] 装载异常:{type(e).__name__}: {e}")

        # ---- 无边框自定义标题栏(名称位置按平台,见 frameless_titlebar.py) ----
        self.setWindowTitle("AMCL")   # 任务栏/系统标题
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        if sys.platform.startswith(('linux', 'win')):
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        from frameless_titlebar import FramelessTitleBar
        self._running_instances = set()
        self._running_label = QLabel("")     # 放在标题栏(悬停看具体实例)
        self._running_label.setMaximumWidth(160)
        self.title_bar = FramelessTitleBar(self, "AMCL",
                                           trailing_widget=self._running_label)
        self._ai_focus_mode = False
        self._ai_transition = None
        self.ai_mode_button = QPushButton("AI 模式")
        self.ai_mode_button.setToolTip("进入全屏对话工作台")
        self.online_button = QPushButton("联机")
        self.online_button.setToolTip("联机方案中心")
        self.settings_button = QPushButton("设置")
        self.settings_button.setToolTip("启动器设置")
        self.title_nav = QWidget(self.title_bar)
        nav_layout = QHBoxLayout(self.title_nav)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(12)
        for button, width in ((self.ai_mode_button, 110),
                              (self.online_button, 84),
                              (self.settings_button, 84)):
            button.setProperty('titleNav', True)
            button.setFixedSize(width, 28)
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
        from version_home import VersionHome
        tab_a = VersionHome()
        self.home_panel = tab_a                     # 保留引用,便于刷新登录显示等
        self.instance_list = tab_a.instance_list    # 版本列表(兼容旧引用:右键/视图/双击)
        self.launch_btn = tab_a.launch_btn          # 启动游戏大按钮
        # 双击仍直接启动；左侧主按钮由 VersionHome 按客户端/服务端模式分派。
        self.instance_list.itemDoubleClicked.connect(self.launch_selected_instance)
        # 键盘导航(遥控器式):实例列表按回车 → 启动选中实例(itemActivated)
        tab_a.launch_requested.connect(lambda _inst: self.launch_selected_instance())
        tab_a.refresh_requested.connect(self.refresh_instances)
        # 新首页抛出的信号 → 启动器处理
        tab_a.open_instance_manager_requested.connect(self._home_open_instance_manager)
        tab_a.open_settings_requested.connect(self.open_settings)
        tab_a.login_changed.connect(self._on_login_changed)
        tab_a.one_click_config_requested.connect(self._one_click_config_kind)
        tab_a.import_modpack_requested.connect(self.import_modpack)
        tab_a.open_resources_requested.connect(self._open_resource_page)
        tab_a.tutorial_requested.connect(self.open_tutorial)
        # 左侧「实例详情」大按钮:客户端实例 → 实例详情页;服务端 → 服务端详情页
        tab_a.instance_details_requested.connect(self._open_details_for_current)
        tab_a.smart_import_requested.connect(self._smart_import_path)

        # ---- 「下载新资源」综合入口:左侧菜单 + 首页/实例/Mod/光影/数据包/资源包 ----
        from resource_center import ResourceCenter
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
        from folder_instance_import import start_import
        self.instance_list.folders_dropped.connect(lambda folders: start_import(self, folders))

        # ---- 主选项卡(我的实例 / 共用详情 / 下载新资源) ----
        self.main_tabs = QTabWidget()
        from ui_style import tab_style, card_btn_style, set_style
        set_style(self.main_tabs, tab_style)   # 外层标签页:圆角+字体放大(14px)
        self.main_tabs.addTab(tab_a, t("MY_INSTANCES"))
        self._my_inst_tab_idx = 0   # 「我的实例」= 主标签第 0 页(拖入文件 → 当作整合包安装)
        # 客户端与服务端详情共用一个顶层标签页。
        from instance_manager import InstanceManagerDialog
        self.instance_details = InstanceManagerDialog()
        self.instance_details.setObjectName("instance_details")
        tab_a.instance_selected.connect(self._on_instance_selected)
        from server_details import ServerDetailsView
        self.server_details = ServerDetailsView()
        self.server_details.setObjectName("server_details")
        tab_a.server_center.selection_changed.connect(self._on_server_selected)
        self.details_stack = QStackedWidget()
        self.details_placeholder = QLabel("请先在“我的实例”中选择一个实例或服务端。")
        self.details_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details_stack.addWidget(self.details_placeholder)
        self.details_stack.addWidget(self.instance_details)
        self.details_stack.addWidget(self.server_details)
        self._details_tab_idx = self.main_tabs.addTab(self.details_stack, t("INSTANCE_DETAILS"))
        self.main_tabs.addTab(self.resource_center, t("RESOURCES"))
        # 联机方案中心留在主窗口右侧，可和当前页面并排查看。
        from online_center import OnlineCenter
        self.online_dock = QDockWidget("联机", self)
        self.online_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.online_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        from ui_style import current_color
        set_style(self.online_dock, lambda: (
            f'QDockWidget {{ background: {current_color("panel_bg")};'
            f' border-left: 1px solid {current_color("panel_border")}; }}'))
        online_header = QWidget()
        online_header_layout = QHBoxLayout(online_header)
        online_header_layout.setContentsMargins(12, 4, 8, 4)
        online_header_layout.addWidget(QLabel("联机方案"))
        online_header_layout.addStretch()
        online_close = QPushButton("✕")
        online_close.setFixedSize(28, 28)
        set_style(online_close, card_btn_style)
        online_close.clicked.connect(self._close_online_center)
        online_header_layout.addWidget(online_close)
        self.online_dock.setTitleBarWidget(online_header)
        from ui_background import BackgroundWidget
        self.online_surface = BackgroundWidget(self.online_dock)
        online_body = QVBoxLayout(self.online_surface)
        online_body.setContentsMargins(0, 0, 0, 0)
        self.online_center = OnlineCenter(self.online_surface)
        self.online_center.setObjectName("online_center")
        online_body.addWidget(self.online_center)
        self.online_dock.setWidget(self.online_surface)
        # 设置页嵌入主窗口，由两种模式共用。
        from settings.center import SettingsCenter
        self.settings_center = SettingsCenter(self.settings)
        self.settings_center.applied.connect(self._on_settings_applied)
        self.settings_center.visual_changed.connect(self._on_visual_settings_changed)
        self.settings_center.runtime_changed.connect(self._on_runtime_settings_changed)

        # ---- 插件注册的主标签页(与下载新资源平级) ----
        try:
            import plugin_manager
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
        from ui_background import BackgroundWidget
        central = BackgroundWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.main_tabs)
        from ai_focus_mode import AIFocusSidebar
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
            from keyboard_nav import install_global_nav

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
                from left_menu import LeftMenu
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
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.online_dock)
        self.online_dock.hide()
        self.online_surface.installEventFilter(self)

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
        self.game_processes = GameProcessController(self)
        self.game_processes.line_received.connect(self._on_game_log_line)
        self.game_processes.exited.connect(self._on_game_process_exited)
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
        from ui_anim import install_interaction_feedback
        self._interaction_feedback = install_interaction_feedback(self)
        # 窗口大小/位置:放在最后恢复,确保其它控件已建好、不会在显示过程中被挤压
        self._restore_window_geometry()
        QTimer.singleShot(0, self._place_download_ball)

    # ---- 设置 ----
    def open_settings(self, tab: str | None = None):
        """在主窗口中打开两种模式共用的设置页。"""
        if tab == "mirror":
            self.settings_center.shell.switch_by_label(t("MIRROR"))
        if self._settings_open:
            return
        if self.online_dock.isVisible():
            self._close_online_center()
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
        from ui_anim import reveal
        reveal(self.settings_page)

    def _close_settings(self):
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
        from ui_anim import reveal
        reveal(self._central_stack.currentWidget())

    def _on_mode_button_clicked(self):
        if self._settings_open:
            self._close_settings()
        elif self.online_dock.isVisible():
            self._close_online_center()
            if not self._ai_focus_mode:
                self.main_tabs.setCurrentIndex(self._my_inst_tab_idx)
            self._update_mode_button()
        else:
            self._toggle_ai_focus_mode()

    def _update_mode_button(self):
        other_page = self._settings_open or self.online_dock.isVisible()
        if other_page:
            self.ai_mode_button.setText('主页')
            self.ai_mode_button.setToolTip('返回当前模式的主页')
        elif self._ai_focus_mode:
            self.ai_mode_button.setText('常规模式')
            self.ai_mode_button.setToolTip('退出 AI 模式')
        else:
            self.ai_mode_button.setText('AI 模式')
            self.ai_mode_button.setToolTip('进入全屏对话工作台')

    def _on_settings_applied(self):
        """设置窗口保存后:刷新本窗口与各处联动。"""
        s = self.settings_center.settings
        self.settings = s
        from ui_anim import set_animations_enabled
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
        from ui_style import (set_theme_mode, apply_global_dark_palette,
                              popup_menu_style, refresh_theme)
        set_theme_mode(self.settings.get('ui_theme', 'system'))
        apply_global_dark_palette(QApplication.instance())
        refresh_theme()
        strategy_menu = self.ai_dock.strategy_btn.menu()
        if strategy_menu is not None:
            strategy_menu.setStyleSheet(popup_menu_style())
        self.title_bar.refresh_theme()
        self._paint_title_background()
        self.ai_dock._dock_header.refresh_theme()
        from ui_anim import set_animations_enabled
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
        from ui_background import (load_wallpaper, mask_strength,
                                   input_style_qss, scroll_surface_qss)
        from ui_tokens import set_wallpaper_active, is_wallpaper_active
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
            from ui_style import refresh_theme
            refresh_theme()
        self._apply_dock_separator_style()

    def _apply_dock_separator_style(self):
        """Give the AI dock a visible, generous resize seam."""
        from ui_style import current_color
        base = current_color('btn_border')
        hover = current_color('accent')
        self.setStyleSheet(
            f'QMainWindow::separator {{ background: {base}; width: 7px; height: 7px; }}'
            f'QMainWindow::separator:hover {{ background: {hover}; }}')

    def _paint_title_background(self):
        """Keep the top dock opaque when the Linux window itself is translucent."""
        from ui_style import current_color
        color = QColor(current_color('bg1'))
        for widget in (self.title_dock, self.title_bar):
            palette = widget.palette()
            palette.setColor(QPalette.ColorRole.Window, color)
            widget.setPalette(palette)

    def _recompute_wallpaper(self):
        """按当前中央区尺寸 + 壁纸源,重算共享壁纸(一张画布),并设置中央区与 AI dock 视口。"""
        from ui_background import prepare_shared_wallpaper
        pix = getattr(self, "_wallpaper_source", None)
        mask = getattr(self, "_wallpaper_mask", 0.55)
        online = getattr(self, 'online_surface', None)
        online_visible = bool(online is not None and self.online_dock.isVisible())
        if getattr(self, '_settings_open', False):
            self.settings_page.set_wallpaper(pix, mask)
            return
        if getattr(self, '_ai_focus_mode', False):
            sidebar = self.ai_focus_sidebar
            if pix is None:
                self._wallpaper_scaled = None
                self._wallpaper_ox = self._wallpaper_oy = 0
                sidebar.clear()
                if online is not None:
                    online.clear()
            else:
                canvas = QSize(max(1, self.width()), max(1, sidebar.height()))
                scaled, ox, oy = prepare_shared_wallpaper(pix, canvas)
                self._wallpaper_scaled = scaled
                self._wallpaper_ox, self._wallpaper_oy = ox, oy
                sidebar.set_shared_view(scaled, ox, oy, mask)
                if online_visible:
                    origin = sidebar.mapTo(self, QPoint(0, 0))
                    position = online.mapTo(self, QPoint(0, 0))
                    online.set_shared_view(scaled, position.x() - origin.x() + ox,
                                           position.y() - origin.y() + oy, mask)
            self._sync_ai_wallpaper()
            return
        bg = getattr(self, "_background", None)
        if pix is None or bg is None:
            self._wallpaper_scaled = None
            self._wallpaper_ox = self._wallpaper_oy = 0
            if bg is not None:
                bg.clear()
            if online is not None:
                online.clear()
            self._sync_ai_wallpaper()
            return
        right_width = online.width() if online_visible else self._ai_dock_width()
        scaled, ox, oy = prepare_shared_wallpaper(pix, bg.size(), right_width)
        self._wallpaper_scaled = scaled
        self._wallpaper_ox = ox
        self._wallpaper_oy = oy
        if scaled is not None:
            bg.set_shared_view(scaled, ox, oy, mask)
            if online_visible:
                origin = bg.mapTo(self, QPoint(0, 0))
                position = online.mapTo(self, QPoint(0, 0))
                online.set_shared_view(scaled, position.x() - origin.x() + ox,
                                       position.y() - origin.y() + oy, mask)
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
                    from win_frameless import hit_test
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
                from win_frameless import apply_win_styles
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
        import window_geometry as wg
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
            import window_geometry as wg
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
        import window_geometry as wg
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
            import plugin_prompt as pp
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
            f"检测到 {', '.join(item['mods'])}；插件「{item['name']}」可提供对应的管理界面。"
            '启用后下次启动生效，也能在「设置 → 插件」里调整。')
        label.setWordWrap(True)
        layout.addWidget(label, 1)
        enable = QPushButton('启用插件')
        later = QPushButton('暂不启用')
        layout.addWidget(enable)
        layout.addWidget(later)
        dock.setWidget(content)
        self._plugin_notice = dock
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

        def finish(*, declined):
            import plugin_prompt as pp
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
        if getattr(self.home_panel.server_center, '_busy', False):
            QMessageBox.information(self, '服务端任务尚未结束', '请等待服务端扫描、导入或补全任务结束后再关闭启动器。')
            event.ignore()
            return
        """窗口关闭:卸载本地 AI 引擎(llama-server),确保无残留进程。"""
        self._save_window_geometry()
        self.download_tasks.cancel()
        if self._launch_task is not None:
            self._launch_task.cancel()
        self.version_manifest.cancel()
        self.game_processes.detach()
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
        from ai_focus_mode import AIFocusTransition
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
            header.chat_button.setText('对话')
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
            header.chat_button.setText('聊天')
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
        """在主窗口右侧展开联机抽屉，左侧页面保持可用。"""
        if self.online_dock.isVisible():
            return
        if self._settings_open:
            self._close_settings()
        self._online_restore = {
            'dock_visible': self.ai_dock.isVisible(),
            'dock_width': self.ai_dock.width(),
            'strip_visible': self.ai_strip_dock.isVisible(),
        }
        self.ai_dock.hide()
        self.ai_strip_dock.hide()
        self.online_dock.show()
        from ui_anim import reveal
        QTimer.singleShot(0, lambda: reveal(self.online_surface)
                          if self.online_dock.isVisible() else None)
        width = max(480, self.width() - 320) if self._ai_focus_mode else min(560, max(400, self.width() // 2))
        QTimer.singleShot(0, lambda: self.resizeDocks(
            [self.online_dock], [width], Qt.Orientation.Horizontal)
            if self.online_dock.isVisible() else None)
        self._update_mode_button()

    def _close_online_center(self):
        if not self.online_dock.isVisible():
            return
        self.online_dock.hide()
        saved = getattr(self, '_online_restore', {})
        self.ai_dock.setVisible(saved.get('dock_visible', False))
        self.ai_strip_dock.setVisible(saved.get('strip_visible', False))
        if saved.get('dock_visible') and not self.ai_dock.isFloating():
            width = saved.get('dock_width', self.ai_dock.width())
            QTimer.singleShot(0, lambda: self.resizeDocks(
                [self.ai_dock], [width], Qt.Orientation.Horizontal)
                if self.ai_dock.isVisible() and not self.ai_dock.isFloating() else None)
        self._online_restore = None
        from ui_anim import reveal
        reveal(self._central_stack.currentWidget())
        self._recompute_wallpaper()
        self._update_mode_button()

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
                from tutorial_intro import TutorialIntroDialog
                if TutorialIntroDialog(self).exec() != 1:
                    return   # 用户跳过基础知识 → 不继续引导
            except Exception:
                pass

        from guide_overlay import GuideDriver
        from tutorial_steps import first_game_steps
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
        from game_command import send_command
        cmd, ok = QInputDialog.getText(self, "发送游戏指令",
                                       "输入游戏指令(如 summon zombie,可省略开头的 /):")
        if not ok or not cmd.strip():
            return
        result = send_command(cmd, self)
        if "\n" in result:
            QMessageBox.information(self, "游戏指令", result)
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
        from ui_background import BackgroundWidget
        self.ai_strip = BackgroundWidget()   # 窄条也透明,画共享壁纸片段
        self.ai_strip.setFixedWidth(22)
        sv = QVBoxLayout(self.ai_strip)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(0)
        expand_btn = QPushButton("▶")
        expand_btn.setFixedSize(22, 72)
        expand_btn.setToolTip("展开 AI 助手")
        from ui_style import set_style, accent_border_style
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
        """给 AI 的上下文:启动器设置 + 当前选中的实例信息"""
        # 输出语言跟随界面/系统选择:中文界面用中文为主,英文界面用英文为主。
        # 专业/英文术语(如 Mod 名、路径、工具名、报错)保留原样,不强行翻译,避免引入 bug。
        ui_lang = i18n.get_language()
        if ui_lang == "en":
            lang_instr = ("Reply in English by default. Keep technical terms, command names, "
                          "Mod/instance IDs, paths and error messages in their original form "
                          "(do not force-translate them).")
        else:
            lang_instr = ("默认用中文回答。Mod 名、命令、实例 id、路径、报错等专业/英文术语保留原样,"
                          "不要强行翻译。")
        lines = [
            "你是 Agent Minecraft Launcher 启动器里内置的 AI 助手。",
            lang_instr,
            f"启动器设置: 离线游戏名 {self.settings.get('username', 'Player')},"
            f" 内存 {str(self.settings.get('memory_gb')) + 'G' if self.settings.get('memory_gb') else '自动（按可用内存）'},"
            f" 版本隔离 {'开' if self.settings.get('version_isolation', True) else '关'}",
        ]
        inst = None
        item = self.instance_list.currentItem()
        if item is not None:
            inst = item.data(Qt.ItemDataRole.UserRole)
        if inst:
            lines.append(f"当前选中的实例: {inst['id']}"
                         f"(加载器:{inst['loader'] or '原版'}, 基础版本:{inst['base']})")
        lines.append(permission_instructions(self.settings))
        lines.append(plain_language_instructions(self.settings))
        # t16:不再在 system 里枚举工具名——工具 schema 由请求 body 提供(云端按需挂载),
        # 枚举既冗余(每轮多花几百 token)又会误导模型去调用未挂载的工具。
        # 技能提示:任务拆分 / 指令指南 等启用的技能注入行为指导
        for hint in self.skill_mgr.ai_hints():
            lines.append(hint)
        return "\n".join(lines)

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
        save_settings(self.settings)

    # ---- 文件菜单动作 ----
    def open_game_dir(self):
        """打开游戏目录(所有版本共用文件的根目录)"""
        os.makedirs(paths.GAME_DIR, exist_ok=True)
        open_path(paths.GAME_DIR)

    def clear_instances(self):
        """清空所有实例(versions 目录),共用文件(依赖库/资源/Java)保留"""
        if QMessageBox.question(
                self, "确认", "确定要删除所有实例吗?\n(versions 目录会被清空,共用文件保留)") != QMessageBox.StandardButton.Yes:
            return
        versions_dir = os.path.join(paths.GAME_DIR, "versions")
        if os.path.isdir(versions_dir):
            for name in os.listdir(versions_dir):
                p = os.path.join(versions_dir, name)
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
        self.load_versions()
        self.refresh_instances()
        self.statusBar().showMessage("所有实例已清空")

    def import_modpack(self):
        """导入整合包(自动识别格式:Modrinth .mrpack / CurseForge .zip / 扁平实例文件夹 zip),后台执行不卡界面"""
        if self.skill_mgr.is_enabled('smart_import') is True:
            from smart_import_ui import start_smart_import
            start_smart_import(self)
            return
        import traceback as _tb
        DBG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                ".tmp", "import_debug.log")

        def dbg(msg):
            try:
                os.makedirs(os.path.dirname(DBG_PATH), exist_ok=True)
                with open(DBG_PATH, "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            except Exception:
                pass

        from PySide6.QtWidgets import QInputDialog
        path, _f = QFileDialog.getOpenFileName(
            self, "选择整合包", "", "整合包 (*.mrpack *.zip)")
        dbg(f"file dialog returned: {path!r}")
        if not path:
            dbg("empty path -> return")
            return

        # 识别格式;扁平整合包(无清单的实例文件夹 zip)需要用户提供 MC 版本(可选加载器)
        from modpack import detect_modpack_format, suggested_instance_id
        mc_version = None
        loader = None
        try:
            fmt = detect_modpack_format(path)
        except Exception as e:
            fmt = None
            dbg(f"detect_modpack_format EXC: {e}")
        dbg(f"fmt={fmt!r}")
        if fmt == 'server':
            self.home_panel.tabs.setCurrentIndex(self.home_panel._server_tab_index)
            self.home_panel.server_center.scan_import(path)
            return
        if fmt == "flat":
            mc_version, okv = QInputDialog.getText(self, "导入扁平整合包", "该整合包没有清单,请填游戏版本(如 1.20.1):")
            if not okv or not mc_version.strip():
                return
            mc_version = mc_version.strip()
            loader, okl = QInputDialog.getItem(
                self, "导入扁平整合包", "加载器(可选,跳过=原版):",
                ["(原版)", "fabric", "forge", "neoforge"], 0, False)
            if okl:
                loader = None if loader == "(原版)" else loader
        elif fmt is None:
            QMessageBox.warning(self, "导入整合包",
                                "无法识别该文件的格式(既不是 Modrinth/CurseForge,也不像实例文件夹 zip)")
            dbg("fmt None -> warning, return")
            return

        # 同名预检:实例名已存在 → 让用户自己命名(不直接失败)
        instance_id = None
        try:
            default_id = suggested_instance_id(path)
            dbg(f"default_id={default_id!r}")
            if default_id and os.path.isdir(os.path.join(paths.GAME_DIR, "versions", default_id)):
                new_id, okn = QInputDialog.getText(
                    self, "实例名重复",
                    f"已存在实例「{default_id}」,请为新实例命名:", text=default_id + "-2")
                if not okn or not new_id.strip():
                    dbg("name conflict -> user cancelled")
                    return
                instance_id = new_id.strip()
        except Exception as e:
            dbg(f"suggested_instance_id EXC: {e}")
            pass   # 预检失败也不拦导入(让 import_modpack 的"已存在"兜底)

        self.statusBar().showMessage("正在导入整合包...")
        dbg(f"calling _run_download, instance_id={instance_id!r}, mc={mc_version!r}, loader={loader!r}")

        def worker(status_cb, progress_cb):
            try:
                dbg("worker: import_modpack_file BEGIN")
                # 注意:返回变量用 done_id,避免和闭包里的 instance_id 同名导致 UnboundLocalError
                done_id = import_modpack_file(path, paths.GAME_DIR,
                                             mc_version=mc_version, loader=loader,
                                             instance_id=instance_id,
                                             status_callback=status_cb,
                                             progress_callback=progress_cb)
                dbg(f"worker: import_modpack_file OK -> {done_id}")
                status_cb(f"整合包导入完成:{done_id} ✅")
            except Exception as e:
                dbg(f"worker: import_modpack_file EXC: {type(e).__name__}: {e}\n{_tb.format_exc()}")
                status_cb(f"❌ 整合包导入失败:{type(e).__name__}: {e}")

        self._run_download(worker)
        dbg("_run_download called, returning")

    # ---- 下载新实例:左侧菜单 → 分类面板 → 后台下载 ----
    def start_instance_download(self):
        """读取 DownloadTab 的汇总选择,后台线程创建实例(不卡界面)"""
        st = self.download_tab.state()
        if not st["version"]:
            self.download_tab.set_status("请先选一个游戏版本")
            return
        self._run_download(lambda status, progress: self.create_instance(
            st["version"], st["loader_key"], st["modrinth_loader"],
            st["shader"], st["optimize"],
            loader_version=st["loader_version"],
            shader_version=st["shader_version"],
            optimize_versions=st["optimize_versions"],
            fabric_api_version=st.get("fabric_api_version"),
            status_cb=status, progress_cb=progress))

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
        self.dl_indicator.setToolTip("下载中,点击查看详情")
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

    def _on_download_progress(self, done: int, total: int):
        self.download_tab.set_progress(done, total)
        self.dl_indicator.set_progress(done, total)
        self._dl_progress = (done, total)

    def _on_download_done(self, ok: bool, error: str):
        error = redact_text(error, self.settings)
        if ok:
            self.statusBar().showMessage("下载任务完成")
            self._dl_log.append("✅ 下载任务完成")
            self.dl_indicator.setToolTip("下载完成,点击查看详情")
            self.dl_indicator.set_completed(True)
        else:
            self.statusBar().showMessage(f"下载失败: {error}")
            self._dl_log.append(f"❌ 下载失败: {error}")
            self.dl_indicator.setToolTip("下载失败,点击查看详情")
            self.dl_indicator.set_completed(False)
        self.dl_indicator.set_progress(1, 1)
        self.dl_indicator.set_completed(ok)
        self.dl_indicator.set_failed(not ok)
        if not ok:
            advice = failure_advice(error)
            self._dl_log.append(advice)
            self.download_tab.set_status(f"下载失败：{error}\n{advice}")
            self.dl_indicator.setToolTip(f"下载失败\n{advice}\n点击查看详情")
        self._dl_finish(ok)

    def _on_download_cancelled(self):
        if self._launch_task is not None:
            self._stop_launch_button_animation()
        self._dl_log.append("已取消下载。已校验的文件会保留，重试时会尽量复用。")
        self.dl_indicator.set_progress(0, 1)
        self.dl_indicator.set_waiting()
        self.dl_indicator.setToolTip("下载已取消，点击查看详情")
        self._busy_download(False)

    def _cancel_current_task(self):
        if self._launch_task is not None and self._launch_task.is_running:
            self._launch_task.cancel()
        else:
            self.download_tasks.cancel()
        self.dl_indicator.setToolTip("正在收尾，稍等一下…")

    def _retry_download(self):
        if self.download_tasks.state not in {'failed', 'cancelled'}:
            return
        worker = self.download_tasks.last_worker
        if worker is not None:
            self._run_download(worker)

    def _ensure_dl_overlay(self):
        """惰性创建下载详情覆盖层(ContentOverlay + DownloadDetailWidget,复用不重复建)。"""
        if getattr(self, "_dl_overlay", None) is not None:
            return
        from ui_overlay import ContentOverlay

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
            self._launcher_log_path = os.path.join(paths.GAME_DIR, "logs", "launcher.log")
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
        dock_hint = QLabel("松开，将 AI 助手停靠回右侧", self)
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
                    from folder_instance_import import start_import
                    start_import(self, list(dict.fromkeys(folders)))
            e.setDropAction(Qt.DropAction.CopyAction)
            e.accept()
        else:
            e.ignore()   # 其它页面:不当作整合包,交由该页控件处理(如实例详情列表拷入文件夹)

    def install_modpack_from_path(self, path: str):
        """把本地的整合包文件导入成新实例(拖放入口;自动识别格式)。"""
        enabled = getattr(getattr(self, 'skill_mgr', None), 'is_enabled',
                          lambda _name: False)('smart_import') is True
        if enabled:
            from smart_import_ui import start_smart_import
            start_smart_import(self, path)
            return
        if os.path.isdir(path):
            from folder_instance_import import start_import
            start_import(self, [path])
            return
        from modpack import detect_modpack_format, import_modpack
        from PySide6.QtWidgets import QInputDialog
        fmt = detect_modpack_format(path)
        mc_version = None
        loader = None
        if fmt == 'server':
            self.home_panel.tabs.setCurrentIndex(self.home_panel._server_tab_index)
            self.home_panel.server_center.scan_import(path)
            return
        if fmt == "flat":
            mc_version, ok = QInputDialog.getText(
                self, "导入扁平整合包", "该整合包没有清单,请填游戏版本(如 1.20.1):")
            if not ok or not mc_version.strip():
                return
            mc_version = mc_version.strip()
            loader, ok2 = QInputDialog.getItem(
                self, "加载器", "加载器(可选,跳过=原版):",
                ["(原版)", "fabric", "forge", "neoforge"], 0, False)
            if ok2:
                loader = None if loader == "(原版)" else loader
        elif fmt is None:
            QMessageBox.information(self, "拖入文件",
                                    "无法识别该文件为整合包(Modrinth/CurseForge/实例文件夹 zip)。")
            return

        def worker(status, progress):
            try:
                done = import_modpack(path, paths.GAME_DIR, mc_version=mc_version,
                                      loader=loader, status_callback=status,
                                      progress_callback=progress)
                status(f"✅ 整合包导入完成:{done}")
            except Exception as ex:
                status(f"❌ 整合包导入失败:{type(ex).__name__}: {ex}")
        self._run_download(worker)

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
        online_surface = getattr(self, 'online_surface', None)
        if (watched is central or watched is dock or watched is focus_sidebar
                or watched is online_surface) and (resized or moved_while_docked):
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
            from ui_style import current_color
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

    def _update_running_label(self):
        """刷新顶部的"已有 x 个运行中的实例"(悬停显示具体实例)"""
        from ui_style import muted_color, success_color
        n = len(self._running_instances)
        if n:
            running_text = "🟢 正在运行：" + ", ".join(sorted(self._running_instances))
            self._running_label.setText(
                self._running_label.fontMetrics().elidedText(
                    running_text, Qt.TextElideMode.ElideRight, 160))
            self._running_label.setToolTip("运行中的实例:\n" + "\n".join(sorted(self._running_instances)))
            self._running_label.setStyleSheet(f"color: {success_color()}; font-weight: bold;")
        else:
            self._running_label.setText("尚未启动游戏")
            self._running_label.setToolTip("启动实例后这里会显示运行中的游戏")
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
        self.dl_indicator.setToolTip("下载中,点击查看详情")
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
            self.dl_indicator.setToolTip(f"{title}失败,点击查看详情")
        elif status and ("完成" in status or "已就绪" in status.lower()):
            self.dl_indicator.setToolTip(f"{title}完成,点击查看详情")
        else:
            self.dl_indicator.setToolTip(f"正在下载{title},点击查看详情")
        self.dl_indicator.show()

    def report_download_done(self, title: str, ok: bool, msg: str):
        """通用下载结束入口:写日志 + 满环 + 收起(2s)。"""
        msg = redact_text(msg, self.settings)
        self._dl_log.append(msg)
        self._dl_progress = (1, 1)
        self.dl_indicator.set_progress(1, 1)
        self.dl_indicator.set_completed(ok)
        self.dl_indicator.setToolTip(f"{title}" + ("完成,点击查看详情" if ok else "失败,点击查看详情"))
        self.dl_indicator.set_failed(not ok)
        if not ok:
            advice = failure_advice(msg)
            self._dl_log.append(advice)
            self.dl_indicator.setToolTip(f"{title}失败\n{advice}\n点击查看详情")
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
        from ui_anim import is_animations_enabled
        if not hasattr(self, '_launch_button_timer'):
            self._launch_button_timer = QTimer(self)
            self._launch_button_timer.setInterval(180)
            self._launch_button_timer.timeout.connect(self._advance_launch_button_animation)
        self._launch_button_generation = getattr(self, '_launch_button_generation', 0) + 1
        self._launch_button_frame = 0
        self.launch_btn.setText('启动中…')
        if is_animations_enabled():
            self._launch_button_timer.start()

    def _advance_launch_button_animation(self):
        self._launch_button_frame = (self._launch_button_frame + 1) % 4
        if self.home_panel.tabs.currentIndex() != self.home_panel._server_tab_index:
            self.launch_btn.setText('启动中' + '·' * self._launch_button_frame)

    def _stop_launch_button_animation(self):
        self._launch_button_generation = getattr(self, '_launch_button_generation', 0) + 1
        timer = getattr(self, '_launch_button_timer', None)
        if timer is not None:
            timer.stop()
        if self.home_panel.tabs.currentIndex() != self.home_panel._server_tab_index:
            self.launch_btn.setText(t('VERSION_HOME_LAUNCH_GAME'))

    def _show_launch_button_success(self):
        timer = getattr(self, '_launch_button_timer', None)
        if timer is not None:
            timer.stop()
        self._launch_button_generation = getattr(self, '_launch_button_generation', 0) + 1
        generation = self._launch_button_generation
        if self.home_panel.tabs.currentIndex() != self.home_panel._server_tab_index:
            self.launch_btn.setText('✓ 启动成功')
        QTimer.singleShot(1800, lambda: self._stop_launch_button_animation()
                          if self._launch_button_generation == generation else None)

    def launch_selected(self):
        """启动当前选中版本:准备 Java → 拼命令 → 拉起进程 → 日志实时显示"""
        v = self.selected_version
        if v is None:
            self.statusBar().showMessage("请先在列表里选中一个版本")
            return
        if self.game_process and self.game_process.poll() is None:
            self.statusBar().showMessage("游戏正在运行中,请先退出再启动")
            return
        if (self._launch_task is not None and self._launch_task.is_running) or self.download_tasks.is_running:
            self.statusBar().showMessage("正在准备或安装，等这一小步完成再启动吧")
            return

        self.statusBar().showMessage(f"正在获取 {v['id']} 的启动信息...")
        self._running_instance_id = v["id"]   # 实例 id(= 游戏目录名),供退出后自动 debug 定位日志

        v = dict(v)
        from copy import deepcopy
        from settings import update_setting
        launch_settings = deepcopy(self.settings)
        game_root, runtime_root = paths.GAME_DIR, paths.RUNTIME_DIR
        service = GameLaunchService(
            lambda: game_root, lambda: runtime_root, lambda: launch_settings,
            lambda changed: update_setting('ms_credentials', changed.get('ms_credentials', {})),
            lambda identity: os.path.join(game_root, 'versions', identity)
            if launch_settings.get('version_isolation') else game_root)
        task = BackgroundTask(lambda current: service.prepare(
            v, status_cb=current.report_status, progress_cb=current.report_progress), self)
        self._launch_task = task
        self.launch_btn.setEnabled(False)
        self._start_launch_button_animation()
        self._dl_log = []
        self._dl_progress = (0, 1)
        self.dl_indicator.set_progress(0, 1)
        self.dl_indicator.setToolTip("正在准备启动，点击查看详情")
        self.dl_indicator.show()
        task.status.connect(self._on_download_status)
        task.progress.connect(self._on_download_progress)
        task.failed.connect(self._on_launch_prepare_failed)
        task.cancelled_signal.connect(self._on_download_cancelled)
        task.succeeded.connect(lambda plan: self._start_prepared_game(plan, v)
                               if paths.GAME_DIR == game_root else self._on_launch_prepare_failed("游戏目录已经变了，请重新点击启动"))
        task.start()

    def _on_launch_prepare_failed(self, error):
        self._stop_launch_button_animation()
        self.launch_btn.setEnabled(True)
        self.dl_indicator.set_failed(True)
        self.dl_indicator.setToolTip("启动准备失败，点击查看状态与日志")
        QMessageBox.warning(self, "启动准备没完成", redact_text(error, self.settings))

    def _start_prepared_game(self, plan, v):
        from memory_launch_card import offer_memory_actions
        if offer_memory_actions(self, plan, v, self._start_game_after_memory):
            return
        self._start_game_after_memory(plan, v)

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

        # 游戏内 AI 通道:关闭 → 游戏启动前卸载本地模型(llama-server),把内存让给游戏;
        # 开启 → 可能用本地模型(看 ai_strategy),保持加载(游戏内 AI 通道)
        ai_in_game = str(self.settings.get("ai_in_game", "off") or "off").strip().lower()
        if ai_in_game == "off":
            self.ai_dock.stop_local_engine()

        try:
            if exit_after:
                self.game_process = self.game_processes.start(cmd, java_exe, game_dir, independent=True)
            else:
                self.game_process = self.game_processes.start(cmd, java_exe, game_dir)
        except Exception as e:
            self._stop_launch_button_animation()
            self.statusBar().showMessage(f"启动失败: {e}")
            self.dl_indicator.set_failed(True)
            self.dl_indicator.setToolTip("启动失败，点击查看状态与日志")
            self.launch_btn.setEnabled(True)
            return

        self._show_launch_button_success()
        self.dl_indicator.set_completed(True)
        self.dl_indicator.setToolTip("游戏已启动，点击查看状态与日志")

        from memory_policy import track_process
        track_process(self.game_process, os.path.join(paths.GAME_DIR, 'versions', v['id']))

        # 只在进程确实已拉起后记录，下载/Java/命令拼装失败不会污染下次默认选择。
        if self.settings.get("last_played_instance") != v["id"]:
            self.settings["last_played_instance"] = v["id"]
            try:
                save_settings(self.settings)
            except Exception:
                pass

        # 运行实例指示:登记并刷新底部标签
        self._running_instances.add(d["id"])
        self._update_running_label()
        # 游戏内 AI 通道(ai_in_game=cloud/local):启动 .bridge/ai_request↔ai_reply 轮询器
        self._start_in_game_ai(v["id"])

        # 通知技能系统:游戏已启动(自动重启等技能开始工作)
        self.skill_mgr.on_game_start(self.game_process, self._running_instance_id)

        # 主动避让(§5):告诉 AI 面板游戏在跑,本地推理降为低于游戏优先级/暂停(ai_in_game=local 时保持)
        try:
            self.ai_dock.set_game_running(self.game_process)
        except Exception:
            pass

        # 记录本次运行起点,用于判断"本次是否新产生了崩溃报告"(即使退出码为 0)
        self._game_started_at = time.time()
        if exit_after:
            from memory_launch_card import exit_when_ready
            exit_when_ready(self, self.game_process)

    def _on_game_log_line(self, line: str):
        line = redact_text(line, self.settings)
        self.log_view.appendPlainText(line)
        self.skill_mgr.on_game_log(line)

    def _on_game_process_exited(self, code: int):
        self._stop_launch_button_animation()
        self.launch_btn.setEnabled(True)
        self.statusBar().showMessage(f"游戏进程已退出(退出码 {code})")
        inst_id = getattr(self, "_running_instance_id", None)
        if inst_id:
            self._running_instances.discard(inst_id)
        self._update_running_label()
        self.skill_mgr.on_game_stop(code)
        try:
            self.ai_dock.set_game_stopped()
        except Exception:
            pass
        self._stop_in_game_ai()
        if code not in (0, None):
            self.dl_indicator.set_failed(True)
            self.dl_indicator.setToolTip(f"游戏异常退出（{code}），点击查看日志")
            self._auto_debug(code)
        elif self._detect_log_crash():
            self.dl_indicator.set_failed(True)
            self.dl_indicator.setToolTip("发现崩溃报告，点击查看日志")
            self._auto_debug(0)

    def _start_in_game_ai(self, instance_id: str):
        """游戏内 AI(ai_in_game 开启):启动 InGameAI 轮询器(读 .bridge/ai_request.json)。
        目标实例在 launch_selected 里用 v['id'](游戏目录名)。"""
        try:
            if str(self.settings.get("ai_in_game", "off") or "off").strip().lower() == "off":
                return
            from in_game_ai import InGameAI, make_answerer
            ai = InGameAI(instance_id,
                          make_answerer(win=self, settings=self.settings),
                          poll=1.0, game_dir=paths.GAME_DIR)
            ai.start()
            self._in_game_ai = ai
            self.statusBar().showMessage(
                f"游戏内 AI 已开启({instance_id}),进游戏敲 /ai 试试")
        except Exception as e:
            self.statusBar().showMessage(f"游戏内 AI 启动失败: {type(e).__name__}: {e}")

    def _stop_in_game_ai(self):
        ai = getattr(self, "_in_game_ai", None)
        if ai:
            try:
                ai.stop()
            except Exception:
                pass
            self._in_game_ai = None

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
        inst_id = getattr(self, "_running_instance_id", None)
        game_dir = self.game_dir_for(inst_id) if inst_id else paths.GAME_DIR
        return detect_crash(game_dir, getattr(self, "_game_started_at", 0))

    def _auto_debug(self, code: int):
        """游戏异常退出(退出码非 0 或检测到本次崩溃):自动抓最新日志 + 崩溃报告,问用户是否让 AI 分析"""
        inst_id = getattr(self, "_running_instance_id", None)
        game_dir = self.game_dir_for(inst_id) if inst_id else paths.GAME_DIR
        msg = collect_crash_report(game_dir, code)
        preview = msg[:400] + ("…" if len(msg) > 400 else "")
        if QMessageBox.question(
                self, "游戏异常退出",
                f"{preview}\n\n要让 AI 助手分析原因并给出解决办法吗?") == QMessageBox.StandardButton.Yes:
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
        from instance_catalog_service import fingerprint
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
            from instance_catalog_service import fingerprint
            if fingerprint(paths.GAME_DIR) == getattr(self, '_instance_fingerprint', None):
                return
            self.refresh_instances()
        except Exception as e:
            self._log_feedback(f"实例目录变动刷新失败:{e}", "警告")

    def _resource_download(self, hit, version, inst, target_dir, sub_dir):
        """资源中心下载回调:把项目下载到目标实例的对应目录(mods/shaderpacks/...)"""
        if hit.get("source") == "curseforge":
            if not target_dir:
                self.statusBar().showMessage("未选择安装位置")
                return
            if not isinstance(version, dict) or not version.get("file_id"):
                self.statusBar().showMessage("请先在“手动下载”中选择一个 CurseForge 文件版本")
                return
            title = hit.get("title") or "CurseForge Mod"
            project_id = hit.get("curseforge_id")
            file_id = version["file_id"]

            def worker(status, progress):
                try:
                    from curseforge import download_mod
                    filename = download_mod(project_id, file_id, target_dir, progress_callback=progress)
                    status(f"✅ 已下载 {filename} → {sub_dir}")
                except Exception as e:
                    status(f"❌ 下载 CurseForge Mod {title} 失败: {e}")

            self._run_download(worker)
            return
        slug = hit["slug"]
        if not target_dir:
            self.statusBar().showMessage("未选择安装位置")
            return
        # Pack version tags are guidance, not an exact install requirement.
        # A chosen Modrinth version ID wins over these preference hints.
        if sub_dir == "shaderpacks":
            gv = None
        elif sub_dir in ("datapacks", "resourcepacks"):
            gv = inst.get("base") if inst else None
        else:
            gv = (inst["base"] if inst else "1.21.1") or "1.21.1"
        loader = (inst["loader"] if inst else None)
        # Mod 按加载器过滤;光影/数据包/资源包一般不区分加载器
        use_loader = loader if sub_dir == "mods" else None

        # 正向依赖提示(灵感 #4):下载 Mod 前,解析该版本依赖,提示"需要什么/冲突";
        # 用户可一并安装缺少的必需依赖。仅 Mod 下载时提示,光影/数据包等跳过。
        extra_deps = []
        if sub_dir == "mods":
            try:
                from modrinth import (dependency_is_installed,
                                      installed_mod_identifiers, resolve_dependencies)
                deps = resolve_dependencies(slug, gv, use_loader, version)
            except Exception:
                deps = None
            if deps:
                installed_ids = installed_mod_identifiers(target_dir)
                missing = [dep for dep in deps["required"]
                           if not dependency_is_installed(dep, installed_ids)]
                lines = [hit.get("title", slug) + " 的依赖提示:"]
                if missing:
                    lines.append("缺少的必需前置:\n" + "\n".join(f" · {d['title']}" for d in missing))
                if deps["optional"]:
                    lines.append("可选(选装):\n" + "\n".join(f" · {d['title']}" for d in deps["optional"]))
                if deps["incompatible"]:
                    lines.append("⚠ 冲突(不建议同装):\n" + "\n".join(f" · {d['title']}" for d in deps["incompatible"]))
                if len(lines) > 1:
                    cont = QMessageBox.question(
                        self, "依赖提示",
                        "\n".join(lines) +
                        "\n\n是否继续下载该 Mod?(缺少的必需依赖会尝试一并安装到该实例)",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                    if cont != QMessageBox.StandardButton.Yes:
                        return
                    extra_deps = missing

        def worker(status, progress):
            from modrinth import (dependency_is_installed, download_mod,
                                  installed_mod_identifiers)
            installed_ids = installed_mod_identifiers(target_dir) if extra_deps else set()
            for dep in extra_deps:
                dep_slug = dep["slug"]
                if dependency_is_installed(dep, installed_ids):
                    status(f"已跳过已有前置: {dep['title']}")
                    continue
                try:
                    dn = download_mod(dep_slug, gv, use_loader, target_dir, progress_callback=progress)
                    if dn:
                        status(f"依赖已装:{dn}")
                        installed_ids = installed_mod_identifiers(target_dir)
                except Exception as e:
                    status(f"依赖 {dep_slug} 装入失败(跳过): {e}")
            filename = download_mod(slug, gv, use_loader, target_dir,
                                    version_number=version,
                                    progress_callback=progress)
            if not filename:
                if gv:
                    target = f"{gv}{'+' + use_loader if use_loader else ''}"
                    raise RuntimeError(f"{slug} 没有适用于 {target} 的可下载文件；请在手动下载中更换版本或筛选条件")
                raise RuntimeError(f"{slug} 所选版本没有可下载文件；请在手动下载中更换版本")
            status(f"✅ 已下载 {filename} → {sub_dir}")

        self._run_download(worker)

    def _resource_download_modpack(self, hit, version):
        """资源中心-整合包下载:下载 Modrinth 的 .mrpack 并导入成【新实例】。
        (整合包是一键全集,不装进已有实例,而是创建一个新实例。)"""
        import shutil as _sh
        slug = hit["slug"]
        title = hit.get("title", slug)

        def worker(status, progress):
            from modpack import import_modpack
            from modrinth import download_modpack
            tmp = os.path.join(paths.GAME_DIR, "downloads", "modpack_tmp")
            try:
                os.makedirs(tmp, exist_ok=True)
            except Exception:
                pass
            # 1) 下载 .mrpack
            try:
                status(f"下载整合包 {title}...")
                local = download_modpack(slug, tmp, version_number=version,
                                         progress_callback=progress)
                if not local:
                    status("❌ 该整合包没有可下载的 .mrpack 文件")
                    return
            except Exception as e:
                status(f"❌ 下载整合包失败:{type(e).__name__}: {e}")
                return
            # 2) 导入成新实例(.mrpack 清单自带 MC 版本/加载器/文件,无需手动填)
            try:
                status("导入整合包(自动装基础+加载器+全部 mod,可能要几分钟)...")
                inst = import_modpack(local, paths.GAME_DIR,
                                      status_callback=status,
                                      progress_callback=progress)
                status(f"✅ 整合包导入完成:{inst}")
            except Exception as e:
                status(f"❌ 整合包导入失败:{type(e).__name__}: {e}"
                       "(同名实例可先在「我的版本」删除或改名后重试)")
            finally:
                try:
                    _sh.rmtree(tmp, ignore_errors=True)
                except Exception:
                    pass

        self._run_download(worker)

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

    def launch_selected_instance(self):
        """启动"我的版本"里选中的实例(双击或按钮)"""
        item = self.instance_list.currentItem()
        if item is None:
            self.statusBar().showMessage("请先选一个实例(双击也可以直接启动)")
            return
        inst = item.data(Qt.ItemDataRole.UserRole)
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
        from ui_style import popup_menu_style
        menu.setStyleSheet(popup_menu_style())
        config_menu = menu.addMenu("一键配置")
        config_menu.addAction("Bridge Mod（推荐）…", lambda: self._one_click_bridge_for(inst))
        rcon_menu_item = config_menu.addAction("RCON（临时方案）…", lambda: self._one_click_rcon_for(inst))
        rcon_menu_item.setToolTip("临时方案:需要 Lan Server Properties + 进世界按 ESC → 对局域网开放")
        # 联机 mod 一键配置:按实例版本+加载器判断支持才显示(不支持不出现)
        self._add_online_mod_menu_items(config_menu, inst)
        menu.addAction("重命名实例…", lambda: self._rename_instance(inst))
        menu.addAction("备份实例", lambda: self.backup_current_instance(inst))
        menu.addAction("打开实例目录", lambda: open_path(self.game_dir_for(inst["id"])))
        menu.addSeparator()
        menu.addAction("删除实例…", lambda: self._delete_instance(inst))
        menu.exec(global_pos)

    def _current_instance(self):
        """「我的版本」当前选中的实例;没选中返回 None"""
        item = self.instance_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _one_click_config_kind(self, kind: str):
        """「我的版本」首页「一键配置 ▾」按钮 → 按用户选择执行 bridge-mod / RCON / 自动。"""
        inst = self._current_instance()
        if inst is None:
            QMessageBox.information(self, "一键配置", "请先在「我的版本」里选中一个实例")
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
            QMessageBox.information(self, "一键配置", "请先在「我的版本」里选中一个实例")
            return
        self._one_click_config_for(inst)

    # ---- 一键配置:bridge-mod(正式方案,本地指令口) ----
    def _one_click_bridge_current(self):
        inst = self._current_instance()
        if inst is None:
            QMessageBox.information(self, "一键配置", "请先在「我的版本」里选中一个实例")
            return
        self._one_click_bridge_for(inst)

    def _one_click_bridge_for(self, inst):
        """一键配置 bridge-mod(本地指令口,推荐):检测 → 确认 → 自动下载安装。
        兼容(能自动发现该加载器+版本)则下载;不兼容 → 明确提示 + 说明可改走 RCON。
        已装但版本旧(check_bridge_mod=outdated)→ 提示可更新到最新。"""
        import bridge_mod_dist
        inst_dir = self.game_dir_for(inst["id"])
        loader = inst.get("loader")
        if loader not in ("fabric", "forge", "neoforge"):
            QMessageBox.information(self, f"一键配置 · {inst['id']}",
                                    "该实例没有加载器(原版),bridge-mod 是 mod 需要加载器。\n"
                                    "先给这个实例装个 Fabric/Forge 等加载器再回来。")
            return
        status = bridge_mod_dist.check_bridge_mod(inst_dir, loader, inst["base"])
        if status == "up_to_date":
            QMessageBox.information(self, f"一键配置 · {inst['id']}",
                                    "✅ bridge-mod 已就绪且是最新:重进世界即可用本地指令口\n"
                                    "(无需'对局域网开放',指令结果可精确回传)。")
            return
        if status == "incompatible":
            ret = QMessageBox.question(
                self, f"一键配置 · {inst['id']}",
                "检测到当前 mods 目录中有其他 MC 版本或加载器的 bridge-mod。\n\n"
                f"将替换为适用于 {inst['base']}+{loader} 的版本吗？")
            if ret == QMessageBox.StandardButton.Yes:
                self._install_bridge_mod(inst)
            return
        if status == "outdated":
            ret = QMessageBox.question(
                self, f"一键配置 · {inst['id']}",
                f"⚠️ 检测到已装 bridge-mod 但版本较旧({inst['base']}+{loader})。\n\n"
                "自动更新到最新版吗?(会覆盖旧的 jar)")
            if ret == QMessageBox.StandardButton.Yes:
                self._install_bridge_mod(inst)
            return
        # status == "not_installed" (或不兼容组合的兜底检查)
        info = bridge_mod_dist.bridge_mod_info(loader, inst["base"])
        if info is None:
            # 不兼容:明确提示,并引导走 RCON 临时方案
            QMessageBox.information(
                self, f"一键配置 · {inst['id']}",
                f"💡 bridge-mod 暂不兼容 {inst['base']}+{loader}(版本表/自动发现都没有这个组合)。\n\n"
                "可以改用临时方案 RCON:功能略弱(指令结果不精确),但覆盖更多版本。\n"
                "要换 RCON 的话,点菜单里的「一键配置 RCON」。")
            return
        ret = QMessageBox.question(self, f"一键配置 · {inst['id']}",
                                   f"未安装 bridge-mod(本地指令口,推荐)。\n\n"
                                   f"检测到 {inst['base']}+{loader} 可用的 bridge-mod v{info['version']},"
                                   "自动下载安装吗?")
        if ret != QMessageBox.StandardButton.Yes:
            return
        self._install_bridge_mod(inst)

    # ---- 一键配置:RCON(临时方案,需要开局域网) ----
    def _one_click_rcon_current(self):
        inst = self._current_instance()
        if inst is None:
            QMessageBox.information(self, "一键配置", "请先在「我的版本」里选中一个实例")
            return
        self._one_click_rcon_for(inst)

    def _one_click_rcon_for(self, inst):
        """一键配置 RCON(临时方案):需要 Lan Server Properties + 进世界后手动对局域网开放"""
        from game_command import ensure_rcon_config, has_lan_server_properties, read_rcon_config
        inst_dir = self.game_dir_for(inst["id"])
        loader = inst.get("loader")
        if read_rcon_config(inst_dir):
            QMessageBox.information(self, f"一键配置 · {inst['id']}",
                                    "✅ RCON 已就绪。\n"
                                    "(临时方案:进世界后按 ESC → 对局域网开放,RCON 才监听端口)")
            return
        if not has_lan_server_properties(inst_dir):
            if loader not in ("fabric", "forge", "neoforge"):
                QMessageBox.information(
                    self, f"一键配置 · {inst['id']}",
                    "该实例没有加载器(原版),而 Lan Server Properties 需要加载器。\n"
                    "先给这个实例装个加载器再回来。")
                return
            ret = QMessageBox.question(
                self, f"一键配置 · {inst['id']}",
                "临时方案需要 Lan Server Properties mod\n"
                "(自动开 RCON,但每次进世界需手动'对局域网开放')。\n\n"
                "是否自动从 Modrinth 下载并安装?")
            if ret != QMessageBox.StandardButton.Yes:
                return
            self._install_lan_server_properties(inst)
            return
        msg = ensure_rcon_config(inst_dir)
        if "\n" in msg:
            QMessageBox.information(self, f"一键配置 · {inst['id']}", msg)
        else:
            self.statusBar().showMessage(msg)

    def _add_online_mod_menu_items(self, menu, inst):
        """在实例右键菜单加「一键配置 <联机mod>」项——仅当该实例版本+加载器支持时才显示。"""
        import lan_tools
        gv = inst.get("base")
        loader = inst.get("loader") or ""
        if loader not in ("fabric", "forge", "neoforge"):
            return
        for slug, name in lan_tools.ONLINE_MODS.items():
            try:
                ok = lan_tools.mod_supported(slug, gv, loader)
            except Exception:
                continue
            if ok:
                it = menu.addAction(
                    f"一键配置 {name}…",
                    lambda _c=False, s=slug: self._one_click_online_mod_for(inst, s))
                it.setToolTip(f"{name}:{gv}+{loader} 可用,自动下载安装")

    def _one_click_online_mod_for(self, inst, slug: str):
        """一键配置联机 mod(Essential / e4mc):按版本+加载器判断是否支持,支持才装。
        已装 → 提示就绪;不支持 → 说明不支持;支持且未装 → 确认后后台下载。"""
        import lan_tools
        inst_dir = self.game_dir_for(inst["id"])
        loader = inst.get("loader") or ""
        gv = inst["base"]
        name = lan_tools.ONLINE_MODS.get(slug, slug)
        # 不支持 → 明确说明
        if loader not in ("fabric", "forge", "neoforge"):
            QMessageBox.information(self, f"一键配置 · {inst['id']}",
                                    f"该实例没有加载器(原版),{name} 是 mod 需要加载器。\n"
                                    "先装个 Fabric/Forge 再回来。")
            return
        if not lan_tools.mod_supported(slug, gv, loader):
            QMessageBox.information(self, f"一键配置 · {inst['id']}",
                                    f"{name} 暂不支持 {gv}+{loader}。\n"
                                    "可以换个版本,或到「联机」看别的方案。")
            return
        # 已装?
        mods_dir = os.path.join(inst_dir, "mods")
        has = any(name and (slug in f.lower() or name.split("(")[0].strip().lower() in f.lower())
                  for f in os.listdir(mods_dir) if f.endswith(".jar")) if os.path.isdir(mods_dir) else False
        ret = QMessageBox.question(
            self, f"一键配置 · {inst['id']}",
            (f"✅ {name} 支持 {gv}+{loader}。\n\n"
             f"{'已检测到,重装/更新吗?' if has else '自动从 Modrinth 下载并安装到该实例吗?'}"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return
        self.statusBar().showMessage(f"正在为 {inst['id']} 安装 {name}…")

        def worker(status_cb, progress_cb):
            try:
                msg = lan_tools.install_online_mod(
                    slug, gv, loader, mods_dir, progress_callback=progress_cb)
            except Exception as e:
                raise RuntimeError(f"安装失败:{type(e).__name__}: {e}") from e
            status_cb(msg)

        self._run_download(worker)

    def _one_click_config_for(self, inst):
        """对指定实例执行一键配置(自动:bridge-mod 优先,不兼容则提示走 RCON)。
        菜单里两个显式入口(bridge / RCON)之外的兜底逻辑。
        已装但版本旧(outdated)→ 走 _one_click_bridge_for(触发更新提示)。"""
        import bridge_mod_dist
        inst_dir = self.game_dir_for(inst["id"])
        status = self.statusBar()
        loader = inst.get("loader")
        if loader in ("fabric", "forge", "neoforge"):
            bstatus = bridge_mod_dist.check_bridge_mod(inst_dir, loader, inst["base"])
            if bstatus != "not_installed":
                # 已装(up_to_date / outdated)→ 交给 _one_click_bridge_for 处理(最新=提示就绪;旧=提示更新)
                self._one_click_bridge_for(inst)
                return
            if bridge_mod_dist.bridge_mod_info(loader, inst["base"]):
                self._one_click_bridge_for(inst)
                return
        # bridge-mod 不可用(无加载器 / 不兼容)→ 提示原因,然后走 RCON 临时方案
        if status:
            status.showMessage(
                f"bridge-mod 暂不可用于 {inst['base']}+{loader or '原版'},改走 RCON 临时方案")
        self._one_click_rcon_for(inst)

    def _install_bridge_mod(self, inst):
        """后台下载 bridge-mod(本地指令口)到实例 mods 目录"""
        import bridge_mod_dist
        self.statusBar().showMessage(f"正在为 {inst['id']} 下载 bridge-mod…")

        def worker(status_cb, progress_cb):
            try:
                fn = bridge_mod_dist.download_bridge_mod(
                    self.game_dir_for(inst["id"]), inst["loader"], inst["base"],
                    progress_callback=progress_cb)
            except Exception as e:
                raise RuntimeError(f"下载失败:{e}") from e
            status_cb(f"bridge-mod 已安装:{fn}\n"
                      "重进世界后即可用本地指令口(无需对局域网开放)。")

        self._run_download(worker)

    def _install_lan_server_properties(self, inst):
        """后台下载 Lan Server Properties 到实例,装好后自动写 RCON 配置"""
        self.statusBar().showMessage(f"正在为 {inst['id']} 下载 Lan Server Properties…")

        def worker(status_cb, progress_cb):
            mods_dir = os.path.join(self.game_dir_for(inst["id"]), "mods")
            try:
                filename = download_mod("lan-server-properties", inst["base"],
                                        inst["loader"], mods_dir,
                                        progress_callback=progress_cb)
            except Exception as e:
                raise RuntimeError(f"下载失败:{e}") from e
            if not filename:
                status_cb(f"没有 {inst['base']}+{inst['loader']} 的版本,换个版本试试")
                return False
            # 装好 → 自动写 RCON 配置
            from game_command import ensure_rcon_config
            cfg = ensure_rcon_config(self.game_dir_for(inst["id"]))
            status_cb(f"Lan Server Properties 已安装:{filename}\n{cfg}")

        self._run_download(worker)

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
                self.details_placeholder.setText('请先在“我的实例”中选择一个服务端。')
                self.details_stack.setCurrentWidget(self.details_placeholder)
            else:
                self.server_details.set_server(server)
                self.details_stack.setCurrentWidget(self.server_details)
        else:
            self.main_tabs.setTabText(self._details_tab_idx, t('INSTANCE_DETAILS'))
            inst = self.home_panel.current_instance()
            if inst is None:
                self.details_placeholder.setText('请先在“我的实例”中选择一个实例。')
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
                QMessageBox.information(self, '实例详情', '请先在右侧选中一个服务端。')
                return
            self._show_server_details(server)
            return
        inst = home.current_instance()
        if inst is None:
            QMessageBox.information(self, '实例详情', '请先在右侧选中一个实例。')
            return
        self._show_instance_details(inst)

    def _smart_import_path(self, path: str):
        """「导入服务端 → 智能导入」:交给既有的智能导入流程。"""
        from smart_import_ui import start_smart_import
        start_smart_import(self, path)

    def _on_main_tab_changed(self, idx: int):
        """主标签页切换时短暂显现新页面。"""
        from ui_anim import reveal
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
            QMessageBox.information(self, t("INSTANCE_SETTINGS"),
                                    t("SELECT_AN_INSTANCE_ON_THE_RIGHT_FIRST"))
            return
        self.open_instance_manager(inst)

    def _on_login_changed(self):
        """首页登录卡片改了离线昵称 → 重读设置,刷新登录显示。"""
        self.settings = load_settings()
        self.home_panel.refresh_login()
        self.statusBar().showMessage(t("LOGIN_INFO_UPDATED"))

    def backup_current_instance(self, inst):
        """GUI 备份按钮(灵感 #6 补齐):手动备份一个实例"""
        from backup import backup_instance
        try:
            out = backup_instance(inst["id"], paths.GAME_DIR)
        except Exception as e:
            QMessageBox.warning(self, "备份失败", str(e))
            return
        self.statusBar().showMessage(f"已备份到:{out}")

    def _rename_instance(self, inst):
        """同步重命名安装目录、版本文件和继承引用。"""
        from PySide6.QtWidgets import QInputDialog
        from instance_metadata import rename_instance
        if self._running_instances or self.download_tasks.is_running or (self._launch_task is not None and self._launch_task.is_running):
            QMessageBox.information(self, "稍等一下", "游戏或安装任务还在运行，结束后再改名吧。")
            return
        name, accepted = QInputDialog.getText(
            self, "重命名实例",
            '新名称（中文、英文、数字和空格均可）：\n'
            '不能留空，不能包含 \\ / : * ? " < > |\n'
            '不能以下划线开头、以句点结尾，或使用 CON、NUL、COM1 等系统保留名。\n'
            '不能与已有实例重名。安装目录和版本文件会同步改名，存档与配置保留。',
            QLineEdit.EchoMode.Normal, inst.get("name") or inst["id"])
        if not accepted:
            return
        try:
            rename_instance(paths.GAME_DIR, inst["id"], name.strip())
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "名称暂时没改成", str(error))
            return
        new_id = name.strip()
        if self.settings.get('last_played_instance') == inst['id']:
            from settings import update_setting
            self.settings['last_played_instance'] = new_id
            try:
                update_setting('last_played_instance', new_id)
            except OSError as error:
                self._log_feedback(f'实例已改名，但最近游玩记录保存失败：{error}')
        self.refresh_instances()
        for index in range(self.instance_list.count()):
            item = self.instance_list.item(index)
            if (item.data(Qt.ItemDataRole.UserRole) or {}).get('id') == new_id:
                self.instance_list.setCurrentItem(item)
                break
        self.statusBar().showMessage(f"实例和安装目录已改名为：{new_id}")

    def _delete_instance(self, inst):
        """删除一个实例的安装文件(只删 versions/<id>，共用 gameDir 保留)。"""
        if inst['id'] in self._running_instances or self.download_tasks.is_running or (self._launch_task is not None and self._launch_task.is_running):
            QMessageBox.information(self, "稍等一下", "游戏正在运行，或文件还在准备中，结束后再删除实例吧。")
            return
        if QMessageBox.question(
                self, "确认删除",
                f"确定删除实例 {inst['id']} 吗?\n(只删该实例,共用文件保留)") != QMessageBox.StandardButton.Yes:
            return
        # ``game_dir_for`` 在关闭版本隔离时会返回整个 .minecraft；它只适合
        # 运行参数、存档和配置，绝不能作为删除目标。实例安装文件始终固定在
        # versions/<id>，从而保证删一个实例不会影响其他实例或共用游戏目录。
        instance_dir = os.path.join(paths.GAME_DIR, "versions", inst["id"])
        if os.path.isdir(instance_dir):
            shutil.rmtree(instance_dir, ignore_errors=True)
        self.statusBar().showMessage(f"实例已删除:{inst['id']}")
        self.refresh_instances()

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
        from mcp_server import serve
        serve()
        raise SystemExit(0)
    if "--mcp-http" in _sys.argv:
        # MCP Streamable-HTTP 模式:POST /mcp → 供「http」连接。--mcp-http [port]
        from mcp_server import serve_http
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
    from ui_style import apply_global_dark_palette, set_theme_mode
    set_theme_mode(load_settings().get('ui_theme', 'system'))
    apply_global_dark_palette(app)   # 系统深色 → 全局深色调色板,统一对话框/菜单/标签页

    # Protect one launcher data directory across processes on Windows, Linux,
    # and macOS. Keep the lock object alive for the full GUI lifetime.
    _instance_lock = None
    if not _CI_STARTUP_SMOKE:
        _instance_lock = QLockFile(os.path.join(paths.CONFIG_DIR, "launcher.lock"))
        _instance_lock.setStaleLockTime(0)
        if not _instance_lock.tryLock(0):
            if _instance_lock.error() == QLockFile.LockError.LockFailedError:
                answer = QMessageBox.question(
                    None,
                    "启动器已在运行",
                    "检测到这个数据目录已有一个启动器进程。\n\n"
                    "仍要再启动一个吗？多个窗口可能同时修改配置、下载或操作同一实例。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    raise SystemExit(0)
            else:
                QMessageBox.critical(
                    None,
                    "无法检查启动器是否已运行",
                    f"无法创建单实例锁文件：{_instance_lock.fileName()}\n"
                    "请检查 AMCL 文件夹的写入权限后重试。",
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
        from onboarding import OnboardingDialog
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
            lambda message=_rollback_notice: QMessageBox.information(
                window, "已恢复旧版本", message),
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
