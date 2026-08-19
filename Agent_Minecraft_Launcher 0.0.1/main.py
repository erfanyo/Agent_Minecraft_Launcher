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

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
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
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from downloader import download_with_mirror  # 下载工具:镜像 + 进度 + sha1 校验
from assistant import AIChatDock, permission_instructions  # AI 助手(右侧停靠对话栏)
from download_tab import DownloadTab  # 下载新实例选项卡(左侧菜单 + 分类面板)
from fetch_versions import fetch_version_detail, fetch_version_manifest  # 网络模块
from game_files import install_version_files  # 按清单安装依赖库和资源文件
from instance_wizard import OPTIMIZE_MODS, SHADER_MODS  # 可选 Mod 清单
from instances import scan_instances  # 实例扫描(与 CLI/AI 共用)
from java_manager import ensure_java  # Java 检测与自动安装
from launcher import build_launch_command, resolve_inherited_json  # 版本 JSON → 启动命令
from loaders import install_loader  # Fabric / Forge 加载器安装
from modpack import import_modpack as import_modpack_file  # 整合包导入
from modrinth import download_mod, search_mods_cn  # Modrinth 搜索与下载(含中文名支持)
from paths import GAME_DIR, RUNTIME_DIR  # 游戏目录 / Java 运行时目录
from settings import load_settings, save_settings  # 启动器配置
from ui_style import arrow_style, card_style, hint_style, inner_style
from version_tree import fill_version_tree  # 版本树构建(与下载选项卡共用)


