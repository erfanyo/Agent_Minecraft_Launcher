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
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

import requests

from PySide6.QtCore import Qt, QSize, QTimer, QFileSystemWatcher
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
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
    QSplitter,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QDockWidget,
)

from downloader import download_with_mirror  # 下载工具:镜像 + 进度 + sha1 校验
import updater  # 自动更新(检查 GitHub 新版本 / 下载 / 替换)
from bridge_mod_dist import BRIDGE_MOD_VERSION  # bridge-mod 当前版本
from assistant import AIChatDock, permission_instructions  # AI 助手(右侧停靠对话栏)
from download_indicator import DownloadDetailWidget, DownloadIndicator  # 左下角下载指示器
from updater_dialog import UpdateDialog  # 检查更新对话框(独立模块)
from download_tab import DownloadTab  # 下载新实例选项卡(左侧菜单 + 分类面板)
from fetch_versions import fetch_version_detail, fetch_version_manifest  # 网络模块
from game_files import install_version_files  # 按清单安装依赖库和资源文件
import i18n  # 界面语言(跟随系统,可设置覆盖)
from i18n import t
from instance_wizard import OPTIMIZE_MODS, SHADER_MODS  # 可选 Mod 清单
from instances import scan_instances  # 实例扫描(与 CLI/AI 共用)
from java_manager import ensure_java  # Java 检测与自动安装
from launcher import build_launch_command, resolve_inherited_json  # 版本 JSON → 启动命令
from loaders import install_loader  # Fabric / Forge 加载器安装
from modpack import import_modpack as import_modpack_file  # 整合包导入
from modpack import heal_instance_json  # 旧版导入的整合包 json id 修正(自愈)
from modrinth import download_mod  # Modrinth 搜索与下载(含中文名支持)
import paths  # 游戏目录(可配置,设置/引导里可改)
from paths import GAME_DIR, RUNTIME_DIR  # 兼容旧引用(测试用);内部统一用 paths.GAME_DIR
from os_platform.openpath import open_path  # 跨平台打开文件/文件夹(替代 os.startfile)
from settings import load_settings, save_settings  # 启动器配置
from skill_manager import SkillManager, SkillManagerDialog  # 技能(运行时辅助)系统
from version_tree import fill_version_tree  # 版本树构建(与下载选项卡共用)





