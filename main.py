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
from datetime import datetime

import requests

from PySide6.QtCore import QObject, Qt, QSize, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
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
)

from downloader import download_with_mirror  # 下载工具:镜像 + 进度 + sha1 校验
import updater  # 自动更新(检查 GitHub 新版本 / 下载 / 替换)
from bridge_mod_dist import BRIDGE_MOD_VERSION  # bridge-mod 当前版本
from assistant import AIChatDock, permission_instructions  # AI 助手(右侧停靠对话栏)
from download_indicator import DownloadDetailDialog, DownloadIndicator  # 左下角下载指示器
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
from modrinth import download_mod  # Modrinth 搜索与下载(含中文名支持)
import paths  # 游戏目录(可配置,设置/引导里可改)
from paths import GAME_DIR, RUNTIME_DIR  # 兼容旧引用(测试用);内部统一用 paths.GAME_DIR
from settings import load_settings, save_settings  # 启动器配置
from skill_manager import SkillManager, SkillManagerDialog  # 技能(运行时辅助)系统
from version_tree import fill_version_tree  # 版本树构建(与下载选项卡共用)



def _legacy_scan(game_dir: str = GAME_DIR) -> list:
    """兼容别名:scan_instances 已移到 instances.py"""
    return scan_instances(game_dir)


class _UpdateSignals(QObject):
    checked = Signal()        # 版本检查完成(主线程刷新界面)
    progress = Signal(int, int)
    downloaded = Signal()
    failed = Signal(str)