def _legacy_scan(game_dir: str = GAME_DIR) -> list:
    """兼容别名:scan_instances 已移到 instances.py"""
    return scan_instances(game_dir)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Agent Minecraft Launcher")
        self.setMinimumSize(700, 560)
        self.selected_version = None  # 记住当前选中的版本,供"下载"按钮使用
        self.settings = load_settings()  # 启动器配置(用户名/内存/版本隔离)

        # ---- 顶部:最新版本信息 + 刷新按钮 ----
        self.label_latest = QLabel("最新正式版: --")
        self.label_snapshot = QLabel("最新快照版: --")
        refresh_btn = QPushButton("刷新列表")
        refresh_btn.clicked.connect(self.load_versions)  # 信号槽:点按钮 → 执行函数

        top_bar = QHBoxLayout()
        top_bar.addWidget(self.label_latest)
        top_bar.addWidget(self.label_snapshot)
        top_bar.addStretch()  # 占位伸缩,把按钮挤到右边
        settings_btn = QPushButton("设置")
        settings_btn.clicked.connect(self.open_settings)
        top_bar.addWidget(settings_btn)
        top_bar.addWidget(refresh_btn)

        # ---- 菜单栏(基础启动器的骨架) ----
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")
        file_menu.addAction("导入整合包(Modrinth .mrpack)…", self.import_modpack)
        file_menu.addAction("打开游戏目录", self.open_game_dir)
        file_menu.addAction("清空所有实例…", self.clear_instances)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close)

        view_menu = menubar.addMenu("查看")
        self._inst_icons_action = view_menu.addAction("实例:大图标")
        self._inst_list_action = view_menu.addAction("实例:列表")
        for act in (self._inst_icons_action, self._inst_list_action):
            act.setCheckable(True)
        self._inst_icons_action.toggled.connect(
            lambda on: on and self.set_view_mode(self.instance_list, True, "instances"))
        self._inst_list_action.toggled.connect(
            lambda on: on and self.set_view_mode(self.instance_list, False, "instances"))

        # ---- AI 助手:顶级菜单(和"查看"同级,更显眼) ----
        ai_menu = menubar.addMenu("AI")
        self._ai_show_action = ai_menu.addAction("显示 AI 助手")
        self._ai_show_action.setCheckable(True)
        self._ai_show_action.toggled.connect(self._toggle_ai)
        ai_menu.addAction("AI 设置…", lambda: self.ai_dock.open_settings())

        # ---- Tab「我的版本」:扫描 versions 文件夹,显示已有实例 ----
        tab_a = QWidget()
        self.instance_list = QListWidget()
        self.instance_list.itemDoubleClicked.connect(self.launch_selected_instance)  # 双击启动
        self.launch_btn = QPushButton("启动所选实例")
        self.launch_btn.clicked.connect(self.launch_selected_instance)
        refresh_inst_btn = QPushButton("刷新")
        refresh_inst_btn.clicked.connect(self.refresh_instances)
        a_row = QHBoxLayout()
        a_row.addWidget(self.launch_btn)
        a_row.addWidget(refresh_inst_btn)
        a_row.addStretch()
        a_layout = QVBoxLayout(tab_a)
        a_layout.addLayout(a_row)
        a_layout.addWidget(self.instance_list)

        # ---- Tab「下载新实例」:左侧菜单 + 右侧分类面板 ----
        self.download_tab = DownloadTab()
        self.download_tab.bind_start(self.start_instance_download)

        # ---- Tab「下载 Mod」:目标实例 + 全局筛选 + 搜索结果卡片 ----
        tab_b = QWidget()
        # 目标实例:卡片列表(点击选中 + 箭头展开看已装 Mod)
        self.instance_cards_box = QWidget()
        self.instance_cards_layout = QVBoxLayout(self.instance_cards_box)
        self.instance_cards_layout.setContentsMargins(0, 0, 0, 0)
        self._mod_inst_cards = []      # [(inst, card)]
        self._selected_mod_inst = None

        # 全局筛选:游戏版本 + 加载器(决定搜索范围,也是卡片内部筛选的默认值)
        self.filter_version = QComboBox()
        self.filter_version.setEditable(True)
        self.filter_version.setToolTip("筛选的游戏版本,可自行输入(影响搜索和卡片默认值)")
        self.filter_loader = QComboBox()
        for label, value in [("全部加载器", None), ("Fabric", "fabric"),
                             ("Forge", "forge"), ("NeoForge", "neoforge"),
                             ("Quilt", "quilt")]:
            self.filter_loader.addItem(label, value)

        self.mod_search_edit = QLineEdit()
        self.mod_search_edit.setPlaceholderText("搜 Mod,如 sodium / 钠 / 想找的模组名")
        search_btn = QPushButton("搜索")
        search_btn.clicked.connect(self.on_search_mods)

        # 搜索结果:左侧列表(一级菜单),右侧详情面板(二级菜单:版本/加载器筛选 + 下载)
        self.mod_result_list = QListWidget()
        self.mod_result_list.currentItemChanged.connect(self._on_mod_selected)

        self.mod_panel = QWidget()
        self.mod_panel.setFixedWidth(300)
        self.mod_panel_empty = QLabel("← 在左侧选择一个 Mod\n展开它的版本 / 加载器选项")
        self.mod_panel_empty.setStyleSheet(hint_style())
        self.mod_panel_empty.setWordWrap(True)
        self.mod_icon = QLabel()
        self.mod_icon.setFixedSize(48, 48)
        self.mod_icon.setStyleSheet(inner_style())
        self.mod_title = QLabel("")
        self.mod_title.setWordWrap(True)
        self.mod_desc = QLabel("")
        self.mod_desc.setWordWrap(True)
        self.mod_desc.setStyleSheet(hint_style())
        self.mod_gv_combo = QComboBox()
        self.mod_loader_combo = QComboBox()
        self.mod_ver_combo = QComboBox()
        self.mod_dl_btn = QPushButton("下载到目标实例")
        self.mod_dl_btn.clicked.connect(self._mod_panel_download)
        self.mod_gv_combo.currentIndexChanged.connect(self._mod_panel_refresh_versions)
        self.mod_loader_combo.currentIndexChanged.connect(self._mod_panel_refresh_versions)

        panel_layout = QVBoxLayout(self.mod_panel)
        panel_layout.addWidget(self.mod_icon)
        panel_layout.addWidget(self.mod_title)
        panel_layout.addWidget(self.mod_desc)
        panel_layout.addWidget(QLabel("游戏版本:"))
        panel_layout.addWidget(self.mod_gv_combo)
        panel_layout.addWidget(QLabel("加载器:"))
        panel_layout.addWidget(self.mod_loader_combo)
        panel_layout.addWidget(QLabel("Mod 版本:"))
        panel_layout.addWidget(self.mod_ver_combo)
        panel_layout.addWidget(self.mod_dl_btn)
        panel_layout.addWidget(self.mod_panel_empty)
        panel_layout.addStretch()
        # 初始只显示占位提示
        for wdg in (self.mod_icon, self.mod_title, self.mod_desc, self.mod_gv_combo,
                    self.mod_loader_combo, self.mod_ver_combo, self.mod_dl_btn):
            wdg.setVisible(False)

        results_split = QHBoxLayout()
        results_split.addWidget(self.mod_result_list, 1)
        results_split.addWidget(self.mod_panel)

        b_layout = QVBoxLayout(tab_b)
        b_layout.addWidget(QLabel("目标实例(点击卡片选中,点箭头看已装 Mod):"))
        b_layout.addWidget(self.instance_cards_box)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("筛选:"))
        filter_row.addWidget(self.filter_version)
        filter_row.addWidget(self.filter_loader)
        search_row = QHBoxLayout()
        search_row.addWidget(self.mod_search_edit)
        search_row.addWidget(search_btn)
        b_layout.addLayout(filter_row)
        b_layout.addLayout(search_row)
        b_layout.addLayout(results_split, 1)

        # 右键菜单:实例(启动/打开目录/删除)
        self.instance_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.instance_list.customContextMenuRequested.connect(self._instance_menu)

        # ---- 主选项卡(我的版本 / 下载新实例 / 下载 Mod) ----
        self.main_tabs = QTabWidget()
        self.main_tabs.addTab(tab_a, "我的版本")
        self.main_tabs.addTab(self.download_tab, "下载新实例")
        self.main_tabs.addTab(tab_b, "下载 Mod")

        # ---- 底部:可折叠的游戏日志(默认收起) ----
        self.log_toggle_btn = QPushButton("▶ 游戏日志")
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

        # 游戏进程相关的运行时状态
        self.game_process = None
        self.log_queue = queue.Queue()
        self.log_timer = None
        self._icon_queue = queue.Queue()   # Mod 封面图下载队列(线程 → 定时器)
        self._icon_timer = None
        self._dl_queue = queue.Queue()     # 下载任务的状态/进度队列(线程 → 定时器)
        self._dl_timer = None

        # 应用视图模式(图标/列表,来自设置)
        self.set_view_mode(self.instance_list,
                           self.settings.get("view_icons_instances", False), "instances")

        self.refresh_instances()
        self.statusBar().showMessage("就绪")

    # ---- 设置 ----
    def open_settings(self):
        """打开设置对话框,确定后刷新本窗口的设置"""
        from settings_dialog import SettingsDialog

        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.settings
            self.ai_dock.settings = dlg.settings
            self.statusBar().showMessage("设置已保存")

    # ---- AI 助手 ----
    def _toggle_ai(self, checked: bool):
        """AI 菜单 → 显示/隐藏右侧对话栏"""
        self.ai_dock.setVisible(checked)

    def _on_ai_visibility(self, visible: bool):
        """对话栏被点 × 关掉时,同步菜单勾选状态"""
        if hasattr(self, "_ai_show_action"):
            self._ai_show_action.setChecked(visible)

    def ai_context(self) -> str:
        """给 AI 的上下文:启动器设置 + 当前选中的实例信息"""
        lines = [
            "你是 Agent Minecraft Launcher 启动器里内置的 AI 助手,用中文简洁回答。",
            f"启动器设置: 离线游戏名 {self.settings.get('username', 'Player')},"
            f" 内存 {self.settings.get('memory_gb', 2)}G,"
            f" 版本隔离 {'开' if self.settings.get('version_isolation', True) else '关'}",
        ]
        inst = self._selected_mod_inst
        item = self.instance_list.currentItem()
        if inst is None and item is not None:
            inst = item.data(Qt.ItemDataRole.UserRole)
        if inst:
            lines.append(f"当前选中的实例: {inst['id']}"
                         f"(加载器:{inst['loader'] or '原版'}, 基础版本:{inst['base']})")
        lines.append(permission_instructions(self.settings))
        lines.append("你可以调用工具:list_instances / search_mods / list_mods / "
                     "read_instance_log / read_crash_report / get_settings / "
                     "install_mod / backup_instance / set_setting。"
                     "写操作需要工作区写权限,装 Mod 前会自动备份。")
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
        os.makedirs(GAME_DIR, exist_ok=True)
        os.startfile(GAME_DIR)

    def clear_instances(self):
        """清空所有实例(versions 目录),共用文件(依赖库/资源/Java)保留"""
        if QMessageBox.question(
                self, "确认", "确定要删除所有实例吗?\n(versions 目录会被清空,共用文件保留)") != QMessageBox.StandardButton.Yes:
            return
        versions_dir = os.path.join(GAME_DIR, "versions")
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
            instance_id = import_modpack_file(path, GAME_DIR, status_callback=status_cb)
            status_cb(f"整合包导入完成:{instance_id} ✅")

        self._run_download(worker)

    # ---- 下载新实例:左侧菜单 → 分类面板 → 后台下载 ----
    def start_instance_download(self):
        """读取 DownloadTab 的汇总选择,后台线程创建实例(不卡界面)"""
        st = self.download_tab.state()
        if not st["version"] or st["loader_key"] is None:
            self.download_tab.set_status("请先选版本和加载器")
            return
        self._run_download(lambda status, progress: self.create_instance(
            st["version"], st["loader_key"], st["modrinth_loader"],
            st["shader"], st["optimize"],
            loader_version=st["loader_version"],
            shader_version=st["shader_version"],
            optimize_versions=st["optimize_versions"],
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
            elif kind == "progress":
                self.download_tab.set_progress(item[1], item[2])
            elif kind == "done":
                self.statusBar().showMessage("下载任务完成")
                self._dl_finish(True)
            elif kind == "error":
                self.statusBar().showMessage(f"下载失败: {item[1]}")
                self._dl_finish(False)

    def _dl_finish(self, _ok):
        self._busy_download(False)
        self.load_versions()
        self.refresh_instances()

    def _busy_download(self, busy: bool):
        self.download_tab.set_busy(busy)
        self.launch_btn.setEnabled(not busy)

    def _set_progress(self, done: int, total: int):
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)

    def game_dir_for(self, version_id: str) -> str:
        """PCL2 风格:versions/<版本ID>/ 就是该版本的实例(游戏目录)。
        版本隔离关闭时所有版本共用一个目录。"""
        if self.settings.get("version_isolation"):
            return os.path.join(GAME_DIR, "versions", version_id)
        return GAME_DIR

    def load_version_data(self, v: dict) -> dict:
        """取版本的完整数据:本地的(Mod 版本)从磁盘读并解析继承链,
        原版从 Mojang 清单拉取。"""
        if v.get("local"):
            return resolve_inherited_json(v["id"], GAME_DIR)
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

        self.label_latest.setText(f"最新正式版: {manifest['latest']['release']}")
        self.label_snapshot.setText(f"最新快照版: {manifest['latest']['snapshot']}")
        self.download_tab._load_tree()

        # 填充"下载 Mod"页的版本筛选下拉(最近的一些正式版)
        if self.filter_version.count() == 0:
            recent = [v["id"] for v in manifest["versions"]
                      if v["type"] == "release"][:40]
            self.filter_version.addItems(recent)

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
        inst_dir = os.path.join(GAME_DIR, "versions", d["id"])
        os.makedirs(inst_dir, exist_ok=True)
        with open(os.path.join(inst_dir, d["id"] + ".json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)

        try:
            # 1) 客户端 jar
            dest = os.path.join(GAME_DIR, "versions", d["id"], f"{d['id']}.jar")
            status_cb(f"下载客户端 {d['id']} ...")
            download_with_mirror(client["url"], dest, version_id=d["id"],
                                 sha1=client.get("sha1"), progress_callback=progress_cb)

            # 2) 依赖库 + 资源文件(自动跳过已存在的;单个失败不会中断)
            _downloaded, failures = install_version_files(
                d, GAME_DIR, progress_callback=progress_cb, status_callback=status_cb)
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

        def on_progress(done, total):
            self.progress_bar.setMaximum(max(total, 1))
            self.progress_bar.setValue(done)

        try:
            # 1) 保证有合适的 Java(没有就自动下载)
            java_exe = ensure_java(RUNTIME_DIR, required_java,
                                   progress_callback=on_progress,
                                   status_callback=self.statusBar().showMessage)
            # 2) 把版本 JSON 翻译成启动命令
            #    运行目录按隔离策略来;安装目录和资源目录是所有版本共享的
            game_dir = self.game_dir_for(d["id"])
            cmd = build_launch_command(
                d, game_dir, java_exe,
                username=self.settings.get("username", "Player"),
                memory_gb=self.settings.get("memory_gb", 2),
                assets_dir=os.path.join(GAME_DIR, "assets"),
                install_dir=GAME_DIR,
            )
        except Exception as e:
            self.statusBar().showMessage(f"启动准备失败: {e}")
            return

        # 3) 展开日志面板,显示要执行的命令(方便你理解"启动"到底是什么)
        self.log_view.clear()
        if not self.log_view.isVisible():
            self.log_toggle_btn.setChecked(True)  # 触发 _toggle_log 展开
        self.log_view.appendPlainText("> " + " ".join(cmd))
        self.statusBar().showMessage("游戏启动中...")
        self.launch_btn.setEnabled(False)

        try:
            self.game_process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", cwd=game_dir,
            )
        except Exception as e:
            self.statusBar().showMessage(f"启动失败: {e}")
            self.launch_btn.setEnabled(True)
            return

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
                return
            self.log_view.appendPlainText(line)

    def _toggle_log(self, checked: bool):
        """展开/折叠底部游戏日志面板"""
        self.log_view.setVisible(checked)
        self.log_toggle_btn.setText("▼ 游戏日志" if checked else "▶ 游戏日志")

    def create_instance(self, version: str, loader_key, modrinth_loader,
                        shader: bool, optimize: bool,
                        loader_version: str | None = None,
                        shader_version: str | None = None,
                        optimize_versions: dict | None = None,
                        status_cb=None, progress_cb=None):
        """下载一个"基础实例":原版本体 + (可选)加载器 + (可选)光影/优化 Mod。
        在后台线程运行,状态/进度通过回调上报(默认用主线程直调,兼容旧用法)。"""
        if status_cb is None:
            status_cb = self.statusBar().showMessage
        if progress_cb is None:
            progress_cb = self._set_progress

        status_cb(f"开始下载实例 {version} ...")

        # 1) 原版本体
        if not self.install_version(version, status_cb=status_cb, progress_cb=progress_cb):
            return

        # 2) 加载器
        instance_id = version
        if loader_key:
            try:
                instance_id = install_loader(loader_key, version, GAME_DIR,
                                             loader_version=loader_version,
                                             progress_callback=progress_cb,
                                             status_callback=status_cb)
            except Exception as e:
                status_cb(f"加载器安装失败: {e}")
                return

        # 3) 光影 / 优化 Mod(下载到该实例自己的 mods 目录)
        mods_dir = os.path.join(self.game_dir_for(instance_id), "mods")
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

        status_cb(f"实例就绪:{instance_id} ✅")

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
        instances = scan_instances(GAME_DIR)

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

        # 2) 下载 Mod 的目标实例:卡片列表(点击选中,箭头展开看已装 Mod)
        self._rebuild_instance_cards(shown)

        # 3) 打小抄(实例清单备忘,可手动编辑)
        self.write_cheat_sheet(shown)

    # ---- 目标实例卡片(与加载器选择同款,深浅色主题兼容) ----

    def _rebuild_instance_cards(self, instances: list):
        for _inst, card in self._mod_inst_cards:
            card.deleteLater()
        self._mod_inst_cards = []
        self._selected_mod_inst = None

        for inst in instances:
            card = QPushButton()
            card.setCheckable(True)
            card.setMinimumHeight(40)
            card.setStyleSheet(card_style())
            card.clicked.connect(lambda _c, i=inst: self._select_mod_instance(i))

            arrow = QPushButton("▸")
            arrow.setFixedWidth(26)
            arrow.setStyleSheet(arrow_style())
            arrow.clicked.connect(lambda _c, i=inst: self._toggle_mod_instance_mods(i))

            name_label = QLabel(inst["label"])
            name_label.setStyleSheet(inner_style())
            top = QHBoxLayout()
            top.setContentsMargins(8, 0, 4, 0)
            top.addWidget(name_label)
            top.addStretch()
            top.addWidget(arrow)

            mods_label = QLabel(self._instance_mods_text(inst))
            mods_label.setStyleSheet(inner_style())
            mods_label.setWordWrap(True)
            mods_label.setVisible(False)

            inner = QVBoxLayout(card)
            inner.setContentsMargins(0, 6, 0, 8)
            inner.addLayout(top)
            inner.addWidget(mods_label)

            self.instance_cards_layout.addWidget(card)
            self._mod_inst_cards.append((inst, card))

        self.instance_cards_layout.addStretch()

    def _select_mod_instance(self, inst):
        self._selected_mod_inst = inst
        for i, card in self._mod_inst_cards:
            card.setChecked(i["id"] == inst["id"])
        # 同步全局筛选到该实例的基础版本 + 加载器(卡片内部默认值也跟着变)
        self.filter_version.setCurrentText(inst["base"])
        idx = self.filter_loader.findData(inst["loader"])
        if idx >= 0:
            self.filter_loader.setCurrentIndex(idx)
        self.statusBar().showMessage(f"目标实例:{inst['id']}({inst['loader'] or '原版'} ← {inst['base']})")

    def _toggle_mod_instance_mods(self, inst):
        """展开卡片:显示该实例已装的 Mod 文件列表"""
        for i, card in self._mod_inst_cards:
            inner = card.layout()
            mods_label = inner.itemAt(inner.count() - 1).widget()
            if i["id"] == inst["id"]:
                show = not mods_label.isVisible()
                mods_label.setVisible(show)
                arrow = inner.itemAt(0).layout().itemAt(inner.itemAt(0).layout().count() - 1).widget()
                arrow.setText("▾" if show else "▸")
            else:
                mods_label.setVisible(False)

    @staticmethod
    def _instance_mods_text(inst: dict) -> str:
        """该实例 mods 目录里的文件清单(用于卡片展开)"""
        mods_dir = os.path.join(GAME_DIR, "versions", inst["id"], "mods")
        if not os.path.isdir(mods_dir):
            return "(还没有 Mod)"
        files = sorted(f for f in os.listdir(mods_dir) if f.endswith(".jar"))
        if not files:
            return "(mods 目录为空)"
        return "\n".join("• " + f for f in files)

    @staticmethod
    def _instance_icon(instance_id: str):
        """实例封面:优先版本 JSON 里的 favicon;没有就生成占位封面(色块+首字)"""
        try:
            vjson = os.path.join(GAME_DIR, "versions", instance_id, instance_id + ".json")
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
        path = os.path.join(GAME_DIR, "versions", "打小抄.txt")
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
        """实例右键:启动 / 打开目录 / 删除实例"""
        item = self.instance_list.itemAt(pos)
        if item is None:
            return
        inst = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction("启动", self.launch_selected_instance)
        menu.addAction("打开实例目录", lambda: os.startfile(self.game_dir_for(inst["id"])))
        mods_dir = os.path.join(self.game_dir_for(inst["id"]), "mods")
        if os.path.isdir(mods_dir):
            menu.addAction("打开 mods 目录", lambda: os.startfile(mods_dir))
        menu.addSeparator()
        menu.addAction("删除实例…", lambda: self._delete_instance(inst))
        menu.exec(self.instance_list.mapToGlobal(pos))

    def _delete_instance(self, inst):
        """删除一个实例(只删它自己,共用文件保留)"""
        if QMessageBox.question(
                self, "确认删除",
                f"确定删除实例 {inst['id']} 吗?\n(只删该实例,共用文件保留)") != QMessageBox.StandardButton.Yes:
            return
        shutil.rmtree(self.game_dir_for(inst["id"]), ignore_errors=True)
        self.statusBar().showMessage(f"实例已删除:{inst['id']}")
        self.refresh_instances()

    def _delete_installed_mod(self, path: str):
        if QMessageBox.question(self, "确认删除", f"删除 Mod 文件 {os.path.basename(path)}?") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(path)
            self.statusBar().showMessage(f"已删除:{os.path.basename(path)}")
        except Exception as e:
            self.statusBar().showMessage(f"删除失败: {e}")

    # ================= 下载 Mod:搜索列表(一级) + 详情面板(二级) =================
    def on_search_mods(self):
        """按筛选(版本 + 加载器)搜索 Mod,结果填进左侧列表"""
        query = self.mod_search_edit.text().strip()
        gv = self.filter_version.currentText().strip()
        loader = self.filter_loader.currentData()
        if not query:
            self.statusBar().showMessage("请输入搜索词")
            return
        self.statusBar().showMessage("正在搜索 Mod...")
        try:
            hits = search_mods_cn(query, gv, loader)
        except Exception as e:
            self.statusBar().showMessage(f"搜索失败: {e}")
            return

        self.mod_result_list.clear()
        self._clear_mod_panel()
        for h in hits:
            item = QListWidgetItem(f"{h['title']}   ⬇{h['downloads']:,}\n{h['description'][:50]}")
            item.setData(Qt.ItemDataRole.UserRole, h)
            self.mod_result_list.addItem(item)
        self.statusBar().showMessage(f"找到 {len(hits)} 个 Mod(点左侧结果,右侧展开选项)")
        self._fetch_mod_icons(hits)

    def _clear_mod_panel(self):
        """详情面板回到占位提示"""
        self._mod_panel_hit = None
        for wdg in (self.mod_icon, self.mod_title, self.mod_desc, self.mod_gv_combo,
                    self.mod_loader_combo, self.mod_ver_combo, self.mod_dl_btn):
            wdg.setVisible(False)
        self.mod_panel_empty.setVisible(True)

    def _on_mod_selected(self, current, _prev):
        """在左侧选中一个 Mod → 右侧详情面板(二级菜单)加载它的筛选选项"""
        if current is None:
            return
        h = current.data(Qt.ItemDataRole.UserRole)
        if h is None:
            return
        self._mod_panel_hit = h
        self.mod_panel_empty.setVisible(False)
        for wdg in (self.mod_icon, self.mod_title, self.mod_desc, self.mod_gv_combo,
                    self.mod_loader_combo, self.mod_ver_combo, self.mod_dl_btn):
            wdg.setVisible(True)
        self.mod_title.setText(h["title"])
        self.mod_desc.setText(h.get("description", "")[:120])
        self.mod_gv_combo.clear()
        self.mod_loader_combo.clear()
        self.mod_ver_combo.clear()
        self.statusBar().showMessage(f"加载 {h['title']} 的版本信息...")
        self._load_mod_panel(h)

    def _load_mod_panel(self, h: dict):
        """按全局筛选填默认值:项目支持的游戏版本/加载器 → 版本列表"""
        try:
            from modrinth import get_project
            proj = get_project(h["slug"])
            gvs, loaders = proj.get("game_versions", []), proj.get("loaders", [])
        except Exception:
            gvs, loaders = [], []

        for gv in reversed(gvs):
            self.mod_gv_combo.addItem(gv, gv)
        default_gv = self.filter_version.currentText().strip()
        idx = self.mod_gv_combo.findData(default_gv) if default_gv else -1
        self.mod_gv_combo.setCurrentIndex(idx if idx >= 0 else 0)

        for l in loaders:
            self.mod_loader_combo.addItem(l, l)
        default_ld = self.filter_loader.currentData()
        idx = self.mod_loader_combo.findData(default_ld) if default_ld else -1
        if idx >= 0:
            self.mod_loader_combo.setCurrentIndex(idx)

        self._mod_panel_refresh_versions()

    def _mod_panel_refresh_versions(self):
        """按面板里的"游戏版本 + 加载器"刷新 Mod 版本下拉(默认最新)"""
        gv = self.mod_gv_combo.currentData()
        loader = self.mod_loader_combo.currentData()
        self.mod_ver_combo.clear()
        if not gv or not loader or not getattr(self, "_mod_panel_hit", None):
            self.mod_ver_combo.addItem("(先选版本和加载器)", None)
            return
        try:
            from modrinth import list_mod_versions
            versions = list_mod_versions(self._mod_panel_hit["slug"], gv, loader)
        except Exception:
            versions = []
        for v in versions:
            self.mod_ver_combo.addItem(v, v)
        self.mod_ver_combo.setEnabled(bool(versions))

    def _mod_panel_download(self):
        """把面板当前选择的(版本/加载器/Mod版本)下载到目标实例的 mods 目录"""
        inst = self._selected_mod_inst
        hit = getattr(self, "_mod_panel_hit", None)
        if inst is None:
            self.statusBar().showMessage("请先在上方选择一个目标实例")
            return
        if hit is None:
            return
        if inst["loader"] not in ("fabric", "forge", "neoforge"):
            self.statusBar().showMessage("该实例不是 Mod 版本,无法安装 Mod")
            return
        gv = self.mod_gv_combo.currentData()
        loader = self.mod_loader_combo.currentData()
        ver = self.mod_ver_combo.currentData()
        if not gv or not loader:
            self.statusBar().showMessage("请先在面板里选游戏版本和加载器")
            return
        self._run_download(
            lambda status, progress: self._do_mod_download(hit, inst, gv, loader, ver, status, progress))

    def _do_mod_download(self, h, inst, gv, loader, ver, status_cb, _progress_cb):
        mods_dir = os.path.join(self.game_dir_for(inst["id"]), "mods")
        try:
            filename = download_mod(h["slug"], gv, loader, mods_dir, version_number=ver)
        except Exception as e:
            status_cb(f"下载失败: {e}")
            return
        if filename:
            status_cb(f"已安装到 {inst['id']}:{filename} ✅")
        else:
            status_cb(f"{h['title']} 暂无 {gv}+{loader} 的该版本")

    def _fetch_mod_icons(self, hits: list):
        """后台线程下载 Mod 封面小图 → 队列 → 定时器贴到列表项(生产-消费)"""
        if self._icon_timer is None:
            self._icon_timer = QTimer(self)
            self._icon_timer.timeout.connect(self._apply_mod_icons)
            self._icon_timer.start(120)

        def worker():
            for h in hits:
                url = h.get("icon_url")
                if not url:
                    continue
                try:
                    r = requests.get(url, timeout=10)
                    if r.status_code == 200 and r.content:
                        self._icon_queue.put((h["slug"], r.content))
                except Exception:
                    continue

        threading.Thread(target=worker, daemon=True).start()

    def _apply_mod_icons(self):
        """主线程:把下载好的封面贴到左侧列表对应项上"""
        while True:
            try:
                slug, content = self._icon_queue.get_nowait()
            except queue.Empty:
                return
            pixmap = QPixmap()
            if not pixmap.loadFromData(content):
                continue
            icon = QIcon(pixmap)
            for i in range(self.mod_result_list.count()):
                item = self.mod_result_list.item(i)
                h = item.data(Qt.ItemDataRole.UserRole)
                if h and h.get("slug") == slug:
                    item.setIcon(icon)
                    break
            # 也贴到详情面板
            if getattr(self, "_mod_panel_hit", None) and self._mod_panel_hit.get("slug") == slug:
                self.mod_icon.setPixmap(pixmap.scaled(
                    48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))


if __name__ == "__main__":
    print("正在获取版本列表(首次约几秒,请稍等)...")
    app = QApplication(sys.argv)
    window = MainWindow()
    window.load_versions()  # 启动时先加载一次
    window.show()
    sys.exit(app.exec())