class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Agent Minecraft Launcher")
        self.setMinimumSize(700, 560)
        self.selected_version = None  # 记住当前选中的版本,供"下载"按钮使用
        self.settings = load_settings()  # 启动器配置(用户名/内存/版本隔离)
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
        from frameless_titlebar import FramelessTitleBar
        self._running_instances = set()
        self._running_label = QLabel("")     # 放在标题栏(悬停看具体实例)
        self.title_bar = FramelessTitleBar(self, "AMCL",
                                           trailing_widget=self._running_label)
        # 菜单栏已取消(2026-08-25):「文件/查看/设置/AI/联机/帮助」全部移除。
        # - 导入整合包 → 下载新资源 → 实例 →「导入整合包」按钮
        # - 检查更新 / 引导教程(重播) → 放到 设置 → 界面
        # - 打开游戏目录 / 清空实例 / 刷新版本列表 意义不大,不再放外层入口
        # 相关方法(load_versions/import_modpack/open_game_dir/clear_instances/open_update_dialog)仍保留可调用。

        # ---- Tab「我的实例」:仿 PCL2 首页(左 1/3 登录+当前选择+启动按钮,右 2/3 实例/更新日志/动态) ----
        from version_home import VersionHome
        tab_a = VersionHome()
        self.home_panel = tab_a                     # 保留引用,便于刷新登录显示等
        self.instance_list = tab_a.instance_list    # 版本列表(兼容旧引用:右键/视图/双击)
        self.launch_btn = tab_a.launch_btn          # 启动游戏大按钮
        # 旧行为保留:双击启动 + 启动按钮;刷新按钮已移除,切回「实例」标签页自动刷新
        self.instance_list.itemDoubleClicked.connect(self.launch_selected_instance)
        self.launch_btn.clicked.connect(self.launch_selected_instance)
        # 键盘导航(遥控器式):实例列表按回车 → 启动选中实例(itemActivated)
        tab_a.launch_requested.connect(lambda _inst: self.launch_selected_instance())
        tab_a.refresh_requested.connect(self.refresh_instances)
        # 新首页抛出的信号 → 启动器处理
        tab_a.open_instance_manager_requested.connect(self._home_open_instance_manager)
        tab_a.open_settings_requested.connect(self.open_settings)
        tab_a.login_changed.connect(self._on_login_changed)
        tab_a.one_click_config_requested.connect(self._one_click_config_kind)
        tab_a.import_modpack_requested.connect(self.import_modpack)
        tab_a.tutorial_requested.connect(self.open_tutorial)

        # ---- 「下载新资源」综合入口:左侧菜单 + 首页/实例/Mod/光影/数据包/资源包 ----
        from resource_center import ResourceCenter
        self.resource_center = ResourceCenter()
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

        # ---- 主选项卡(我的实例 / 实例详情 / 下载新资源 / 联机 / 设置) ----
        self.main_tabs = QTabWidget()
        from ui_style import tab_style, set_style
        set_style(self.main_tabs, tab_style)   # 外层标签页:圆角+字体放大(14px)
        self.main_tabs.addTab(tab_a, t("MY_INSTANCES"))
        self._my_inst_tab_idx = 0   # 「我的实例」= 主标签第 0 页(拖入文件 → 当作整合包安装)
        # 实例详情:放在「我的版本」右边;未选择实例时隐藏,选择后出现(带滑入/淡入动画)
        from instance_manager import InstanceManagerDialog
        self.instance_details = InstanceManagerDialog()
        self.instance_details.setObjectName("instance_details")
        self._inst_details_tab_idx = self.main_tabs.addTab(
            self.instance_details, t("INSTANCE_DETAILS"))
        self.main_tabs.setTabVisible(self._inst_details_tab_idx, False)
        tab_a.instance_selected.connect(self._on_instance_selected)
        self.main_tabs.addTab(self.resource_center, t("RESOURCES"))
        # 联机方案中心:改为「下载新资源」右侧的标签卡(卡片形式)
        from online_center import OnlineCenter
        self.online_center = OnlineCenter()
        self.online_center.setObjectName("online_center")
        self._online_tab_idx = self.main_tabs.addTab(self.online_center, t("MULTIPLAYER"))
        # 设置:改成"和下载新资源平级的标签卡",左菜单(游戏/界面/AI/镜像源)+ 右面板(非模态,引导遮罩可用)
        from settings_center import SettingsCenter
        self.settings_center = SettingsCenter(self.settings)
        self.settings_center.applied.connect(self._on_settings_applied)
        self.main_tabs.addTab(self.settings_center, t("SETTINGS"))

        # ---- 插件注册的主标签页(与 下载新资源/联机/设置 平级)----
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
        self.setCentralWidget(central)
        self._background = central
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
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.title_dock)
        # 修复 dock"放不回去":允许嵌套/标签 + 动画(拖出后能顺利拖回边缘复原)
        self.setDockOptions(QMainWindow.DockOption.AllowNestedDocks
                            | QMainWindow.DockOption.AllowTabbedDocks
                            | QMainWindow.DockOption.AnimatedDocks)

        # ---- AI 助手/游戏日志:停靠在右侧,做成"标签页"(tab)形式 ----
        # 允许拖动(可浮出成子窗口)、可关闭;标签页之间点击切换显示/隐藏。
        self.ai_dock = AIChatDock(self, self.settings)
        self.ai_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.ai_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                                 | QDockWidget.DockWidgetFeature.DockWidgetFloatable
                                 | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.ai_dock)
        self.ai_dock.visibilityChanged.connect(self._on_ai_visibility)
        self.ai_dock.show()

        # 游戏日志已挪进实例详情,不再有独立 dock(AI 助手单独在右侧作标签页)

        # ---- AI 助手被 × / 隐藏时:收窄成贴在右边缘的小条(留「展开」) ----
        self._build_ai_strip()

        # ---- 技能管理器(游戏运行时辅助功能,可插拔) ----
        self.skill_mgr = SkillManager(self, self.settings)

        # 游戏进程相关的运行时状态
        self.game_process = None
        self.log_queue = queue.Queue()
        self.log_timer = None
        self._dl_queue = queue.Queue()     # 下载任务的状态/进度队列(线程 → 定时器)
        self._dl_timer = None

        # 应用视图模式(图标/列表,来自设置)
        self.set_view_mode(self.instance_list,
                           self.settings.get("view_icons_instances", False), "instances")

        self.refresh_instances()
        self.statusBar().showMessage("就绪")

        # 监听 versions/ 目录文件变动 → 实例列表自动刷新(如外部新增/删除实例文件夹)
        self._setup_instance_watcher()

        # 左下角下载指示器:下载时显示 ⬇ 圆环进度,点击查看详情
        self._dl_log = []                      # 本次下载的状态消息流
        self._dl_progress = (0, 1)
        # 下载球 = 悬浮球:置顶、可拖动,默认在内容区右下角(AI 子窗口左侧、主窗口侧外部)
        self.dl_indicator = DownloadIndicator(self)
        self.dl_indicator.make_floating()
        self.dl_indicator.clicked.connect(self.open_download_detail)
        self.dl_indicator.shown.connect(self._place_download_ball)
        self.dl_indicator.hide()

        # 拖放:把文件(整合包)拖进窗口 → 覆盖层提示"松手尝试安装" → 松手导入
        self.setAcceptDrops(True)
        self._build_drop_overlay()

        # 运行中的实例指示:已在标题栏显示"已有 x 个运行中的实例"(悬停看具体是哪个)
        # (self._running_instances / _running_label 已在创建标题栏时初始化)
        self._update_running_label()

        # 状态栏隐藏:信息走启动器日志 / 下载球 / 提示条;自绘状态栏留待后续
        self.statusBar().hide()
        self.apply_background()   # AI dock 已建好,再刷一次让 dock 也带上壁纸(幂等)

    # ---- 设置 ----
    def open_settings(self, tab: str | None = None):
        """打开设置:切换到「设置」标签卡(非模态,现为顶部标签页)。
        tab 可选 "mirror":直接切到镜像源小节(设置菜单 → 镜像源…)"""
        from settings_dialog import SettingsDialog
        idx = self.main_tabs.indexOf(self.settings_center)
        if idx >= 0:
            self.main_tabs.setCurrentIndex(idx)
            if tab == "mirror":
                self.settings_center.shell.switch_by_label(t("MIRROR"))
            return
        # 兜底:兼容未挂tab的旧路径(一般不会走到)
        dlg = SettingsDialog(self.settings, self, tab=tab)
        if dlg.exec():
            self.settings = dlg.settings
            self._on_settings_applied()

    def _on_settings_applied(self):
        """设置(标签卡)保存后:刷新本窗口与各处联动。"""
        s = self.settings_center.settings
        self.settings = s
        from ui_anim import set_animations_enabled
        set_animations_enabled(s.get("ui_animations_enabled", True))
        self.ai_dock.settings = s
        self.ai_dock.update_vision_ui()   # 多模态开关变化 → 立即显示/隐藏图片按钮
        self.ai_dock.update_local_status()   # 本地模型 provider 切换 → 刷新状态
        self.ai_dock.maybe_preload_local()   # 切到内置本地模型 → 空闲期预热 server(§8.2)
        self.skill_mgr.settings = s
        self.resource_center.set_ui_mode(s.get("ui_mode", "beginner"))
        self.refresh_instances()   # 游戏目录可能被改了,重新扫描
        self._watch_versions_dir()   # 游戏目录若变更,把监听指向新的 versions/
        self.apply_background()   # 壁纸/遮罩变化 → 立即生效
        self.statusBar().showMessage("设置已保存")

    def apply_background(self):
        """按设置应用背景壁纸 + 遮罩 + 面板/按钮/文本框透明化(阶段 2 · 决策 2)。"""
        from ui_background import load_wallpaper, mask_strength, input_style_qss
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
            new_qss = input_style_qss() if active else ""
            if app.styleSheet() != new_qss:   # 样式串没变就别重设,避免无谓 re-polish
                app.setStyleSheet(new_qss)
        # 壁纸激活态变了 → 切换面板/按钮不透明度并全量重刷样式(否则跳过,省成本)
        if is_wallpaper_active() != active:
            set_wallpaper_active(active)
            from ui_style import refresh_theme
            refresh_theme()

    def _recompute_wallpaper(self):
        """按当前中央区尺寸 + 壁纸源,重算共享壁纸(一张画布),并设置中央区与 AI dock 视口。"""
        from ui_background import prepare_shared_wallpaper
        pix = getattr(self, "_wallpaper_source", None)
        mask = getattr(self, "_wallpaper_mask", 0.6)
        bg = getattr(self, "_background", None)
        if pix is None or bg is None:
            self._wallpaper_scaled = None
            self._wallpaper_ox = self._wallpaper_oy = 0
            if bg is not None:
                bg.clear()
            self._sync_ai_wallpaper()
            return
        scaled, ox, oy = prepare_shared_wallpaper(pix, bg.size(), self._ai_dock_width())
        self._wallpaper_scaled = scaled
        self._wallpaper_ox = ox
        self._wallpaper_oy = oy
        if scaled is not None:
            bg.set_shared_view(scaled, ox, oy, mask)
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

    def showEvent(self, ev):
        super().showEvent(ev)
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

    def closeEvent(self, event):
        """窗口关闭:卸载本地 AI 引擎(llama-server),确保无残留进程。"""
        if hasattr(self, "ai_dock"):
            try:
                self.ai_dock.shutdown()
            except Exception:
                pass
        super().closeEvent(event)

    # ---- AI 助手 ----
    def _toggle_ai(self, checked: bool):
        """显示/隐藏右侧 AI 对话栏(靠其自身标题/关闭控制,不再有菜单入口)"""
        if hasattr(self, "ai_dock"):
            self.ai_dock.setVisible(bool(checked))

    def open_online_center(self):
        """打开联机方案中心:改为切到「联机」标签卡(卡片形式,非模态)"""
        if hasattr(self, "_online_tab_idx"):
            self.main_tabs.setCurrentIndex(self._online_tab_idx)

    def open_tutorial(self):
        """打开新手教程(模块化:内容 tutorial_content.py / 渲染 tutorial_gui.py,与 UI 解耦)"""
        from tutorial_gui import TutorialDialog
        TutorialDialog(self).exec()

    def open_guide_demo(self, intro: bool = True):
        """打开引导式新手教程(正式步骤):spctlight + 箭头 + 文本,用 UI 路由指向真实界面。

        intro=True 时先弹「基础知识页」(可跳过),再进正式引导。重播/自动播放都可用。
        步骤覆盖:版本分类 → 加载器 → 下载 Mod(不遮盖选项)→ 启动器插件 → AI + 技能。
        """
        # ① 先弹基础知识页(可跳过):MC 版本/阵营/正版 + 版本分类
        if intro:
            try:
                from tutorial_intro import TutorialIntroDialog
                if TutorialIntroDialog(self).exec() != 1:
                    return   # 用户跳过基础知识 → 不继续引导
            except Exception:
                pass

        from guide_overlay import GuideDriver

        steps = [
            # ---- 版本分类(下载新资源 → 实例/下载向导 → 版本树)----
            {"route": [("maintab", "下载新资源"), ("rcswitch", "1"), ("widgetname", "version_tree")],
             "arrow": "below",
             "text": "① 先认识版本:左侧版本列表里,「正式版」最稳(其中几个「黄金版本」Mod 生态最好);"
                     "「预览版」=公测(可能有 bug);「远古版」=考古;「愚人节版」=官方整活小改(类似整合包)。"},
            # ---- 加载器(同页:下载向导的加载器卡片)----
            {"route": [("maintab", "下载新资源"), ("rcswitch", "1"), ("widgetname", "loader_panel")],
             "arrow": "below",
             "text": "② 选完版本选「加载器」:原版(不打 Mod)/ Fabric / Forge / NeoForge。"
                     "NeoForge 是 Forge 的现代继承者(1.20.2 及以上);"
                     "Fabric 轻量、Mod 多。以后可能支持更多加载器。"},
            # ---- 下载 Mod(不遮盖选项,多个一起讲)----
            {"route": [("maintab", "下载新资源"), ("rcswitch", "3"), ("widgetname", "resource_search")],
             "arrow": "below",
             "text": "③ 这里逛 Mod:搜索框搜中文/英文;上面能选「游戏版本 + 加载器」、排序/标签,"
                     "找到后点「下载」装到目标实例。光影包 / 数据包 / 资源包 也是同样的逛法。"},
            # ---- 启动器插件(默认仓库)----
            {"route": [("maintab", "下载新资源"), ("rcswitch", "8"), ("widgetname", "plugins_page")],
             "arrow": "below",
             "text": "④ 启动器插件页:默认已填好官方仓库(erfanyo/Agent_Minecraft_Launcher,"
                     "plugins.json 清单);点「添加仓库」还能加别的仓库,仓库里的插件可一键安装。"},
            # ---- AI + 技能 ----
            {"route": [("maintab", "设置"), ("btn", "AI 助手")],
             "arrow": "below",
             "text": "⑤ AI 助手:配云端或本地模型后,能问答、自动帮你装 Mod/查配方/诊断崩溃;"
                     "「技能管理」里能开关 自动重启 / 备份提醒 / 崩溃诊断清单 等辅助技能。"},
            {"route": [("maintab", "我的实例"), ("btn", "启动游戏")],
             "arrow": "below",
             "text": "⑥ 回到「我的实例」:右侧选中一个实例,点这个「启动游戏」大按钮就进游戏了。"},
        ]
        self._guide_driver = GuideDriver(self, steps)
        self._guide_driver.finished.connect(lambda: self.statusBar().showMessage("引导教程演示结束"))
        self._guide_driver.start()

    def open_skill_manager(self):
        """打开技能管理(游戏运行时辅助功能,勾选启停)"""
        dlg = SkillManagerDialog(self.skill_mgr, self)
        dlg.exec()

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
            self.ai_strip_dock.setVisible(not visible)
        if hasattr(self, "dl_indicator"):
            self._place_download_ball()
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
            f" 内存 {self.settings.get('memory_gb', 4)}G,"
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

    # ---- 后台下载:队列 + 定时器,把线程里的回调搬回主线程 ----
    def _run_download(self, worker_fn):
        """后台线程跑下载任务;状态/进度经队列回主线程,界面不卡。"""
        self._busy_download(True)
        self._dl_queue = queue.Queue()
        if self._dl_timer is None:
            self._dl_timer = QTimer(self)
            self._dl_timer.timeout.connect(self._drain_download)
            self._dl_timer.start(80)
        # 左下角指示器:显示 + 归零;下载 tab 进度条也归零
        self._dl_log = []
        self._dl_progress = (0, 1)
        self.dl_indicator.set_progress(0, 1)
        self.dl_indicator.setToolTip("下载中,点击查看详情")
        self.dl_indicator.show()
        try:
            self.download_tab.set_progress(0, 1)
        except Exception:
            pass

        def status(msg):
            self._dl_queue.put(("status", str(msg)))

        def progress(done, total):
            self._dl_queue.put(("progress", done, total))

        def worker():
            try:
                worker_fn(status, progress)
                self._dl_queue.put(("done", None))
            except Exception as e:
                self._dl_queue.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _drain_download(self):
        """主线程:把下载队列里的状态/进度搬到界面"""
        while True:
            try:
                item = self._dl_queue.get_nowait()
            except queue.Empty:
                return
            kind = item[0]
            if kind == "status":
                self.download_tab.set_status(item[1])
                self.statusBar().showMessage(item[1])
                self._dl_log.append(item[1])            # 记录进详情
            elif kind == "progress":
                self.download_tab.set_progress(item[1], item[2])
                self.dl_indicator.set_progress(item[1], item[2])
                self._dl_progress = (item[1], item[2])
            elif kind == "done":
                self.statusBar().showMessage("下载任务完成")
                self._dl_log.append("✅ 下载任务完成")
                self.dl_indicator.set_progress(1, 1)    # 满环
                self.dl_indicator.setToolTip("下载完成,点击查看详情")
                # 常驻:不自动收起(点击看详情/下次下载重置),避免'进度条出现晚'的感知
                self._dl_finish(True)
            elif kind == "error":
                self.statusBar().showMessage(f"下载失败: {item[1]}")
                self._dl_log.append(f"❌ 下载失败: {item[1]}")
                self.dl_indicator.set_progress(1, 1)
                self.dl_indicator.setToolTip("下载失败,点击查看详情")
                self._dl_finish(False)

    def _ensure_dl_overlay(self):
        """惰性创建下载详情覆盖层(ContentOverlay + DownloadDetailWidget,复用不重复建)。"""
        if getattr(self, "_dl_overlay", None) is not None:
            return
        from ui_overlay import ContentOverlay

        def live():
            return (list(self._dl_log), self._dl_progress[0], self._dl_progress[1])

        self._dl_overlay = ContentOverlay(self._background)
        self._dl_overlay.set_title("下载详情")
        self._dl_overlay.backRequested.connect(self._on_dl_back)
        self._dl_overlay.set_content(
            DownloadDetailWidget(self._dl_log, self._dl_progress[0], self._dl_progress[1],
                                 live=live))

    def _on_dl_back(self):
        """下载详情返回:收起覆盖层,恢复主内容。"""
        if getattr(self, "_dl_overlay", None) is not None:
            self._dl_overlay.hide_overlay()
        self.main_tabs.show()

    def open_download_detail(self):
        """点击下载球:隐藏主内容,在主窗显示半透明下载详情覆盖层(返回按钮回原页)。"""
        self._ensure_dl_overlay()
        self.main_tabs.hide()   # 隐藏主内容,让半透明覆盖层直接压在壁纸上
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
        text = (text or "").strip()
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

    def _on_my_instances_page(self) -> bool:
        """当前是否在「我的实例」页(只有在这页,拖入文件才当作整合包安装)。"""
        return getattr(self, "_my_inst_tab_idx", 0) == self.main_tabs.currentIndex()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and self._on_my_instances_page():
            e.acceptProposedAction()
            if hasattr(self, "_drop_overlay"):
                self._drop_overlay.setGeometry(self.rect())
                self._drop_overlay.raise_()
                self._drop_overlay.show()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls() and self._on_my_instances_page():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        if hasattr(self, "_drop_overlay"):
            self._drop_overlay.hide()

    def dropEvent(self, e):
        if hasattr(self, "_drop_overlay"):
            self._drop_overlay.hide()
        if e.mimeData().hasUrls() and self._on_my_instances_page():
            for u in e.mimeData().urls():
                path = u.toLocalFile()
                if path:
                    self.install_modpack_from_path(path)
            e.acceptProposedAction()
        else:
            e.ignore()   # 其它页面:不当作整合包,交由该页控件处理(如实例详情列表拷入文件夹)

    def install_modpack_from_path(self, path: str):
        """把本地的整合包文件导入成新实例(拖放入口;自动识别格式)。"""
        from modpack import detect_modpack_format, import_modpack
        from PySide6.QtWidgets import QInputDialog
        fmt = detect_modpack_format(path)
        mc_version = None
        loader = None
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
        """把下载悬浮球摆到内容区右下角:AI 停靠时在 AI dock 左侧(主窗口侧外部),不占底部。
        随窗口/右侧 dock 变化自动重新定位(窗口缩放、AI 显示/收起)。"""
        if not hasattr(self, "dl_indicator"):
            return
        central = self.centralWidget()
        if central is None:
            return
        br = central.mapToGlobal(central.rect().bottomRight())
        margin = 12
        x = br.x() - self.dl_indicator.width() - margin
        y = br.y() - self.dl_indicator.height() - margin
        self.dl_indicator.move(x, y)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, "dl_indicator"):
            self._place_download_ball()
        if getattr(self, "_wallpaper_source", None) is not None:
            self._recompute_wallpaper()

    def _update_running_label(self):
        """刷新顶部的"已有 x 个运行中的实例"(悬停显示具体实例)"""
        from ui_style import muted_color, success_color
        n = len(self._running_instances)
        if n:
            self._running_label.setText(f"🟢 已有 {n} 个运行中的实例")
            self._running_label.setToolTip("运行中的实例:\n" + "\n".join(sorted(self._running_instances)))
            self._running_label.setStyleSheet(f"color: {success_color()}; font-weight: bold;")
        else:
            self._running_label.setText("⚪ 已有 0 个运行中的实例")
            self._running_label.setToolTip("启动实例后这里会显示运行中的游戏")
            self._running_label.setStyleSheet(f"color: {muted_color()};")

    def _busy_download(self, busy: bool):
        self.download_tab.set_busy(busy)
        self.launch_btn.setEnabled(not busy)

    def _set_progress(self, done: int, total: int):
        """通用进度回调(实例下载 / Java 下载共用):显示在左下角圆环指示器上"""
        self.dl_indicator.set_progress(done, total)
        self.dl_indicator.setToolTip("下载中,点击查看详情")
        self.dl_indicator.show()

    def report_download_progress(self, title: str, status: str, done: int, total: int):
        """通用下载进度入口(本地模型 / AI 发起的 Mod 下载共用):写进下载日志 + 更新左下角圆环指示器。
        title 用作圆环 tooltip/详情里的标识;status 为状态消息(可为空)。这样点圆环 → 下载详情也能看到。"""
        if status:
            self._dl_log.append(status)
        self._dl_progress = (done, total)
        self.dl_indicator.set_progress(done, total)
        if status and "失败" in status:
            self.dl_indicator.setToolTip(f"{title}失败,点击查看详情")
        elif status and ("完成" in status or "已就绪" in status.lower()):
            self.dl_indicator.setToolTip(f"{title}完成,点击查看详情")
        else:
            self.dl_indicator.setToolTip(f"正在下载{title},点击查看详情")
        self.dl_indicator.show()

    def report_download_done(self, title: str, ok: bool, msg: str):
        """通用下载结束入口:写日志 + 满环 + 收起(2s)。"""
        self._dl_log.append(msg)
        self._dl_progress = (1, 1)
        self.dl_indicator.set_progress(1, 1)
        self.dl_indicator.setToolTip(f"{title}" + ("完成,点击查看详情" if ok else "失败,点击查看详情"))
        QTimer.singleShot(2000, self.dl_indicator.hide)

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
        if self.settings.get("version_isolation"):
            return os.path.join(paths.GAME_DIR, "versions", version_id)
        return paths.GAME_DIR

    def load_version_data(self, v: dict) -> dict:
        """取版本的完整数据:本地的(Mod 版本)从磁盘读并解析继承链,
        原版从 Mojang 清单拉取。"""
        if v.get("local"):
            return resolve_inherited_json(v["id"], paths.GAME_DIR)
        return fetch_version_detail(v["url"])

    # ---- 工具函数:把版本 v 作为叶子节点加进树,并藏好数据 ----
    def _add_version(self, parent, v):
        item = QTreeWidgetItem([f"{v['id']}  ({v['type']})"])
        item.setData(0, Qt.ItemDataRole.UserRole, v)  # 版本数据藏在第 0 列
        parent.addChild(item)

    def load_versions(self):
        """从网络拉取版本清单,更新顶部信息 + 刷新下载选项卡的版本树"""
        self.statusBar().showMessage("正在获取版本列表...")
        try:
            manifest = fetch_version_manifest()
        except Exception as e:
            self.statusBar().showMessage(f"获取失败: {e}")
            return

        self.resource_center.set_latest_versions(manifest['latest']['release'],
                                                 manifest['latest']['snapshot'])
        self.download_tab._load_tree()

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

    def install_version(self, version_id: str, status_cb=None, progress_cb=None) -> bool:
        """按版本号完整安装一个原版版本(jar + 依赖库 + 资源)。成功返回 True。"""
        if status_cb is None:
            status_cb = self.statusBar().showMessage
        if progress_cb is None:
            progress_cb = self._set_progress
        status_cb(f"正在获取 {version_id} 的安装信息...")
        try:
            manifest = fetch_version_manifest()
            entry = next((v for v in manifest["versions"]
                          if v["id"] == version_id
                          and v["type"] in ("release", "snapshot")), None)
            if entry is None:
                status_cb(f"清单里找不到 {version_id}")
                return False
            d = fetch_version_detail(entry["url"])
        except Exception as e:
            status_cb(f"获取版本信息失败: {e}")
            return False
        return self._install_detail(d, status_cb=status_cb, progress_cb=progress_cb)

    def _install_detail(self, d: dict, status_cb=None, progress_cb=None) -> bool:
        """安装一个已取到详细数据的原版版本:保存 JSON + 客户端 jar + 依赖库/资源"""
        if status_cb is None:
            status_cb = self.statusBar().showMessage
        if progress_cb is None:
            progress_cb = self._set_progress

        client = d.get("downloads", {}).get("client")
        if client is None:
            status_cb(f"{d['id']} 没有客户端 jar(该版本不可直接启动)")
            return False

        # 保存版本 JSON 到实例目录(PCL2 风格:实例自包含,也是加载器继承链的根)
        inst_dir = os.path.join(paths.GAME_DIR, "versions", d["id"])
        os.makedirs(inst_dir, exist_ok=True)
        with open(os.path.join(inst_dir, d["id"] + ".json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)

        try:
            # 1) 客户端 jar
            dest = os.path.join(paths.GAME_DIR, "versions", d["id"], f"{d['id']}.jar")
            status_cb(f"下载客户端 {d['id']} ...")
            download_with_mirror(client["url"], dest, version_id=d["id"],
                                 sha1=client.get("sha1"), progress_callback=progress_cb)

            # 2) 依赖库 + 资源文件(自动跳过已存在的;单个失败不会中断)
            _downloaded, failures = install_version_files(
                d, paths.GAME_DIR, progress_callback=progress_cb, status_callback=status_cb)
        except Exception as e:
            status_cb(f"安装失败: {e}")
            return False

        if failures:
            example = failures[0][0]
            status_cb(f"安装完成但 {len(failures)} 个文件失败(如 {example})——请重试补齐")
            return False
        return True

    def launch_selected(self):
        """启动当前选中版本:准备 Java → 拼命令 → 拉起进程 → 日志实时显示"""
        v = self.selected_version
        if v is None:
            self.statusBar().showMessage("请先在列表里选中一个版本")
            return
        if self.game_process and self.game_process.poll() is None:
            self.statusBar().showMessage("游戏正在运行中,请先退出再启动")
            return

        self.statusBar().showMessage(f"正在获取 {v['id']} 的启动信息...")
        # 旧版导入的整合包 json id 可能仍是加载器版本名(未改写成包名),
        # 启动前先自愈:让 id 与实例目录名一致,启动才会落到本实例自己的游戏目录
        if v.get("local"):
            heal_instance_json(v["id"], paths.GAME_DIR)
        try:
            d = self.load_version_data(v)
        except Exception as e:
            self.statusBar().showMessage(f"获取版本信息失败: {e}")
            return

        required_java = (d.get("javaVersion") or {}).get("majorVersion", 8)
        self._running_instance_id = v["id"]   # 实例 id(= 游戏目录名),供退出后自动 debug 定位日志

        def on_progress(done, total):
            self.dl_indicator.set_progress(done, total)
            self.dl_indicator.setToolTip("下载中,点击查看详情")
            self.dl_indicator.show()

        try:
            # 1) 保证有合适的 Java(没有就自动下载)
            java_exe = ensure_java(paths.RUNTIME_DIR, required_java,
                                   progress_callback=on_progress,
                                   status_callback=self.statusBar().showMessage)
            self.dl_indicator.hide()   # Java 检测/下载完成,收起圆环
            # 2) 把版本 JSON 翻译成启动命令
            #    运行目录按隔离策略来;安装目录和资源目录是所有版本共享的
            #    用 v["id"](用户选中的实例目录名)而不是 d["id"](json 的 id):
            #    整合包 json 可能从加载器版本复制而来,id 若没改对,游戏会被启动到
            #    加载器的空白目录里(mod 全不加载)—— 游戏目录必须是所选实例自己的目录。
            game_dir = self.game_dir_for(v["id"])
            # 正版登录:若存了凭证,启动时用正版 UUID/令牌(online 服能过验证);否则离线
            auth = None
            username_load = self.settings.get("username", "Player")
            if self.settings.get("login_method") == "microsoft":
                cred = dict(self.settings.get("ms_credentials") or {})
                # 顺手尝试刷新令牌(免每次重登;失败则用已存令牌)
                if cred.get("refresh_token"):
                    try:
                        from microsoft_auth import refresh_with_ms_refresh
                        new = refresh_with_ms_refresh(cred["refresh_token"])
                        cred.update({
                            "access_token": new.get("access_token", cred.get("access_token", "")),
                            "uuid": new.get("uuid", cred.get("uuid", "")),
                            "username": new.get("username", cred.get("username", "")),
                        })
                        self.settings["ms_credentials"] = cred
                        save_settings(self.settings)
                    except Exception:
                        pass   # 刷新失败:用已存令牌(可能仍有效)
                if cred.get("access_token") and cred.get("uuid"):
                    auth = {
                        "uuid": cred.get("uuid", ""),
                        "access_token": cred.get("access_token", ""),
                        "refresh_token": cred.get("refresh_token", ""),
                        "username": cred.get("username", ""),
                        "token_type": "msa",
                    }
                    username_load = cred.get("username") or username_load
            # 强制正版(microsoft_login=true):【没有正版凭证】才禁止启动;
            # 正版玩家即便切到离线昵称也会放行(凭证保留,可切回正版)。
            force_online = self.settings.get("microsoft_login", True)
            _creds = dict(self.settings.get("ms_credentials") or {})
            if force_online and not _creds.get("uuid"):
                self.dl_indicator.hide()
                QMessageBox.warning(
                    self, "需要正版登录",
                    "当前为「强制正版」模式(config 的 microsoft_login=true)。\n"
                    "本机还没有正版账号,请先完成微软正版登录才能启动游戏。\n\n"
                    "若想完全跳过正版、纯离线使用,请把 config.json 的 microsoft_login 改为 false。")
                return
            # 实例级内存覆盖:读本实例 launch_options.json(memory_gb>0 则覆盖全局;0/缺失=用全局)
            inst_mem = 0
            try:
                lop = os.path.join(paths.GAME_DIR, "versions", v["id"], "launch_options.json")
                if os.path.isfile(lop):
                    with open(lop, encoding="utf-8") as f:
                        inst_mem = int(json.load(f).get("memory_gb") or 0)
            except Exception:
                inst_mem = 0
            mem_gb = inst_mem if inst_mem > 0 else self.settings.get("memory_gb", 4)
            cmd = build_launch_command(
                d, game_dir, java_exe,
                username=username_load,
                memory_gb=mem_gb,
                assets_dir=os.path.join(paths.GAME_DIR, "assets"),
                install_dir=paths.GAME_DIR,
                auth=auth,
            )
        except Exception as e:
            self.dl_indicator.hide()
            self.statusBar().showMessage(f"启动准备失败: {e}")
            return

        # 3) 展开日志面板,显示要执行的命令(方便你理解"启动"到底是什么)
        # 3) 清空并写入要执行的命令到游戏日志(在「实例详情 → 游戏日志」里看)
        self.log_view.clear()
        self.log_view.appendPlainText("> " + " ".join(cmd))
        # 首次运行提示:还没生成过完整游戏目录(saves/配置)时告诉用户
        if not os.path.isdir(os.path.join(game_dir, "saves")):
            self.statusBar().showMessage(
                f"首次运行 {d['id']}:将生成完整游戏目录(存档/配置在 {game_dir})")
        else:
            self.statusBar().showMessage("游戏启动中...")
        self.launch_btn.setEnabled(False)

        # Java 用 javaw(无控制台窗口,避免弹出黑框);启动进程本身也不开新窗口
        java_dir = os.path.dirname(java_exe)
        javaw = os.path.join(java_dir, "javaw.exe")
        if os.path.isfile(javaw):
            cmd = [javaw] + cmd[1:]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        # 游戏内 AI 通道:关闭 → 游戏启动前卸载本地模型(llama-server),把内存让给游戏;
        # 开启 → 可能用本地模型(看 ai_strategy),保持加载(游戏内 AI 通道)
        ai_in_game = str(self.settings.get("ai_in_game", "off") or "off").strip().lower()
        if ai_in_game == "off":
            self.ai_dock.stop_local_engine()

        try:
            self.game_process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", cwd=game_dir,
                creationflags=creationflags,
            )
        except Exception as e:
            self.statusBar().showMessage(f"启动失败: {e}")
            self.launch_btn.setEnabled(True)
            return

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

        # 4) 后台线程读游戏输出 → 队列 → 定时器搬到日志页(生产-消费模式)
        self.log_queue = queue.Queue()
        threading.Thread(target=self._read_process, daemon=True).start()
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self._drain_log)
        self.log_timer.start(100)

        # 记录本次运行起点,用于判断"本次是否新产生了崩溃报告"(即使退出码为 0)
        self._game_started_at = time.time()

    def _read_process(self):
        """后台线程:一行行读游戏输出,放进队列(生产)"""
        for line in self.game_process.stdout:
            self.log_queue.put(line.rstrip())
        self.log_queue.put(None)  # 结束标记

    def _drain_log(self):
        """主线程(定时器):把队列里的日志搬到界面(消费)"""
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                return
            if line is None:
                self.log_timer.stop()
                code = self.game_process.poll()
                self.launch_btn.setEnabled(True)
                self.statusBar().showMessage(f"游戏进程已退出(退出码 {code})")
                # 运行实例指示:注销并刷新底部标签
                inst_id = getattr(self, "_running_instance_id", None)
                if inst_id:
                    self._running_instances.discard(inst_id)
                self._update_running_label()
                # 通知技能系统:游戏退出(自动重启/备份提醒等技能在这里触发)
                self.skill_mgr.on_game_stop(code)
                # 主动避让(§5):游戏退出 → 恢复本地推理正常优先级,并按策略预热下次要用
                try:
                    self.ai_dock.set_game_stopped()
                except Exception:
                    pass
                self._stop_in_game_ai()
                if code not in (0, None):
                    self._auto_debug(code)   # 异常退出 → 自动收集日志给 AI 分析
                elif self._detect_log_crash():
                    # 很多崩溃(尤其 F3+C 调试崩溃/Mod 崩溃)退出码其实是 0,但留下了崩溃报告或日志特征
                    self._auto_debug(0)
                return
            self.log_view.appendPlainText(line)
            self.skill_mgr.on_game_log(line)   # 每行日志实时喂给技能(自动重启等)

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
        """显示游戏日志:切到「实例详情」标签页并选中「游戏日志」项(若有实例)。"""
        if getattr(self, "_inst_details_tab_idx", None) is not None:
            self.main_tabs.setCurrentIndex(self._inst_details_tab_idx)
        if hasattr(self, "instance_details") and self.instance_details.shell is not None:
            self.instance_details.shell.switch_by_label("游戏日志")

    # ---- 自动 debug:游戏异常退出时收集日志,让 AI 分析 ----
    def _detect_log_crash(self) -> bool:
        """很多崩溃(如 F3+C 调试崩溃、Mod 崩溃)退出码是 0,但留下了崩溃报告或日志特征。
        这里只判断"本次运行是否发生崩溃",不弹窗。"""
        inst_id = getattr(self, "_running_instance_id", None)
        game_dir = self.game_dir_for(inst_id) if inst_id else paths.GAME_DIR
        # 1) 本次运行期间是否新产生了崩溃报告
        cr_dir = os.path.join(game_dir, "crash-reports")
        start = float(getattr(self, "_game_started_at", 0) or 0)
        if os.path.isdir(cr_dir):
            try:
                for f in os.listdir(cr_dir):
                    p = os.path.join(cr_dir, f)
                    if os.path.isfile(p) and os.path.getmtime(p) >= start:
                        return True
            except Exception:
                pass
        # 2) 日志里是否有明显崩溃标记
        log_path = os.path.join(game_dir, "logs", "latest.log")
        if os.path.isfile(log_path):
            try:
                tail = open(log_path, encoding="utf-8", errors="replace").read()[-8000:].lower()
            except Exception:
                tail = ""
            marks = ("---- minecraft crash report ----", "a fatal error has been detected",
                     "failed to start the minecraft server", "outofmemoryerror", "java.lang.nullpointer")
            if any(m in tail for m in marks):
                return True
        return False

    def _auto_debug(self, code: int):
        """游戏异常退出(退出码非 0 或检测到本次崩溃):自动抓最新日志 + 崩溃报告,问用户是否让 AI 分析"""
        inst_id = getattr(self, "_running_instance_id", None)
        game_dir = self.game_dir_for(inst_id) if inst_id else paths.GAME_DIR
        parts = [f"游戏进程异常退出(退出码 {code})。"]
        log_path = os.path.join(game_dir, "logs", "latest.log")
        if os.path.isfile(log_path):
            try:
                lines = open(log_path, encoding="utf-8", errors="replace").read().splitlines()
                parts.append("【最新日志(尾部 60 行)】\n" + "\n".join(lines[-60:]))
            except Exception:
                pass
        cr_dir = os.path.join(game_dir, "crash-reports")
        if os.path.isdir(cr_dir):
            files = sorted(os.listdir(cr_dir), reverse=True)
            if files:
                try:
                    text = open(os.path.join(cr_dir, files[0]),
                                encoding="utf-8", errors="replace").read()
                    parts.append("【最新崩溃报告(摘要)】\n" + text[:2000])
                except Exception:
                    pass
        msg = "\n\n".join(parts)
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
        """下载一个"基础实例":原版本体 + (可选)加载器 + (可选)Fabric API + 光影/优化 Mod。
        在后台线程运行,状态/进度通过回调上报(默认用主线程直调,兼容旧用法)。"""
        if status_cb is None:
            status_cb = self.statusBar().showMessage
        if progress_cb is None:
            progress_cb = self._set_progress

        status_cb(f"开始下载实例 {version} ...")

        # 1) 原版本体(加载器版本必须依赖它,先提示避免"怎么多下个原版"的困惑)
        if loader_key:
            status_cb(f"准备基础原版 {version}({loader_key} 加载器依赖它,必须一并下载)...")
        if not self.install_version(version, status_cb=status_cb, progress_cb=progress_cb):
            return

        # 2) 加载器
        instance_id = version
        if loader_key:
            try:
                instance_id = install_loader(loader_key, version, paths.GAME_DIR,
                                             loader_version=loader_version,
                                             progress_callback=progress_cb,
                                             status_callback=status_cb)
            except Exception as e:
                status_cb(f"加载器安装失败: {e}")
                return

        # 2.5) Fabric API(绝大多数 Fabric 模组的前置;选中 Fabric 且选了版本时自动装)
        mods_dir = os.path.join(self.game_dir_for(instance_id), "mods")
        if loader_key == "fabric" and fabric_api_version:
            self._install_mod("fabric-api", version, "fabric", mods_dir, "Fabric API",
                              version_number=fabric_api_version,
                              status_cb=status_cb, progress_cb=progress_cb)

        # 3) 光影 / 优化 Mod(下载到该实例自己的 mods 目录)
        if shader and modrinth_loader:
            slug = SHADER_MODS.get(modrinth_loader)
            if slug:
                self._install_mod(slug, version, modrinth_loader, mods_dir, "光影",
                                  version_number=shader_version,
                                  status_cb=status_cb, progress_cb=progress_cb)
        if optimize and modrinth_loader:
            for slug in OPTIMIZE_MODS.get(modrinth_loader, []):
                want = None
                if optimize_versions:
                    want = optimize_versions.get(slug)
                self._install_mod(slug, version, modrinth_loader, mods_dir, "优化",
                                  version_number=want,
                                  status_cb=status_cb, progress_cb=progress_cb)

        status_cb(f"实例就绪:{instance_id} ✅ "
                  f"(游戏目录:{self.game_dir_for(instance_id)};"
                  f"首次运行会生成完整目录——存档/配置/日志)")

    def _install_mod(self, slug: str, game_version: str, loader: str,
                     mods_dir: str, kind: str, version_number: str | None = None,
                     status_cb=None, progress_cb=None):
        """下载一个 Mod 到实例的 mods 目录;失败只提示,不中断流程"""
        if status_cb is None:
            status_cb = self.statusBar().showMessage
        try:
            filename = download_mod(slug, game_version, loader, mods_dir,
                                    version_number=version_number,
                                    progress_callback=progress_cb)
        except Exception as e:
            status_cb(f"{kind} Mod {slug} 下载失败: {e}")
            return
        if filename:
            status_cb(f"{kind} Mod 已装:{filename}")
        else:
            status_cb(f"{kind} Mod {slug} 暂无 {game_version}+{loader} 版本,已跳过")

    # ---- 下载 Mod 选项卡 ----
    def refresh_instances(self):
        """扫描实例,刷新:我的版本列表 + 下载 Mod 卡片 + versions 里的实例记录"""
        self._tidy_base_versions()   # 把纯基础原版收进 _versions 仓库(一次性迁移)
        instances = scan_instances(paths.GAME_DIR)

        # 隐藏"依赖型原版实例":被 Mod 实例继承、且没有自己存档的原版,
        # 只是加载器的地基,不单独显示(下载一个 Fabric 实例不会看到两个实例)
        bases_in_use = {i["base"] for i in instances if i["loader"]}
        shown = [i for i in instances
                 if not (i["loader"] is None and i["id"] in bases_in_use
                         and not os.path.isdir(os.path.join(self.game_dir_for(i["id"]), "saves")))]

        # 1) 我的版本列表(带封面)
        # 保留当前选中:versions/ 目录变动会触发防抖自动刷新(500ms),clear() 会把当前项
        # 清成 None → currentItemChanged(None) → 详情页被"自动取消"。这里 blockSignals
        # 重建列表、按 id 复原选中,最后统一同步一次 UI(恢复选中 / 实例真的没了→None)。
        _cur_item = self.instance_list.currentItem()
        _cur_id = (_cur_item.data(Qt.ItemDataRole.UserRole) or {}).get("id") if _cur_item else None
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
            if _cur_id:
                for _i in range(self.instance_list.count()):
                    _d = self.instance_list.item(_i).data(Qt.ItemDataRole.UserRole)
                    if _d and _d.get("id") == _cur_id:
                        _restore = self.instance_list.item(_i)
                        break
            if _restore is not None:
                self.instance_list.setCurrentItem(_restore)
        finally:
            self.instance_list.blockSignals(False)
        # 刷新后统一同步一次当前选择(复原的实例,或已消失→None)
        self.instance_list._on_selection_changed(self.instance_list.currentItem(), None)
        # 同步到首页面板(实例数量 + 当前选择态)
        self.home_panel.set_current_instances(shown)

        # 3) 实例记录(实例清单备忘,可手动编辑补充)
        self.write_cheat_sheet(shown)

        # 4) 资源中心的目标实例卡片(Mod/光影/数据包浏览器)
        self.resource_center.refresh_browser_instances(shown)

    # ---- 实例目录文件变动 → 自动刷新实例列表 ----
    def _setup_instance_watcher(self):
        """监听 versions/ 目录:子文件夹新增/删除 → 防抖后刷新「实例(共x个)」列表。"""
        self._inst_watcher = None
        self._inst_refresh_timer = QTimer(self)
        self._inst_refresh_timer.setSingleShot(True)
        self._inst_refresh_timer.setInterval(500)   # 防抖:多次文件变动合并成一次刷新
        self._inst_refresh_timer.timeout.connect(self._on_instance_dir_debounced)
        try:
            self._inst_watcher = QFileSystemWatcher(self)
            self._inst_watcher.directoryChanged.connect(self._on_instance_dir_changed)
            self._watch_versions_dir()
        except Exception as e:
            self._inst_watcher = None
            self._log_feedback(f"实例目录监听初始化失败:{e}", "警告")

    def _watch_versions_dir(self):
        """(重新)把监听指向当前游戏目录的 versions/。游戏目录变更时也调用。"""
        if self._inst_watcher is None:
            return
        try:
            dirs = self._inst_watcher.directories()
            if dirs:
                self._inst_watcher.removePaths(dirs)
            versions_dir = os.path.join(paths.GAME_DIR, "versions")
            if os.path.isdir(versions_dir):
                self._inst_watcher.addPath(versions_dir)
        except Exception as e:
            self._log_feedback(f"监听 versions/{os.path.basename(paths.GAME_DIR)} 失败:{e}", "警告")

    def _on_instance_dir_changed(self, _path: str):
        """versions/ 目录有变动:重启防抖计时器(合并连续变动)。"""
        # 正在游戏内/下载等忙时也允许,但防抖+避免 TidyBase 迁移又触发自身
        self._inst_refresh_timer.start()

    def _on_instance_dir_debounced(self):
        """防抖到期:确实有变动才刷新。避免 refresh→tidy→目录变动→refresh 死循环。"""
        try:
            self.refresh_instances()
        except Exception as e:
            self._log_feedback(f"实例目录变动刷新失败:{e}", "警告")

    def _resource_download(self, hit, version, inst, target_dir, sub_dir):
        """资源中心下载回调:把项目下载到目标实例的对应目录(mods/shaderpacks/...)"""
        slug = hit["slug"]
        if not target_dir:
            self.statusBar().showMessage("未选择安装位置")
            return
        gv = (inst["base"] if inst else "1.21.1") or "1.21.1"
        loader = (inst["loader"] if inst else None)
        # Mod 按加载器过滤;光影/数据包/资源包一般不区分加载器
        use_loader = loader if sub_dir == "mods" else None

        # 正向依赖提示(灵感 #4):下载 Mod 前,解析该版本依赖,提示"需要什么/冲突";
        # 用户可一并安装缺少的必需依赖。仅 Mod 下载时提示,光影/数据包等跳过。
        extra_deps = []
        if sub_dir == "mods":
            try:
                from modrinth import resolve_dependencies
                deps = resolve_dependencies(slug, gv, use_loader, version)
            except Exception:
                deps = None
            if deps:
                lines = [hit.get("title", slug) + " 的依赖提示:"]
                if deps["required"]:
                    lines.append("需要(必装):\n" + "\n".join(f" · {d['title']}" for d in deps["required"]))
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
                    extra_deps = [d["slug"] for d in deps["required"]]

        def worker(status, progress):
            from modrinth import download_mod
            for dep_slug in extra_deps:
                try:
                    dn = download_mod(dep_slug, gv, use_loader, target_dir, progress_callback=progress)
                    if dn:
                        status(f"依赖已装:{dn}")
                except Exception as e:
                    status(f"依赖 {dep_slug} 装入失败(跳过): {e}")
            try:
                filename = download_mod(slug, gv, use_loader, target_dir,
                                        version_number=version,
                                        progress_callback=progress)
                if filename:
                    status(f"✅ 已下载 {filename} → {sub_dir}")
                else:
                    status(f"⚠️ {slug} 没有 {gv}{'+' + use_loader if use_loader else ''} 的可用版本")
            except Exception as e:
                status(f"❌ 下载失败: {e}")

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
        """把"被加载器继承、且没有自己存档"的纯基础原版,收进 versions/_versions/ 版本仓库。
        versions 目录只留真实例(用户主动装的版本/加载器实例);基础原版只是地基,
        收进仓库后 UI 和磁盘目录都干净(有自己存档的算真实例,不动)。"""
        try:
            instances = scan_instances(paths.GAME_DIR)
        except Exception:
            return
        bases_in_use = {i["base"] for i in instances if i["loader"]}
        repo = os.path.join(paths.GAME_DIR, "versions", "_versions")
        for inst in instances:
            if inst["loader"] is not None or inst["id"] not in bases_in_use:
                continue   # 不是"被继承的纯原版"
            inst_dir = self.game_dir_for(inst["id"])
            if os.path.isdir(os.path.join(inst_dir, "saves")):
                continue   # 有自己的存档 → 真实例,不动
            dest = os.path.join(repo, inst["id"])
            try:
                if not os.path.isdir(dest) and os.path.isdir(inst_dir):
                    os.makedirs(repo, exist_ok=True)
                    shutil.move(inst_dir, dest)
            except OSError:
                pass

    @staticmethod
    def _instance_icon(instance_id: str):
        """实例封面:优先版本 JSON 里的 favicon;没有就生成占位封面(色块+首字)"""
        try:
            vjson = os.path.join(paths.GAME_DIR, "versions", instance_id, instance_id + ".json")
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
        """在 versions 目录生成「实例记录.json」:实例清单备忘,可手动编辑补充说明。
        用户手动加过的备注(note)会在刷新时保留,不覆盖;旧版「打小抄.txt」自动清理。"""
        import json
        import datetime
        path = os.path.join(paths.GAME_DIR, "versions", "实例记录.json")
        old_notes = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    old = json.load(f)
                for it in old.get("instances", []):
                    if isinstance(it, dict) and it.get("id") and it.get("note"):
                        old_notes[it["id"]] = it["note"]
            except Exception:
                pass
        data = {
            "note": "实例记录(启动器自动生成,可手动编辑补充说明;每实例的 note 会保留)",
            "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "instances": [
                {"id": inst["id"], "loader": inst.get("loader") or "原版",
                 "base": inst.get("base", ""), "note": old_notes.get(inst["id"], "")}
                for inst in instances
            ],
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass  # 记录文件写不写都不影响功能

        # 清理旧版(打小抄.txt → 实例记录.json)
        old_txt = os.path.join(paths.GAME_DIR, "versions", "打小抄.txt")
        try:
            if os.path.exists(old_txt):
                os.remove(old_txt)
        except Exception:
            pass

    def launch_selected_instance(self):
        """启动"我的版本"里选中的实例(双击或按钮)"""
        item = self.instance_list.currentItem()
        if item is None:
            self.statusBar().showMessage("请先选一个实例(双击也可以直接启动)")
            return
        inst = item.data(Qt.ItemDataRole.UserRole)
        self.selected_version = {"id": inst["id"], "local": True, "type": "instance"}
        self.statusBar().showMessage(f"启动实例: {inst['id']}")
        self.launch_selected()

    # ---- 右键菜单 ----
    def _instance_menu(self, pos):
        """实例右键:管理 / 启动 / 备份 / 打开目录 / 删除实例"""
        item = self.instance_list.itemAt(pos)
        if item is None:
            return
        inst = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction("实例详情…", lambda: self.open_instance_manager(inst))
        menu.addAction("一键配置 bridge-mod(推荐)…", lambda: self._one_click_bridge_for(inst))
        rcon_menu_item = menu.addAction("一键配置 RCON(临时方案)…", lambda: self._one_click_rcon_for(inst))
        rcon_menu_item.setToolTip("临时方案:需要 Lan Server Properties + 进世界按 ESC → 对局域网开放")
        # 联机 mod 一键配置:按实例版本+加载器判断支持才显示(不支持不出现)
        self._add_online_mod_menu_items(menu, inst)
        menu.addAction("启动", self.launch_selected_instance)
        menu.addAction("备份实例", lambda: self.backup_current_instance(inst))
        menu.addAction("打开实例目录", lambda: open_path(self.game_dir_for(inst["id"])))
        mods_dir = os.path.join(self.game_dir_for(inst["id"]), "mods")
        if os.path.isdir(mods_dir):
            menu.addAction("打开 mods 目录", lambda: open_path(mods_dir))
        menu.addSeparator()
        menu.addAction("删除实例…", lambda: self._delete_instance(inst))
        menu.exec(self.instance_list.mapToGlobal(pos))

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
                status_cb(f"安装失败:{type(e).__name__}: {e}")
                return
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
                status_cb(f"下载失败:{e}")
                return
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
                status_cb(f"下载失败:{e}")
                return
            if not filename:
                status_cb(f"没有 {inst['base']}+{inst['loader']} 的版本,换个版本试试")
                return
            # 装好 → 自动写 RCON 配置
            from game_command import ensure_rcon_config
            cfg = ensure_rcon_config(self.game_dir_for(inst["id"]))
            status_cb(f"Lan Server Properties 已安装:{filename}\n{cfg}")

        self._run_download(worker)

    def open_instance_manager(self, inst):
        """打开「实例详情」:改为切到「实例详情」标签页(非模态)并填充该实例。"""
        if inst is None:
            self._hide_instance_details()
            return
        self._show_instance_details(inst, switch=True)

    def _on_instance_selected(self, inst):
        """首页选中实例变化 → 显示/隐藏「实例详情」标签页(带滑入动画)。"""
        if inst is None:
            self._hide_instance_details()
        else:
            self._show_instance_details(inst, switch=False)   # 选中即可见,不强制跳到该页

    def _show_instance_details(self, inst, switch: bool):
        self.instance_details.set_instance(inst, paths.GAME_DIR)
        was_hidden = not self.main_tabs.isTabVisible(self._inst_details_tab_idx)
        self.main_tabs.setTabVisible(self._inst_details_tab_idx, True)
        if was_hidden:
            self._animate_instance_details_in()
        if switch:
            self.main_tabs.setCurrentIndex(self._inst_details_tab_idx)

    def _hide_instance_details(self):
        self.main_tabs.setTabVisible(self._inst_details_tab_idx, False)

    def _animate_instance_details_in(self):
        """标签页出现动画:淡入(320ms OutCubic,走 ui_anim 统一封装;关闭动画则直接显示)。"""
        from ui_anim import fade_in
        from ui_tokens import DURATION
        fade_in(self.instance_details, DURATION.get("slide", 320))

    def _on_main_tab_changed(self, idx: int):
        """主标签页切换 → 新页淡入(250ms;关闭动画则跳过)。"""
        from ui_anim import fade_in
        from ui_tokens import DURATION
        w = self.main_tabs.widget(idx) if 0 <= idx < self.main_tabs.count() else None
        if w is not None:
            fade_in(w, DURATION.get("tab", 250))

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

    def _delete_instance(self, inst):
        """删除一个实例(只删它自己,共用文件保留)"""
        if QMessageBox.question(
                self, "确认删除",
                f"确定删除实例 {inst['id']} 吗?\n(只删该实例,共用文件保留)") != QMessageBox.StandardButton.Yes:
            return
        shutil.rmtree(self.game_dir_for(inst["id"]), ignore_errors=True)
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
    from ui_style import apply_global_dark_palette
    apply_global_dark_palette(app)   # 系统深色 → 全局深色调色板,统一对话框/菜单/标签页

    # 首次启动:还没配置过游戏目录 → 弹引导界面(选路径 + 首次配置 AI + 新手/老手)
    first = not (load_settings().get("game_dir") or "").strip()
    _auto_tutorial = False
    if first:
        from onboarding import OnboardingDialog
        od = OnboardingDialog()
        od.exec()
        # 新手:配置完成后自动走一遍引导式新手教程(老手跳过,设置→界面可重播)
        if getattr(od, "want_tutorial", False):
            _auto_tutorial = True

    window = MainWindow()
    window.load_versions()  # 启动时先加载一次
    window.show()
    # 首次启动选了「新手」→ 自动走一遍引导式新手教程(用 QTimer 延迟到首帧后,保证控件就绪)
    if _auto_tutorial:
        QTimer.singleShot(400, lambda: _open_auto_tutorial_safe(window))
    sys.exit(app.exec())