class UpdateDialog(QDialog):
    """检查更新:AMCL 启动器 + bridge-mod(从 GitHub Releases 拉取)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("检查更新", "Check for Updates"))
        self.setMinimumWidth(440)
        self.sig = _UpdateSignals()
        self.sig.checked.connect(self._refresh)
        self.sig.progress.connect(self._on_progress)
        self.sig.downloaded.connect(self._on_downloaded)
        self.sig.failed.connect(self._on_failed)
        self.result = {"launcher": None, "bridge": None, "error": ""}

        self.launcher_label = QLabel("AMCL 启动器: 正在检查...")
        self.bridge_label = QLabel("bridge-mod: 正在检查...")
        self.launcher_btn = QPushButton(t("下载并更新", "Download & Update"))
        self.launcher_btn.setVisible(False)
        self.launcher_btn.clicked.connect(self._do_launcher_update)
        self.bridge_btn = QPushButton(t("查看发布页", "Open Release Page"))
        self.bridge_btn.setVisible(False)
        self.bridge_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(updater.RELEASES_API)))
        close_btn = QPushButton(t("关闭", "Close"))
        close_btn.clicked.connect(self.accept)

        row = QHBoxLayout()
        row.addWidget(close_btn)
        row.addStretch()

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(t("AMCL 启动器", "AMCL Launcher")))
        layout.addWidget(self.launcher_label)
        layout.addWidget(self.launcher_btn)
        layout.addSpacing(10)
        layout.addWidget(QLabel(t("bridge-mod(游戏内指令口 / 数据导出)", "bridge-mod")))
        layout.addWidget(self.bridge_label)
        layout.addWidget(self.bridge_btn)
        layout.addSpacing(10)
        layout.addLayout(row)

        threading.Thread(target=self._check, daemon=True).start()

    def _check(self):
        try:
            self.result["launcher"] = updater.check_launcher_update()
            self.result["bridge"] = updater.check_bridge_mod_update()
        except Exception as e:
            self.result["error"] = str(e)
        self.sig.checked.emit()

    def _refresh(self):
        err = self.result.get("error")
        if err:
            self.launcher_label.setText(f"检查失败: {err[:120]}")
            self.bridge_label.setText("—")
            return
        # AMCL
        upd = self.result.get("launcher")
        cur = updater.VERSION
        if upd:
            new_ver = upd["version"]
            if updater.parse_version(new_ver) <= updater.parse_version(cur):
                self.launcher_label.setText(f"AMCL 启动器: 已是最新 (v{cur}) ✅")
            else:
                self.launcher_label.setText(
                    f"AMCL 启动器: 当前 v{cur} → 发现新版本 {new_ver}")
                self.launcher_btn.setVisible(True)
        else:
            self.launcher_label.setText(
                f"AMCL 启动器: 当前 v{cur}(未能获取最新版本,请检查网络)")
        # bridge-mod
        br = self.result.get("bridge")
        if br:
            self.bridge_label.setText(
                f"bridge-mod: 本地 {BRIDGE_MOD_VERSION} → GitHub {br['version']}")
            self.bridge_btn.setVisible(True)
        else:
            self.bridge_label.setText(
                f"bridge-mod: 本地 {BRIDGE_MOD_VERSION}(未能获取最新版本)")

    def _do_launcher_update(self):
        info = self.result.get("launcher")
        if not info:
            return
        self.launcher_btn.setEnabled(False)
        self.launcher_btn.setText("下载中 0%")
        exe_path = (sys.executable if getattr(sys, "frozen", False)
                    else os.path.join(paths.BASE_DIR, updater.LAUNCHER_ASSET))
        update_dir = os.path.join(paths.BASE_DIR, "AMCL", "update")
        new_exe = os.path.join(update_dir, updater.LAUNCHER_ASSET)
        threading.Thread(target=self._download_and_apply,
                         args=(info["url"], new_exe, exe_path),
                         daemon=True).start()

    def _download_and_apply(self, url, new_exe, exe_path):
        try:
            updater.download_to(url, new_exe, progress_callback=self.sig.progress.emit)
            bat = os.path.join(os.path.dirname(new_exe), "update.bat")
            updater.make_update_bat(exe_path, new_exe, bat)
            updater.run_update_bat(bat)
            self.sig.downloaded.emit()
        except Exception as e:
            self.sig.failed.emit(str(e))

    def _on_progress(self, done, total):
        pct = int(done * 100 / total) if total else 0
        self.launcher_btn.setText(f"下载中 {pct}%")

    def _on_downloaded(self):
        QMessageBox.information(
            self, t("更新", "Update"),
            t("新版本已下载,程序将退出并自动替换重启。", "Update downloaded; the app will restart."))
        QTimer.singleShot(300, QApplication.instance().quit)

    def _on_failed(self, msg):
        self.launcher_btn.setEnabled(True)
        self.launcher_btn.setText(t("下载并更新", "Download & Update"))
        QMessageBox.warning(self, t("更新失败", "Update Failed"),
                            f"下载/替换失败:{msg[:200]}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Agent Minecraft Launcher")
        self.setMinimumSize(700, 560)
        self.selected_version = None  # 记住当前选中的版本,供"下载"按钮使用
        self.settings = load_settings()  # 启动器配置(用户名/内存/版本隔离)
        i18n.set_language(self.settings.get("language", "auto"))  # 界面语言(跟随系统/设置)

        # ---- 顶部(已精简,设置移入菜单栏) ----
        top_bar = QHBoxLayout()
        top_bar.addStretch()

        # ---- 菜单栏(基础启动器的骨架) ----
        menubar = self.menuBar()
        file_menu = menubar.addMenu(t("文件", "File"))
        file_menu.addAction(t("刷新版本列表", "Refresh Version List"), self.load_versions)
        file_menu.addAction(t("导入整合包(Modrinth .mrpack)…", "Import Modpack (.mrpack)…"), self.import_modpack)
        file_menu.addAction(t("打开游戏目录", "Open Game Directory"), self.open_game_dir)
        file_menu.addAction(t("清空所有实例…", "Clear All Instances…"), self.clear_instances)
        file_menu.addSeparator()
        file_menu.addAction(t("退出", "Quit"), self.close)

        view_menu = menubar.addMenu(t("查看", "View"))
        self._inst_icons_action = view_menu.addAction(t("实例:大图标", "Instances: Icons"))
        self._inst_list_action = view_menu.addAction(t("实例:列表", "Instances: List"))
        for act in (self._inst_icons_action, self._inst_list_action):
            act.setCheckable(True)
        self._inst_icons_action.toggled.connect(
            lambda on: on and self.set_view_mode(self.instance_list, True, "instances"))
        self._inst_list_action.toggled.connect(
            lambda on: on and self.set_view_mode(self.instance_list, False, "instances"))

        # ---- 设置:和"文件"平级 ----
        settings_menu = menubar.addMenu(t("设置", "Settings"))
        settings_menu.addAction(t("设置对话框…", "Settings…"), self.open_settings)
        settings_menu.addAction(t("检查更新…", "Check for Updates…"), self.open_update_dialog)
        settings_menu.addSeparator()
        settings_menu.addAction(t("镜像源…", "Mirror Sources…"),
                                lambda: self.open_settings(tab="mirror"))

        # ---- AI 助手:顶级菜单(和"查看"同级,更显眼) ----
        ai_menu = menubar.addMenu("AI")
        self._ai_show_action = ai_menu.addAction(t("显示 AI 助手", "Show AI Assistant"))
        self._ai_show_action.setCheckable(True)
        self._ai_show_action.toggled.connect(self._toggle_ai)
        # AI 设置入口已移除(进设置对话框);技能管理入口已移到 AI 子窗口顶部;
        # 「发送游戏指令…」入口已隐藏:由指令中心 skill 与 bridge-mod 的新通道替代
        # 帮助菜单已移除:其中"检查更新"与设置菜单里的重复(设置 → 检查更新…)

        # ---- 联机方案中心(灵感 #2):按场景推荐联机方案 ----
        online_menu = menubar.addMenu(t("联机", "Multiplayer"))
        online_menu.addAction(t("联机方案中心…", "Multiplayer Center…"), self.open_online_center)

        # ---- Tab「我的版本」:仿 PCL2 首页(左 1/3 登录+实例设置+启动按钮,右 2/3 版本/更新日志/动态) ----
        from version_home import VersionHome
        tab_a = VersionHome()
        self.home_panel = tab_a                     # 保留引用,便于刷新登录显示等
        self.instance_list = tab_a.instance_list    # 版本列表(兼容旧引用:右键/视图/双击)
        self.launch_btn = tab_a.launch_btn          # 启动游戏大按钮
        self.refresh_inst_btn = tab_a.refresh_btn   # 右列「版本」里的刷新按钮
        # 旧行为保留:双击启动 + 启动按钮 + 刷新
        self.instance_list.itemDoubleClicked.connect(self.launch_selected_instance)
        self.launch_btn.clicked.connect(self.launch_selected_instance)
        self.refresh_inst_btn.clicked.connect(self.refresh_instances)
        # 新首页抛出的信号 → 启动器处理
        tab_a.open_instance_manager_requested.connect(self._home_open_instance_manager)
        tab_a.open_settings_requested.connect(self.open_settings)
        tab_a.login_changed.connect(self._on_login_changed)

        # ---- 「下载新资源」综合入口:左侧菜单 + 首页/实例/Mod/光影/数据包/资源包 ----
        from resource_center import ResourceCenter
        self.resource_center = ResourceCenter()
        self.resource_center.set_ui_mode(self.settings.get("ui_mode", "beginner"))
        # 兼容旧引用:download_tab 是资源中心内的实例向导
        self.download_tab = self.resource_center.download_tab
        self.resource_center.set_hooks(
            instance_dir=self.game_dir_for,
            on_download=self._resource_download,
            on_start_instance=self.start_instance_download)


        # 右键菜单:实例(启动/打开目录/删除)
        self.instance_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.instance_list.customContextMenuRequested.connect(self._instance_menu)

        # ---- 主选项卡(我的版本 / 下载新资源) ----
        self.main_tabs = QTabWidget()
        self.main_tabs.addTab(tab_a, t("我的版本", "Versions"))
        self.main_tabs.addTab(self.resource_center, t("下载新资源", "Resources"))

        # ---- 底部:可折叠的游戏日志(默认收起) ----
        self.log_toggle_btn = QPushButton(t("▶ 游戏日志", "▶ Game Log"))
        self.log_toggle_btn.setCheckable(True)
        self.log_toggle_btn.setChecked(False)
        self.log_toggle_btn.clicked.connect(self._toggle_log)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setVisible(False)   # 默认折叠

        # ---- 组装整个窗口 ----
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top_bar)
        layout.addWidget(self.main_tabs)
        layout.addWidget(self.log_toggle_btn)
        layout.addWidget(self.log_view, 1)
        self.setCentralWidget(central)

        # ---- AI 助手:停靠在右侧(类似 VS Code 侧栏),默认显示 ----
        self.ai_dock = AIChatDock(self, self.settings)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.ai_dock)
        self.ai_dock.visibilityChanged.connect(self._on_ai_visibility)
        self._ai_show_action.setChecked(True)   # 默认显示(更显眼)
        self.ai_dock.show()

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

        # 左下角下载指示器:下载时显示 ⬇ 圆环进度,点击查看详情
        self._dl_log = []                      # 本次下载的状态消息流
        self._dl_progress = (0, 1)
        self.dl_indicator = DownloadIndicator(self)
        self.dl_indicator.clicked.connect(self.open_download_detail)
        self.statusBar().addWidget(self.dl_indicator, 0)   # 状态栏最左 = 窗口左下角
        self.dl_indicator.hide()

        # 运行中的实例指示:最外层显示"已有 x 个运行中的实例",悬停看具体是哪个
        self._running_instances = set()
        self._running_label = QLabel()
        self.statusBar().addPermanentWidget(self._running_label)   # 状态栏最右
        self._update_running_label()

    # ---- 设置 ----
    def open_settings(self, tab: str | None = None):
        """打开设置对话框,确定后刷新本窗口的设置。
        tab 可选 "mirror":直接切到镜像源页(设置菜单 → 镜像源…)"""
        from settings_dialog import SettingsDialog

        dlg = SettingsDialog(self.settings, self, tab=tab)
        if dlg.exec():
            self.settings = dlg.settings
            self.ai_dock.settings = dlg.settings
            self.ai_dock.update_vision_ui()   # 多模态开关变化 → 立即显示/隐藏图片按钮
            self.ai_dock.update_local_status()   # 本地模型 provider 切换 → 刷新状态
            self.ai_dock.maybe_preload_local()   # 切到内置本地模型 → 空闲期预热 server(§8.2)
            self.skill_mgr.settings = dlg.settings   # 技能启停状态同步
            self.resource_center.set_ui_mode(dlg.settings.get("ui_mode", "beginner"))
            self.refresh_instances()   # 游戏目录可能被改了,重新扫描
            self.statusBar().showMessage("设置已保存")

    def open_update_dialog(self):
        """设置 → 检查更新:AMCL 启动器 + bridge-mod(帮助菜单已移除,入口并入设置菜单)"""
        dlg = UpdateDialog(self)
        dlg.exec()

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
        """AI 菜单 → 显示/隐藏右侧对话栏"""
        self.ai_dock.setVisible(checked)

    def open_online_center(self):
        """打开联机方案中心(虚拟局域网/内网穿透/联机 Mod/官方方案)"""
        from online_center import OnlineCenterDialog
        OnlineCenterDialog(self).exec()

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
        """对话栏被点 × 关掉时,同步菜单勾选状态"""
        if hasattr(self, "_ai_show_action"):
            self._ai_show_action.setChecked(visible)

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
            f" 内存 {self.settings.get('memory_gb', 2)}G,"
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
        os.startfile(paths.GAME_DIR)

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
        """导入整合包(Modrinth .mrpack),后台执行不卡界面"""
        path, _f = QFileDialog.getOpenFileName(
            self, "选择整合包", "", "整合包 (*.mrpack *.zip)")
        if not path:
            return
        self.statusBar().showMessage("正在导入整合包...")

        def worker(status_cb, _progress_cb):
            instance_id = import_modpack_file(path, paths.GAME_DIR, status_callback=status_cb)
            status_cb(f"整合包导入完成:{instance_id} ✅")

        self._run_download(worker)

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
        # 左下角指示器:显示 + 归零
        self._dl_log = []
        self._dl_progress = (0, 1)
        self.dl_indicator.set_progress(0, 1)
        self.dl_indicator.setToolTip("下载中,点击查看详情")
        self.dl_indicator.show()

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
                QTimer.singleShot(2000, self.dl_indicator.hide)  # 2 秒后收起
                self._dl_finish(True)
            elif kind == "error":
                self.statusBar().showMessage(f"下载失败: {item[1]}")
                self._dl_log.append(f"❌ 下载失败: {item[1]}")
                self.dl_indicator.set_progress(1, 1)
                self.dl_indicator.setToolTip("下载失败,点击查看详情")
                QTimer.singleShot(2000, self.dl_indicator.hide)
                self._dl_finish(False)

    def open_download_detail(self):
        """点击左下角指示器:弹出下载详情"""
        done, total = self._dl_progress
        dlg = DownloadDetailDialog(self._dl_log, done, total, self)
        dlg.exec()

    def _dl_finish(self, _ok):
        self._busy_download(False)
        self.load_versions()
        self.refresh_instances()

    def _update_running_label(self):
        """刷新状态栏的"已有 x 个运行中的实例"(悬停显示具体实例)"""
        n = len(self._running_instances)
        if n:
            self._running_label.setText(f"🟢 已有 {n} 个运行中的实例")
            self._running_label.setToolTip("运行中的实例:\n" + "\n".join(sorted(self._running_instances)))
            self._running_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        else:
            self._running_label.setText("⚪ 已有 0 个运行中的实例")
            self._running_label.setToolTip("启动实例后这里会显示运行中的游戏")
            self._running_label.setStyleSheet("color: #888888;")

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

        # 填充筛选下拉(最近的一些正式版):各资源浏览器
        recent = [v["id"] for v in manifest["versions"]
                  if v["type"] == "release"][:40]
        for br in self.resource_center.browsers.values():
            if br.filter_version.count() == 0:
                br.filter_version.addItems(recent)

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
        try:
            d = self.load_version_data(v)
        except Exception as e:
            self.statusBar().showMessage(f"获取版本信息失败: {e}")
            return

        required_java = (d.get("javaVersion") or {}).get("majorVersion", 8)
        self._running_instance_id = d["id"]   # 供退出后自动 debug 定位日志

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
            game_dir = self.game_dir_for(d["id"])
            cmd = build_launch_command(
                d, game_dir, java_exe,
                username=self.settings.get("username", "Player"),
                memory_gb=self.settings.get("memory_gb", 2),
                assets_dir=os.path.join(paths.GAME_DIR, "assets"),
                install_dir=paths.GAME_DIR,
            )
        except Exception as e:
            self.dl_indicator.hide()
            self.statusBar().showMessage(f"启动准备失败: {e}")
            return

        # 3) 展开日志面板,显示要执行的命令(方便你理解"启动"到底是什么)
        self.log_view.clear()
        if not self.log_view.isVisible():
            self.log_toggle_btn.setChecked(True)  # 触发 _toggle_log 展开
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

        # 游戏内 AI 通道:off/cloud → 游戏启动前卸载本地模型(llama-server),把内存让给游戏;
        # local → 保持本地模型加载(游戏内 AI 通道,规划中)
        ai_in_game = self.settings.get("ai_in_game", "off")
        if ai_in_game != "local":
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

        # 通知技能系统:游戏已启动(崩溃守护等技能开始工作)
        self.skill_mgr.on_game_start(self.game_process, self._running_instance_id)

        # 4) 后台线程读游戏输出 → 队列 → 定时器搬到日志页(生产-消费模式)
        self.log_queue = queue.Queue()
        threading.Thread(target=self._read_process, daemon=True).start()
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self._drain_log)
        self.log_timer.start(100)

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
                if code not in (0, None):
                    self._auto_debug(code)   # 异常退出 → 自动收集日志给 AI 分析
                return
            self.log_view.appendPlainText(line)
            self.skill_mgr.on_game_log(line)   # 每行日志实时喂给技能(崩溃守护等)

    def _toggle_log(self, checked: bool):
        """展开/折叠底部游戏日志面板"""
        self.log_view.setVisible(checked)
        self.log_toggle_btn.setText(t("▼ 游戏日志", "▼ Game Log") if checked
                                    else t("▶ 游戏日志", "▶ Game Log"))

    # ---- 自动 debug:游戏异常退出时收集日志,让 AI 分析 ----
    def _auto_debug(self, code: int):
        """游戏进程异常退出(退出码非 0):自动抓最新日志 + 崩溃报告,问用户是否让 AI 分析"""
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
        """扫描实例,刷新:我的版本列表 + 下载 Mod 卡片 + versions 里的打小抄"""
        self._tidy_base_versions()   # 把纯基础原版收进 _versions 仓库(一次性迁移)
        instances = scan_instances(paths.GAME_DIR)

        # 隐藏"依赖型原版实例":被 Mod 实例继承、且没有自己存档的原版,
        # 只是加载器的地基,不单独显示(下载一个 Fabric 实例不会看到两个实例)
        bases_in_use = {i["base"] for i in instances if i["loader"]}
        shown = [i for i in instances
                 if not (i["loader"] is None and i["id"] in bases_in_use
                         and not os.path.isdir(os.path.join(self.game_dir_for(i["id"]), "saves")))]

        # 1) 我的版本列表(带封面)
        self.instance_list.clear()
        for inst in shown:
            item = QListWidgetItem(inst["label"])
            item.setData(Qt.ItemDataRole.UserRole, inst)
            icon = self._instance_icon(inst["id"])
            if icon:
                item.setIcon(icon)
            self.instance_list.addItem(item)
        # 同步到首页面板(实例数量 + 当前选择态)
        self.home_panel.set_current_instances(shown)

        # 3) 打小抄(实例清单备忘,可手动编辑)
        self.write_cheat_sheet(shown)

        # 4) 资源中心的目标实例卡片(Mod/光影/数据包浏览器)
        self.resource_center.refresh_browser_instances(shown)

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

        def worker(status, progress):
            from modrinth import download_mod
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
        """在 versions 目录生成"打小抄.txt":一份实例清单备忘,可手动编辑补充说明"""
        path = os.path.join(paths.GAME_DIR, "versions", "打小抄.txt")
        lines = [
            "我的实例小抄(启动器自动生成,可手动编辑补充,如每行后面加说明)",
            "=" * 32,
        ]
        for inst in instances:
            lines.append(f"{inst['id']}  ({inst['loader'] or '原版'} ← {inst['base']})")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:
            pass  # 备忘文件写不写都不影响功能

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
        menu.addAction("管理实例…", lambda: self.open_instance_manager(inst))
        menu.addAction("一键配置 bridge-mod(推荐)…", lambda: self._one_click_bridge_for(inst))
        rcon_menu_item = menu.addAction("一键配置 RCON(临时方案)…", lambda: self._one_click_rcon_for(inst))
        rcon_menu_item.setToolTip("临时方案:需要 Lan Server Properties + 进世界按 ESC → 对局域网开放")
        menu.addAction("启动", self.launch_selected_instance)
        menu.addAction("备份实例", lambda: self.backup_current_instance(inst))
        menu.addAction("打开实例目录", lambda: os.startfile(self.game_dir_for(inst["id"])))
        mods_dir = os.path.join(self.game_dir_for(inst["id"]), "mods")
        if os.path.isdir(mods_dir):
            menu.addAction("打开 mods 目录", lambda: os.startfile(mods_dir))
        menu.addSeparator()
        menu.addAction("删除实例…", lambda: self._delete_instance(inst))
        menu.exec(self.instance_list.mapToGlobal(pos))

    def _current_instance(self):
        """「我的版本」当前选中的实例;没选中返回 None"""
        item = self.instance_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

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
        """一键配置 bridge-mod(本地指令口,推荐):检测 → 确认 → 自动下载安装"""
        import bridge_mod_dist
        inst_dir = self.game_dir_for(inst["id"])
        if bridge_mod_dist.has_bridge_mod(inst_dir):
            QMessageBox.information(self, f"一键配置 · {inst['id']}",
                                    "✅ bridge-mod 已就绪:重进世界即可用本地指令口\n"
                                    "(无需'对局域网开放',指令结果可精确回传)。")
            return
        loader = inst.get("loader")
        if loader not in ("fabric", "forge", "neoforge"):
            QMessageBox.information(self, f"一键配置 · {inst['id']}",
                                    "该实例没有加载器(原版),bridge-mod 是 mod 需要加载器。\n"
                                    "先给这个实例装个 Fabric/Forge 等加载器再回来。")
            return
        info = bridge_mod_dist.bridge_mod_info(loader, inst["base"])
        if info is None:
            QMessageBox.information(
                self, f"一键配置 · {inst['id']}",
                f"版本表还没有 {inst['base']}+{loader} 的 bridge-mod。\n"
                "可先手动从 GitHub Releases 下载 jar 放进实例 mods 目录。")
            return
        ret = QMessageBox.question(self, f"一键配置 · {inst['id']}",
                                   "未安装 bridge-mod(本地指令口,推荐)。\n\n自动下载安装吗?")
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

    def _one_click_config_for(self, inst):
        """对指定实例执行一键配置(自动:bridge-mod 优先,版本表没覆盖时备选 RCON)。
        菜单里两个显式入口(bridge / RCON)之外的兜底逻辑。"""
        import bridge_mod_dist
        inst_dir = self.game_dir_for(inst["id"])
        if bridge_mod_dist.has_bridge_mod(inst_dir):
            QMessageBox.information(self, f"一键配置 · {inst['id']}",
                                    "✅ bridge-mod 已就绪:重进世界即可用本地指令口\n"
                                    "(无需'对局域网开放',指令结果可精确回传)。")
            return
        if inst.get("loader") in ("fabric", "forge", "neoforge") \
                and bridge_mod_dist.bridge_mod_info(inst["loader"], inst["base"]):
            self._one_click_bridge_for(inst)
            return
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
        """打开实例管理对话框(Mod/数据包/光影/YSM/TACZ/KubeJS/备份存档)"""
        from instance_manager import InstanceManagerDialog
        dlg = InstanceManagerDialog(inst, paths.GAME_DIR, self)
        dlg.exec()

    def _home_open_instance_manager(self, inst):
        """「我的版本」首页 → 实例设置/版本设置 需要打开实例管理时调用。

        没选中实例就提示,避免打开一个空管理界面让人困惑。"""
        if inst is None:
            QMessageBox.information(self, t("实例设置", "Instance settings"),
                                    t("请先在右侧「版本」里选中一个实例。",
                                      "Select an instance on the right first."))
            return
        self.open_instance_manager(inst)

    def _on_login_changed(self):
        """首页登录卡片改了离线昵称 → 重读设置,刷新登录显示。"""
        self.settings = load_settings()
        self.home_panel.refresh_login()
        self.statusBar().showMessage(t("登录信息已更新", "Login info updated"))

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

if __name__ == "__main__":
    print("正在获取版本列表(首次约几秒,请稍等)...")
    app = QApplication(sys.argv)

    # 首次启动:还没配置过游戏目录 → 弹引导界面(选路径 + 首次配置 AI)
    first = not (load_settings().get("game_dir") or "").strip()
    if first:
        from onboarding import OnboardingDialog
        OnboardingDialog().exec()

    window = MainWindow()
    window.load_versions()  # 启动时先加载一次
    window.show()
    sys.exit(app.exec())
