# -*- coding: utf-8 -*-
"""
AI 助手:停靠在主窗口右侧的对话栏(类似 VS Code 的 AI 侧栏)。

- 接 OpenAI 兼容接口:DeepSeek(默认)/ Ollama 本地 / 自定义
- 对话在后台线程跑,回复经信号回到主线程,不卡界面
- 主窗口通过 ai_context() 提供上下文(选中的实例、启动器设置等)作为系统提示
"""
from launcher_app.core.i18n import t
import base64
import json
import mimetypes
import os
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, cast

import requests
from PySide6.QtCore import QObject, QMimeData, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDrag,
    QDesktopServices,
    QIcon,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFrame,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QListView,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStyle,
    QToolButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from launcher_app.ai.ai_actions import (ALWAYS_CONFIRM_ACTIONS, PERMISSIONS, PermissionDenied, permission_instructions,
                        require_launcher_write, require_workspace_write)
from launcher_app.ai.agent_tools import TOOL_FUNCS
from launcher_app.ai.assistant_ui import (
    _esc,
    _ChatInput,
    ChoicePopupButton,
    AskUserPanel,
    collect_screenshots,
    ContextRing,
    estimate_tokens,
    InputPreferencesPopover,
    ModelEffortPopover,
    model_supports_vision,
    RecentScreenshotsDialog,
    SendWithRing,
)
from launcher_app.ai.chat_view import ChatEntry, ChatView, coerce_entries
from launcher_app.ui.ui_style import set_style, list_style, muted_color, accent_color, success_color, warning_color, danger_color, text_color, current_color, tab_style, popup_menu_style
from launcher_app.ui.ui_background import BackgroundWidget
from launcher_app.ui.ui_switch import ToggleSwitch, setting_switch_row
from settings import save_settings
from launcher_app.ai.assistant_defaults import _CLOUD_PROVIDERS, _LOCAL_MODES
from launcher_app.ai.settings_forms import (
    AISettingsForm, AIQuickSettingsForm, AISettingsDialog, _limit_combo_popup,
    _commit_combo_search, _setup_model_combo, _refresh_model_combo_search,
)

# Public compatibility exports; headless callers use the owning modules.
from launcher_app.ai.tool_catalog import (
    CLOUD_MAX_TOKENS, CLOUD_MAX_TOOLS, CONFIRM_TOOLS, GENERAL_TOOLS, MOD_READONLY_TOOLS, RESOURCE_STRONG_KEYWORDS, TOOLS, TOOL_GROUPS, TOOL_GROUP_KEYWORDS, TOOL_GROUP_LABELS, WRITE_TOOLS, _merge_plugin_tools, _resource_mode, _tool, available_tools, groups_for_text, mcp_tools_schemas, mount_tools_for, tools_for_text
)
from launcher_app.ai.tool_executor import (
    build_executor
)
from launcher_app.ai.response_router import (
    _cloud_available_settings, _cloud_chat, _cloud_settings_headless, _friendly_cloud_error, _human_wrap_result, _local_model_downloaded, _synthesize_tool_reply, chat_completion, chat_with_tools, route_answer
)
from launcher_app.ai.assistant_defaults import (
    LOCAL_MODEL_ID, LOCAL_PROVIDER, STRATEGY_CYCLE, STRATEGY_LABELS
)
from launcher_app.runtime.process_metrics import (
    _CPU_HOT_C, _MEM_LOW_MB, _PRIORITY_BELOW_NORMAL, _PRIORITY_IDLE, _PRIORITY_NORMAL, _cpu_temperature, _process_cpu_percent, _set_process_priority_class, _system_available_memory_mb
)
# 本地推理(§8.1 拍板模型):接入路由后才启用,懒加载
AI_DOCK_RETURN_MIME = "application/x-amcl-ai-dock-return"


class _Signals(QObject):
    reply = Signal(str)
    error = Signal(str)
    no_tool = Signal()
    self_test = Signal(bool)
    tool_called = Signal(str, dict, str)   # 工具调用过程展示(从 worker 线程 emit,主线程渲染)
    user_ask = Signal(str, list, object, object)   # (问题, 选项, 结果列表引用, 事件) 主线程显示卡片
    user_ask_cancel = Signal()
    action_confirm = Signal(str, str, object, object)  # (工具名, 预览文本, 结果列表, 事件) 主线程确认
    local_dl_start = Signal()              # 需要开始下载本地模型 → 主线程开下载(带进度弹窗)
    local_dl_progress = Signal(int, int)   # 本地模型下载进度(done, total)(跨线程)
    local_dl_done = Signal(str)            # 本地模型下载完成/失败的消息(跨线程)
    local_status = Signal(str)             # 本地模型状态文字(未下载/下载中/已就绪/推理中)(跨线程)
    # ---- t13 修复:worker 线程禁止直接碰 Qt 部件,一律走队列信号回主线程 ----
    system_msg = Signal(str)               # worker → 主线程:追加一条系统消息(_append_system)
    ring_update = Signal()                 # worker → 主线程:刷新上下文占用环(_update_ctx_ring)
    dl_progress = Signal(str, str, int, int)   # worker → 主线程:(title, status, done, total) 下载进度
    dl_done = Signal(str, bool, str)           # worker → 主线程:(title, ok, msg) 下载结束
    local_idle = Signal()                      # worker → 主线程:本地推理结束(用于「用完即卸」闲置卸载)


# 本地模型类型(下拉:标签, 值)——只留「内置」;Ollama/LM Studio 已移到 _CLOUD_PROVIDERS(OpenAI 兼容 API)


class _DockReturnButton(QToolButton):
    """Click to toggle dock; drag the same icon back into the launcher to dock."""

    def __init__(self, dock, parent=None):
        super().__init__(parent)
        self._dock = dock
        self._press_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dock.isFloating():
            self._press_pos = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._press_pos is not None
                and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._press_pos).manhattanLength()
                >= QApplication.startDragDistance()):
            self._press_pos = None
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(AI_DOCK_RETURN_MIME, b"ai-dock")
            drag.setMimeData(mime)
            pixmap = QPixmap(190, 40)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(current_color('bg1')))
            painter.drawRoundedRect(pixmap.rect().adjusted(1, 1, -1, -1), 9, 9)
            painter.setPen(QColor(text_color()))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "AI 助手 → 启动器")
            painter.end()
            drag.setPixmap(pixmap)
            drag.setHotSpot(pixmap.rect().center())
            main = self._dock.parentWidget()
            if main is not None and hasattr(main, '_show_ai_dock_drop_hint'):
                main._show_ai_dock_drop_hint()
            try:
                drag.exec(Qt.DropAction.MoveAction)
            finally:
                if main is not None and hasattr(main, '_hide_ai_dock_drop_hint'):
                    main._hide_ai_dock_drop_hint()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._press_pos is not None and event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = None
            self.click()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _DockHeader(BackgroundWidget):
    """One compact tab/drag/control row for docked and floating AI panels."""

    def __init__(self, dock, tabs):
        super().__init__(dock)
        self.dock = dock
        self.tabs = tabs
        self._system_move_active = False
        self._drag_offset = None
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 3, 4, 3)
        row.setSpacing(3)
        self.chat_button = QToolButton(self)
        self.chat_button.setText(t('聊天'))
        self.chat_button.setToolTip(t('AI 聊天'))
        self.chat_button.clicked.connect(lambda: tabs.setCurrentIndex(0))
        self.archive_button = QToolButton(self)
        self.archive_button.setText(t('记录/归档'))
        self.archive_button.setToolTip(t('聊天记录与归档'))
        self.archive_button.clicked.connect(lambda: tabs.setCurrentIndex(1))
        row.addWidget(self.chat_button)
        row.addWidget(self.archive_button)
        row.addStretch()
        self.float_button = _DockReturnButton(dock, self)
        self.float_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarNormalButton))
        self.float_button.setFixedSize(22, 22)
        self.float_button.clicked.connect(lambda: dock.setFloating(not dock.isFloating()))
        self.close_button = QToolButton(self)
        self.close_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton))
        self.close_button.setToolTip(t('隐藏 AI 助手'))
        self.close_button.setFixedSize(22, 22)
        self.close_button.clicked.connect(dock.hide)
        row.addWidget(self.float_button)
        row.addWidget(self.close_button)
        self.setFixedHeight(30)
        tabs.currentChanged.connect(self.refresh_theme)
        self.refresh_theme()
        self.update_floating_state(dock.isFloating())

    def paintEvent(self, event):
        super().paintEvent(event)
        from launcher_app.ui.ui_style import current_color
        color = QColor(current_color('bg1'))
        color.setAlpha(45)
        painter = QPainter(self)
        painter.fillRect(self.rect(), color)
        painter.end()

    def refresh_theme(self, *_args):
        from launcher_app.ui.ui_style import accent_color, current_color, muted_color, text_color
        for index, button in enumerate((self.chat_button, self.archive_button)):
            active = self.tabs.currentIndex() == index
            button.setStyleSheet(
                f'QToolButton {{ background: {current_color("tab_sel_bg") if active else "transparent"};'
                f' color: {text_color() if active else muted_color()}; border: none;'
                f' border-radius: 6px; padding: 3px 8px; font-weight: {"bold" if active else "normal"}; }}'
                f'QToolButton:hover {{ color: {accent_color()}; }}')
        for button in (self.float_button, self.close_button):
            button.setStyleSheet(
                f'QToolButton {{ background: transparent; color: {muted_color()};'
                ' border: none; border-radius: 5px; }'
                f'QToolButton:hover {{ background: {current_color("hover")}; color: {text_color()}; }}')
        self.update()

    def update_floating_state(self, floating):
        self.float_button.setToolTip(
            t('点击停靠；拖到主窗口左/右边缘也可停靠；双击顶部空白处停靠')
            if floating else t('浮出 AI 助手'))

    @staticmethod
    def _manual_move_on_xcb():
        return QApplication.platformName() == "xcb"

    def mousePressEvent(self, event):
        # Qt's system move is required on Wayland. On X11/XWayland, some window
        # managers accept the request but never move the undecorated dock, so
        # move it from the pointer delta instead.
        self._system_move_active = False
        self._drag_offset = None
        if event.button() == Qt.MouseButton.LeftButton and self.dock.isFloating():
            if self._manual_move_on_xcb():
                self._drag_offset = event.globalPosition().toPoint() - self.dock.pos()
                event.accept()
                return
            window = self.dock.windowHandle()
            self._system_move_active = bool(window is not None and window.startSystemMove())
            # Do not pass the same press back to QDockWidget, even if the
            # compositor declines it: Qt's own floating-dock grab interferes
            # with subsequent Wayland presses.
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            if event.buttons() & Qt.MouseButton.LeftButton:
                self.dock.move(event.globalPosition().toPoint() - self._drag_offset)
                sync_wallpaper = getattr(self.dock, "_sync_wallpaper_view", None)
                if sync_wallpaper is not None:
                    sync_wallpaper()
            event.accept()
            return
        if self._system_move_active:
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event):
        if self._drag_offset is not None:
            self._drag_offset = None
            if event.button() == Qt.MouseButton.LeftButton:
                self._snap_back_to_main(event.globalPosition().toPoint())
            event.accept()
            return
        if self._system_move_active:
            self._system_move_active = False
            event.accept()
            return
        event.ignore()

    def _snap_back_to_main(self, global_pos):
        main = self.dock.parentWidget()
        if main is None or not main.isVisible() or not hasattr(main, "addDockWidget"):
            return
        bounds = main.frameGeometry()
        if not bounds.top() <= global_pos.y() <= bounds.bottom():
            return
        left = abs(global_pos.x() - bounds.left())
        right = abs(global_pos.x() - bounds.right())
        if min(left, right) > 36:
            return
        area = (Qt.DockWidgetArea.LeftDockWidgetArea if left <= right
                else Qt.DockWidgetArea.RightDockWidgetArea)
        main.addDockWidget(area, self.dock)
        self.dock.setFloating(False)
        self.dock.show()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.dock.isFloating():
            self.dock.setFloating(False)
            event.accept()
            return
        event.ignore()


class _FloatingDockResizeGrip(QWidget):
    """Tell the compositor which *left* edge of a floating dock is being dragged."""

    def __init__(self, dock, edges, cursor):
        super().__init__(dock)
        self._dock = dock
        self._edges = edges
        self.setCursor(cursor)
        self.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dock.isFloating():
            window = self._dock.windowHandle()
            if window is not None and window.startSystemResize(self._edges):
                event.accept()
                return
        event.ignore()


class AIChatDock(QDockWidget):
    """右侧停靠的 AI 对话栏"""

    archive_changed = Signal()
    conversation_changed = Signal()

    def __init__(self, parent, settings: dict):
        super().__init__("AI 助手", parent)
        self._dock_header = None
        self.main = parent
        self.settings = settings

        self.signals = _Signals()
        self.signals.reply.connect(self._on_reply)
        self.signals.error.connect(self._on_error)
        self.signals.no_tool.connect(self._on_no_tool)
        self.signals.self_test.connect(self._on_self_test)
        # 工具调用过程展示:worker 线程只 emit 信号,渲染回到主线程(跨线程操作 UI 会崩)
        self.signals.tool_called.connect(self._show_tool)
        # ask_user 交互:worker 线程请求 → 主线程显示输入框上方卡片 → 结果回传
        self.signals.user_ask.connect(self._on_user_ask_ui)
        self.signals.user_ask_cancel.connect(self._cancel_user_ask)
        self.signals.action_confirm.connect(self._on_action_confirm_ui)
        # 本地模型下载(跨线程发信号,主线程更新进度弹窗,避免跨线程碰 UI)
        self.signals.local_dl_start.connect(self._start_local_download)
        self.signals.local_dl_progress.connect(self._on_local_dl_progress)
        self.signals.local_dl_done.connect(self._on_local_dl_done)
        self.signals.local_status.connect(self._on_local_status)
        # t13 修复:worker 线程的系统消息/上下文环更新也走队列信号(跨线程直接碰 UI 会原生崩溃)
        self.signals.system_msg.connect(self._append_system)
        self.signals.ring_update.connect(self._update_ctx_ring)
        # 下载进度/结束:worker 线程报告 → 主线程写到主窗口下载日志 + 左下角圆环(详情可点开看)
        self.signals.dl_progress.connect(self._on_dl_progress)
        self.signals.dl_done.connect(self._on_dl_done)
        # 用完即卸:本地推理结束 → 主线程安排闲置卸载(§5)
        self.signals.local_idle.connect(self._schedule_idle_unload)

        self.history = ChatView()
        self.history.anchorClicked.connect(self._on_anchor)  # 自己处理链接(展开工具日志/开外部链接)
        self.history.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history.customContextMenuRequested.connect(self._show_history_menu)
        self.input = _ChatInput()
        self.input.setPlaceholderText(t('问 AI 任何问题…(Enter 发送, Shift+Enter 换行;Ctrl+V 可粘贴图片)'))
        self.input.returnPressed.connect(self.send)
        self.input.sendClicked.connect(self.send)
        self.input.testClicked.connect(self.self_test_tools)   # 🛠 已移进输入框,挨着发送
        self.input.imageClicked.connect(self._pick_images)
        self.input.imagePasted.connect(self._add_image_data)
        self.input.recentClicked.connect(self._pick_recent_screenshots)
        # 顶部 Dock 标题与标签页合为一行；聊天页内只放策略与技能入口。
        # AI 策略入口已移至发送键左边的「模型」面板(参考 Codex);顶部不再放独立策略按钮。
        skills_btn = QPushButton(t('技能与可选功能…'))
        skills_btn.setToolTip(t('管理 AI 技能、运行辅助和实验性工作流'))
        skills_btn.clicked.connect(self.open_skill_manager)
        set_style(skills_btn, lambda:
            f"QPushButton {{ background: transparent; color: {muted_color()}; border: 1px solid {current_color('btn_border')};"
            f" border-radius: 6px; padding: 3px 8px; }}"
            f"QPushButton:hover {{ color: {text_color()}; border-color: {accent_color()}; }}")
        undo_btn = QPushButton(t('撤销设置'))
        undo_btn.setToolTip(t('撤销最近一次由 AI 完成的设置修改；Mod 安装请使用自动备份恢复'))
        undo_btn.clicked.connect(self._undo_last_setting)
        set_style(undo_btn, lambda:
            f"QPushButton {{ background: transparent; color: {muted_color()}; border: 1px solid {current_color('btn_border')};"
            f" border-radius: 6px; padding: 3px 8px; }}"
            f"QPushButton:hover {{ color: {text_color()}; border-color: {accent_color()}; }}")
        action_log_btn = QPushButton(t('操作记录'))
        action_log_btn.setToolTip(t('查看 AI 修改了什么，以及可用的回退信息。'))
        action_log_btn.setToolTip(t('查看 AI 已确认、取消或失败的操作，以及是否可回退'))
        action_log_btn.clicked.connect(self._show_action_history)
        set_style(action_log_btn, lambda:
            f"QPushButton {{ background: transparent; color: {muted_color()}; border: 1px solid {current_color('btn_border')};"
            f" border-radius: 6px; padding: 3px 8px; }}"
            f"QPushButton:hover {{ color: {text_color()}; border-color: {accent_color()}; }}")
        top_row = QHBoxLayout()
        top_row.setContentsMargins(2, 0, 2, 0)
        # 本地模型状态(未下载/下载中/已就绪/推理中),仅本地 provider 时显示
        self.local_status_label = QLabel("")
        self.local_status_label.setVisible(False)
        top_row.addSpacing(6)
        top_row.addWidget(self.local_status_label)
        top_row.addStretch()
        top_row.addWidget(skills_btn)

        # 「偏好」气泡面板:操作确认 / 文件权限 两项收在一起,
        # 从输入栏按钮弹出(Qt.Popup + 屏幕钳制,不会冲出窗口),点选即生效并保存。
        self.preferences_popover = InputPreferencesPopover(self)
        self.preferences_popover.add_option(
            "response_style", "普通用户语言", "plain", "重点说明结果、影响和下一步。")
        self.preferences_popover.add_option(
            "response_style", "技术详情", "technical", "附带日志证据、版本、路径和处理细节。")
        self.preferences_popover.add_option(
            "confirmation_mode", "每项都确认", "per_action", "每次操作前都由你确认。")
        self.preferences_popover.add_option(
            "confirmation_mode", "备份后连续处理", "backup_continue",
            "先备份再连续处理；恢复旧状态、换实例或改变世界时仍会询问。")
        self.preferences_popover.add_option(
            "permission", "只读", "readonly", "AI 只能查看,不能改任何文件。")
        self.preferences_popover.add_option(
            "permission", "日常可写", "launcher_write", "安装 Mod、改游戏和启动器设置(推荐)。")
        self.preferences_popover.add_option(
            "permission", "工作区可写", "workspace_write", "还允许生成插件、修改启动器源码;仅在让 AI 改 AMCL 本身时开启。")
        self.preferences_popover.set_on_select(self._on_preference_selected)
        self.input.preferencesClicked.connect(self._show_input_preferences)

        # 模型 + 思考程度入口(发送键左边,参考 Codex):选模型 + 调思考/模拟悟程度
        self.model_effort_popover = ModelEffortPopover(self)
        self.model_effort_popover.modelChanged.connect(self._on_input_model_changed)
        self.model_effort_popover.effortChanged.connect(self._on_input_effort_changed)
        self.model_effort_popover.strategyChanged.connect(self._set_strategy)
        self.input.modelEffortClicked.connect(self._show_model_effort)

        audit_row = QHBoxLayout()
        audit_row.addStretch()
        audit_row.addWidget(action_log_btn)
        audit_row.addWidget(undo_btn)

        row = QVBoxLayout()
        row.setSpacing(4)
        row.addWidget(self.input, 1)
        stop_run = QPushButton(t('停止任务'))
        stop_run.setToolTip(t('在当前请求或工具结束后停止，不会强杀正在写文件的操作'))
        stop_run.clicked.connect(self._stop_agent_run)
        run_records = QPushButton(t('任务记录'))
        run_records.setToolTip(t('打开整轮 AI 任务日志：模型回复、工具调用、结果与结束原因。'))
        run_records.setToolTip(t('打开本机逐轮记录；包含终止原因，模型结束不等于测试通过'))
        run_records.clicked.connect(self._open_run_records)
        task_row = QHBoxLayout()
        task_row.setContentsMargins(0, 0, 0, 0)
        task_row.setSpacing(4)
        task_row.addStretch()
        self.quote_button = QPushButton(t('引用选中内容'))
        self.quote_button.setToolTip(t('选中上方对话的一段文字，添加注释后放入输入框'))
        self.quote_button.clicked.connect(self._quote_selected_conversation)
        self.quote_button.hide()
        task_row.addWidget(self.quote_button)
        task_row.addWidget(stop_run)
        task_row.addWidget(run_records)
        row.addLayout(task_row)
        # 局部紧凑样式，不受主窗口大按钮的最小宽度和内边距影响。
        for button in (skills_btn, undo_btn, action_log_btn,
                       self.quote_button, stop_run, run_records):
            button.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {muted_color()};"
                f" border: 1px solid {current_color('btn_border')}; border-radius: 5px;"
                " padding: 1px 4px; min-width: 0px; min-height: 0px; font-size: 12px; }"
                f"QPushButton:hover {{ border-color: {accent_color()}; }}")
            button.setFixedHeight(24)
        self.local_status_label.setWordWrap(True)

        # 图片行:输入框上方 —— 左侧待发图片缩略图(上下文环已移到发送按钮外圈)
        self.pending_images = []     # [{"path": ...}] 待发送的图片
        self._thumb_widgets = []     # 与 pending_images 一一对应的缩略图 widget
        self.thumb_row = QHBoxLayout()
        self.thumb_row.setContentsMargins(0, 0, 0, 0)
        self.thumb_row.setSpacing(6)
        img_row_widget = QWidget()
        irl = QHBoxLayout(img_row_widget)
        irl.setContentsMargins(2, 2, 2, 0)
        irl.addLayout(self.thumb_row)
        irl.addStretch()
        self.img_row_widget = img_row_widget
        self.ask_user_panel = AskUserPanel()
        self.ask_user_panel.submitted.connect(self._finish_user_ask)
        self.ask_user_panel.canceled.connect(self._cancel_user_ask)
        self._pending_user_ask = None

        container = BackgroundWidget()   # 壁纸模式下 AI dock 内容区也画同张壁纸+遮罩(不割裂)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # ---- 用标签页:0=聊天(原内容) 1=聊天记录·归档 ----
        self.tabs = QTabWidget()
        set_style(self.tabs, tab_style)   # 透明标签条/面板,壁纸透出
        # Tab0: 聊天(历史+权限+图片+输入)
        chat_tab = QWidget()
        self._chat_tab = chat_tab
        self._focus_mode = False
        chat_lay = QVBoxLayout(chat_tab)
        chat_lay.setContentsMargins(8, 4, 8, 4)
        chat_lay.setSpacing(6)
        self.focus_target_label = QLabel()
        self.focus_target_label.setWordWrap(True)
        set_style(self.focus_target_label, lambda:
                  f'color: {muted_color()}; font-size: 12px; padding: 3px 5px;')
        self.focus_target_label.hide()
        chat_lay.addWidget(self.focus_target_label)
        chat_lay.addLayout(top_row)            # 顶部:技能管理入口
        self.focus_welcome = QWidget()
        welcome_lay = QVBoxLayout(self.focus_welcome)
        welcome_lay.addStretch()
        welcome_title = QLabel(t('你想让我们在 AMCL 中构建什么？'))
        welcome_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_title.setWordWrap(True)
        set_style(welcome_title, lambda:
                  f'color: {text_color()}; font-size: 25px; font-weight: bold;')
        welcome_lay.addWidget(welcome_title)
        welcome_hint = QLabel(t('可以从安装 Mod、整理实例或分析崩溃开始。'))
        welcome_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_hint.setWordWrap(True)
        set_style(welcome_hint, lambda: f'color: {muted_color()}; font-size: 13px;')
        welcome_lay.addWidget(welcome_hint)
        welcome_lay.addStretch()
        self.focus_welcome.hide()
        chat_lay.addWidget(self.focus_welcome, 1)
        chat_lay.addWidget(self.history, 1)    # 历史区上下弹性伸缩
        chat_lay.addLayout(audit_row)
        from launcher_app.ai.ai_context_pins import ContextPins
        self.context_pins = ContextPins(self)
        chat_lay.addWidget(self.context_pins)
        chat_lay.addWidget(self.img_row_widget)  # 图片缩略图 + 上下文环
        chat_lay.addWidget(self.ask_user_panel)
        chat_lay.addLayout(row)                 # 输入行
        self.tabs.addTab(chat_tab, t('💬 聊天'))
        # Tab1: 聊天记录·归档
        self.tabs.addTab(self._build_archive_tab(), t('🗂 记录/归档'))
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.tabBar().hide()
        layout.addWidget(self.tabs, 1)
        self.setWidget(container)
        self._container = container
        self._dock_header = _DockHeader(self, self.tabs)
        self.setTitleBarWidget(self._dock_header)
        self.topLevelChanged.connect(self._on_floating_changed)
        self.setMinimumWidth(320)
        self.setObjectName("AIChatDock")
        self._left_resize_grips = (
            _FloatingDockResizeGrip(self, Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
                                    Qt.CursorShape.SizeFDiagCursor),
            _FloatingDockResizeGrip(self, Qt.Edge.LeftEdge,
                                    Qt.CursorShape.SizeHorCursor),
            _FloatingDockResizeGrip(self, Qt.Edge.LeftEdge | Qt.Edge.BottomEdge,
                                    Qt.CursorShape.SizeBDiagCursor),
        )
        self._other_resize_grips = (
            _FloatingDockResizeGrip(self, Qt.Edge.RightEdge | Qt.Edge.TopEdge,
                                    Qt.CursorShape.SizeBDiagCursor),
            _FloatingDockResizeGrip(self, Qt.Edge.RightEdge,
                                    Qt.CursorShape.SizeHorCursor),
            _FloatingDockResizeGrip(self, Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
                                    Qt.CursorShape.SizeFDiagCursor),
            _FloatingDockResizeGrip(self, Qt.Edge.BottomEdge,
                                    Qt.CursorShape.SizeVerCursor),
        )

        self._tool_id = 0              # 工具调用编号
        self._entries = []             # 展示流(ChatEntry);渲染交给 chat_view
        self._tool_expand_levels = {}  # 工具折叠级别:0摘要 / 1参数+结果摘要 / 2完整结果
        self._expanded_ai = set()      # 已展开的长 AI 回答(按 _entries 中的索引)
        self._chat_messages = []       # 真正的对话历史(喂给 LLM 的消息,不含 system)
        self._session_instance_id = ''  # 会话首次提问时的目标实例，供左侧归档分组
        self._session_dirty = False
        self._local_engine = None      # 本地推理引擎(懒加载单例,见 _get_local_engine)
        self._local_downloading = False   # 本地模型下载中标志
        self._local_preloading = False    # 本地模型预热中标志(§8.2 冷启动预加载)
        self._local_dlg = None            # 下载进度弹窗
        # ---- 性能策略(§5)状态:量化提示 / 主动避让 / 用完即卸 / 温控意识 ----
        self._inferring = False           # 本地推理进行中(CPU 采样/闲置卸载据此判断)
        self._game_running = False        # 是否有游戏进程在跑(主动避让:降推理优先级/暂停)
        self._game_proc = None            # 运行中的游戏进程(用于判断存活)
        self._cpu_sample = {}             # 量化提示:CPU 采样状态 {cpu, t}
        self._idle_timer = None           # 用完即卸:闲置卸载 QTimer
        self._hot_warned_at = 0.0         # 温控意识:上次高温提醒时间(避免刷屏)
        self._infer_monitor_stop = threading.Event()   # CPU 采样监控线程停止标志
        self._append_system("AI 助手就绪。选中实例后提问,我会带上实例上下文;"
                            "我还能调用工具(列实例/搜 Mod/读日志等),写操作需要\"工作区可写\"权限。")
        self.update_vision_ui()        # 按模型是否支持多模态显示/隐藏图片按钮
        self.update_local_status()     # 本地模型状态(未下载/已就绪)
        # §8.2 冷启动预加载:若默认就是内置本地模型,开机空闲期就预热 server
        QTimer.singleShot(2000, self.maybe_preload_local)
        # §5 性能策略:CPU 采样监控线程(量化提示);daemon,不阻塞退出。见 shutdown() 置停。
        threading.Thread(target=self._infer_monitor_loop, daemon=True).start()

    def _on_floating_changed(self, floating):
        if self._dock_header is not None:
            self._dock_header.update_floating_state(floating)
            self._dock_header._system_move_active = False
            self._dock_header._drag_offset = None
        # On Wayland, switch the floating dock to native window decorations
        # after the initial undocking drag ends. A custom QDockWidget title bar
        # suppresses those decorations, and a second drag may be accepted by
        # startSystemMove without actually moving the independent window.
        wayland = self._is_wayland()
        movable = QDockWidget.DockWidgetFeature.DockWidgetMovable
        features = self.features()
        wanted = features & ~movable if floating and not wayland else features | movable
        if wanted != features:
            self.setFeatures(wanted)
        if wayland:
            QTimer.singleShot(0, self._sync_wayland_titlebar)
        self._position_left_resize_grips()
        # Qt may finish changing QDockWidget's native window after this signal.
        QTimer.singleShot(0, self._position_left_resize_grips)
        # Linux window managers can publish the floating window's global
        # position one event-loop turn after topLevelChanged.
        sync_wallpaper = getattr(self, "_sync_wallpaper_view", None)
        if sync_wallpaper is not None:
            QTimer.singleShot(0, sync_wallpaper)

    @staticmethod
    def _is_wayland():
        return QApplication.platformName().startswith("wayland")

    def _sync_wayland_titlebar(self):
        if not self._is_wayland():
            return
        header = getattr(self, "_dock_header", None)
        container = getattr(self, "_container", None)
        layout = container.layout() if container is not None else None
        if header is None or layout is None:
            return
        if self.isFloating():
            if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
                QTimer.singleShot(50, self._sync_wayland_titlebar)
                return
            if self.titleBarWidget() is header:
                self.setTitleBarWidget(None)
                layout.insertWidget(0, header)
                header.setToolTip(t('拖动上方系统标题栏可移动 AI 浮窗'))
        elif self.titleBarWidget() is not header:
            layout.removeWidget(header)
            header.setToolTip("")
            self.setTitleBarWidget(header)

    def _position_left_resize_grips(self):
        grips = getattr(self, '_left_resize_grips', ())
        others = getattr(self, '_other_resize_grips', ())
        if not grips and not others:
            return
        for grip in (*grips, *others):
            grip.setVisible(self.isFloating())
        if not self.isFloating():
            return
        # Keep the hit targets flush to the *outer* edge. Top-left is shallow
        # so the first tab still works; the vertical strip is broad enough to
        # grab on a touchpad without covering the conversation controls.
        width, corner = 16, 24
        height = max(0, self.height())
        grips[0].setGeometry(0, 0, corner, 8)
        grips[1].setGeometry(0, 30, width, max(0, height - corner - 30))
        grips[2].setGeometry(0, max(0, height - corner), corner, corner)
        if others:
            right = max(0, self.width() - width)
            others[0].setGeometry(max(0, self.width() - corner), 0, corner, 8)
            others[1].setGeometry(right, 30, width, max(0, height - corner - 30))
            others[2].setGeometry(max(0, self.width() - corner),
                                  max(0, height - corner), corner, corner)
            others[3].setGeometry(corner, max(0, height - width),
                                  max(0, self.width() - 2 * corner), width)
        for grip in (*grips, *others):
            grip.raise_()

    def _sync_wallpaper_view(self):
        """按与本窗口中央区的相对位置,更新本 dock 显示的壁纸片段(共享模式)。
        效果:AI dock 的壁纸是主窗壁纸的「局部放大/平移」,横向连续;浮动后左右移动
        会切换到对应位置的片段。"""
        main = self.main
        scaled = getattr(main, "_wallpaper_scaled", None)
        c = getattr(self, "_container", None)
        header = getattr(self, "_dock_header", None)
        if c is None:
            return
        if scaled is None:
            c.clear()
            if header is not None:
                header.clear()
            return
        ox = getattr(main, "_wallpaper_ox", 0)
        oy = getattr(main, "_wallpaper_oy", 0)
        mask = getattr(main, "_wallpaper_mask", 0.6)
        central = (getattr(main, 'ai_focus_sidebar', None)
                   if getattr(main, '_ai_focus_mode', False)
                   else getattr(main, '_background', None))
        if central is None:
            return
        dg = c.mapToGlobal(c.rect().topLeft())
        cg = central.mapToGlobal(central.rect().topLeft())
        dx = dg.x() - cg.x()
        dy = dg.y() - cg.y()
        floating = self.isFloating()
        c.set_shared_view(scaled, ox + dx, oy + dy, mask, wrap=floating)
        if header is not None:
            hg = header.mapToGlobal(header.rect().topLeft())
            header.set_shared_view(scaled, ox + hg.x() - cg.x(),
                                   oy + hg.y() - cg.y(), mask, wrap=floating)

    def moveEvent(self, e):
        super().moveEvent(e)
        self._sync_wallpaper_view()
        if self.isFloating():
            QTimer.singleShot(0, self._sync_wallpaper_view)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._position_left_resize_grips()
        self._update_focus_margins()
        self._sync_wallpaper_view()

    def set_focus_mode(self, enabled: bool):
        """Center the live conversation when the dock fills the main window."""
        self._focus_mode = bool(enabled)
        if self._focus_mode:
            self._focus_show_history = False
        self.focus_target_label.setVisible(self._focus_mode)
        self.quote_button.setVisible(self._focus_mode)
        if self._focus_mode:
            self.context_pins.cancel()
        self.context_pins.setVisible(not self._focus_mode)
        self._update_focus_empty_state()
        self._update_focus_margins()

    def update_focus_target(self, inst):
        name = (inst or {}).get('name') or (inst or {}).get('id')
        self.focus_target_label.setText(
            t('当前目标实例：{v0}  ·  {v1} {v2}').format(v0=(name), v1=((inst or {}).get("base", "")), v2=((inst or {}).get("loader", ""))) if name else
            t('当前目标实例：未选择  ·  发送安装或修复任务前请选择实例'))

    def _update_focus_empty_state(self):
        if not hasattr(self, 'focus_welcome'):
            return
        has_user_message = any(entry.kind in ('user', 'amcl') for entry in self._entries)
        empty = (self._focus_mode and not has_user_message
                 and not getattr(self, '_focus_show_history', False))
        self.focus_welcome.setVisible(empty)
        self.history.setVisible(not empty)

    def _show_history_menu(self, pos):
        menu = self.history.createStandardContextMenu()
        if self._focus_mode and self.history.textCursor().hasSelection():
            menu.addSeparator()
            menu.addAction(t('引用并添加注释…'), self._quote_selected_conversation)
        menu.exec(self.history.mapToGlobal(pos))

    def _quote_selected_conversation(self):
        selected = self.history.textCursor().selectedText().replace('\u2029', '\n').strip()
        if not selected:
            QMessageBox.information(self, t('引用对话'), t('先在对话中选中想引用的文字。'))
            return
        annotation, accepted = QInputDialog.getMultiLineText(
            self, t('引用对话'), t('给这段会话添加注释：'))
        if not accepted:
            return
        excerpt = selected[:2000]
        if len(selected) > 2000:
            excerpt += '\n…（引用已截断）'
        quote = '\n'.join('> ' + line for line in excerpt.splitlines())
        note = annotation.strip()
        addition = quote + (f'\n注释：{note}' if note else '')
        current = self.input.text().strip()
        self.input.setText((current + '\n\n' if current else '') + addition + '\n')
        self.input.setFocus()

    def _update_focus_margins(self):
        chat = getattr(self, '_chat_tab', None)
        if chat is None:
            return
        side = max(12, (self.width() - 980) // 2) if self._focus_mode else 8
        chat.layout().setContentsMargins(side, 10 if self._focus_mode else 4,
                                         side, 14 if self._focus_mode else 4)

    def update_vision_ui(self):
        """按所选模型是否支持看图(多模态)显示/隐藏图片相关按钮。

        优先依据模型名判定(见 model_supports_vision);无法判定的本地/自定义模型
        才回退到用户手动的 ai_multimodal 开关。设置对话框保存后也会调用。"""
        vis = model_supports_vision(self.settings.get("ai_provider"),
                                    self.settings.get("ai_model"))
        if vis is None:
            on = bool(self.settings.get("ai_multimodal", False))
        else:
            on = vis
        self.input.set_vision_enabled(on)
        # 未选择模型 → 隐藏发送/自测按钮,占位提示去设置里选
        has_model = bool((self.settings.get("ai_model") or "").strip()) \
            or bool((self.settings.get("ai_local_model") or "").strip())
        self.input.set_has_model(has_model)
        # 模型不支持图片时,清掉还没发送的图片(按钮已隐藏,防止残留)
        if not on and self.pending_images:
            self.pending_images = []
            self._rebuild_thumb_row()
            self._append_system("当前模型不支持图片输入,已清除待发送的图片。")
        self._update_model_badge(vis)

    # ---- AI 策略(顶部按钮直接切换三档) ----
    def _current_strategy(self) -> str:
        s = self.settings.get("ai_strategy", "local_first") or "local_first"
        return s if s in STRATEGY_CYCLE else "local_first"

    def _set_strategy(self, key: str):
        """切换到某档策略:写 settings 并立即生效(由「模型」面板策略单选触发)。"""
        if key not in STRATEGY_CYCLE:
            return
        self.settings["ai_strategy"] = key
        if getattr(self, "main", None) is not None:
            self.main.settings["ai_strategy"] = key
        try:
            save_settings(self.settings)
        except Exception:
            pass
        self._append_system(f"AI 策略已切换为:{STRATEGY_LABELS.get(key, key)}(立即生效)")

    def _open_ai_settings(self):
        """打开主窗口的设置对话框(AI 助手页)。"""
        try:
            if getattr(self, "main", None) is not None and hasattr(self.main, "open_settings"):
                self.main.open_settings()
        except Exception:
            pass

    def _update_model_badge(self, vis):
        """顶部策略按钮已删除;此方法保留兼容(策略/模型信息现在在「模型」面板里)。"""
        return

    def _vision_on(self) -> bool:
        return bool(self.settings.get("ai_multimodal", False))

    # ---- 「偏好」气泡面板:回答方式 / 操作确认 / 文件权限 ----
    def _sync_preference_popover(self):
        """把当前设置值回填到偏好面板的选中卡片(打开前/外部改设置后同步)。"""
        self.preferences_popover.set_current(
            "response_style", self.settings.get("ai_response_style", "plain"))
        self.preferences_popover.set_current(
            "confirmation_mode", self.settings.get("ai_confirmation_mode", "per_action"))
        self.preferences_popover.set_current(
            "permission", self.settings.get("ai_permission", "launcher_write"))

    def _show_input_preferences(self):
        btn = self.input.preferences_btn
        self._sync_preference_popover()
        anchor = btn.mapToGlobal(btn.rect().bottomLeft())
        self.preferences_popover.pop_at(anchor)

    # ---- 模型 + 思考程度入口(发送键左边) ----
    def _available_models(self) -> list:
        """当前可选模型列表 [(model_id, label)];内置固定一张,云端用已配服务商/模型。"""
        items = []
        try:
            import launcher_app.ai.model_registry as model_registry
            from launcher_app.ai.local_ai import DEFAULT_MODEL_ID
            ready = model_registry.is_downloaded(DEFAULT_MODEL_ID)
            items.append((f"builtin:{DEFAULT_MODEL_ID}",
                          f"内置本地模型{'' if ready else '（未下载）'}"))
        except Exception:
            pass
        try:
            from launcher_app.ai.model_profiles import api_models
            items.extend(api_models(self.settings))
        except Exception:
            pass
        return items

    def _current_model_id(self) -> str:
        if self._local_enabled():
            try:
                from launcher_app.ai.local_ai import DEFAULT_MODEL_ID
                return f"builtin:{DEFAULT_MODEL_ID}"
            except Exception:
                return "builtin"
        prov = self.settings.get("ai_cloud_provider") or "cloud"
        return f"cloud:{prov}:{self.settings.get('ai_cloud_model') or ''}"

    def _show_model_effort(self):
        btn = self.input.model_btn
        is_builtin = self._local_enabled()
        self.model_effort_popover.set_models(self._available_models(), self._current_model_id())
        self.model_effort_popover.set_effort(
            self.settings.get("ai_reasoning_effort", "medium"), is_builtin=is_builtin)
        self.model_effort_popover.set_strategies(
            [(k, STRATEGY_LABELS.get(k, k)) for k in STRATEGY_CYCLE],
            self._current_strategy())
        anchor = btn.mapToGlobal(btn.rect().bottomLeft())
        self.model_effort_popover.pop_at(anchor)

    def _on_input_effort_changed(self, effort: str):
        from settings import update_settings
        if effort not in {"none", "minimal", "low", "medium", "high", "xhigh"}:
            return
        update_settings(lambda live: live.__setitem__("ai_reasoning_effort", effort))
        self.settings["ai_reasoning_effort"] = effort
        self.main.settings["ai_reasoning_effort"] = effort
        if getattr(self.main, "settings_center", None) is not None:
            self.main.settings_center.settings["ai_reasoning_effort"] = effort

    def _on_input_model_changed(self, model_id: str):
        """切换模型:builtin=内置本地,cloud:<prov>:<model>=云端。写回设置并刷新 UI。"""
        try:
            if model_id.startswith("builtin:"):
                self.settings["ai_source"] = "local"
                self.settings["ai_strategy"] = "local_first"
                self.settings["ai_local_mode"] = "builtin"
                self.settings["ai_provider"] = "local_builtin"
            elif model_id.startswith("cloud:"):
                _, prov, model = model_id.split(":", 2)
                from launcher_app.ai.model_profiles import activate_api
                activate_api(self.settings, prov, model)
            from settings import save_settings
            self.main.settings.update(self.settings)
            center = getattr(self.main, 'settings_center', None)
            if center is not None:
                center.settings.update(self.settings)
                if hasattr(center, 'model_cards'):
                    center.model_cards._settings.update(self.settings)
            save_settings(self.settings)
            self.apply_settings(self.settings)
        except Exception:
            pass

    def _on_preference_selected(self, group: str, value):
        """偏好面板任一项被点选:立即生效并保存到设置(三处同步)。"""
        from settings import update_settings
        if group == "response_style":
            if value not in {"plain", "technical"}:
                return
            key = "ai_response_style"
        elif group == "confirmation_mode":
            if value not in {"per_action", "backup_continue"}:
                return
            key = "ai_confirmation_mode"
        elif group == "permission":
            # 提升到「工作区可写」需二次确认 + 免责声明(与旧开关一致)
            if value == "workspace_write" and \
                    self.settings.get("ai_permission", "launcher_write") != "workspace_write":
                if not self._confirm_workspace_write():
                    self.preferences_popover.set_current(
                        "permission", self.settings.get("ai_permission", "launcher_write"))
                    return
            elif value not in {"readonly", "launcher_write", "workspace_write"}:
                return
            key = "ai_permission"
        else:
            return
        update_settings(lambda live: live.__setitem__(key, value))
        self.settings[key] = value
        self.main.settings[key] = value
        if getattr(self.main, "settings_center", None) is not None:
            self.main.settings_center.settings[key] = value
        if key == "ai_permission":
            self._append_system("文件权限已切换为：" + {
                "readonly": "只读（AI 不能改文件）",
                "launcher_write": "日常可写（AMCL 与 .minecraft）",
                "workspace_write": "工作区可写",
            }[value])

    def _confirm_workspace_write(self) -> bool:
        """给 AI「工作区可写」是提升权限:弹二级确认 + 免责声明,确认后才生效。"""
        from PySide6.QtWidgets import QMessageBox
        plain = self.settings.get("ai_response_style", "plain") == "plain"
        cap = "允许 AI 修改启动器程序？" if plain else "🛡️ 确认给 AI「工作区可写」权限?"
        disc = (("修游戏、装 Mod 和改游戏设置不需要这个权限。\n\n"
                 "开启后，AI 还可以修改启动器功能和插件。只有你打算让 AI 改启动器本身时才建议开启。\n\n"
                 "是否允许？") if plain else
                ("【免责声明】\n一旦开启，AI 就能在启动器程序、设置和游戏目录内创建、修改或删除文件。\n\n"
                 "可能涉及插件、源码和存档；需要稳妥时可切回只读。\n\n确定要开启吗？"))
        ret = QMessageBox.question(self, cap, disc,
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                   QMessageBox.StandardButton.Yes)
        return ret == QMessageBox.StandardButton.Yes

    def _refresh_confirmation_mode(self):
        self._sync_preference_popover()

    # ---- 聊天记录·归档 tab ----
    def _build_archive_tab(self) -> QWidget:
        import launcher_app.ai.chat_archive as ca
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(6)
        tip = QLabel(t('把当前对话存成会话,或从归档快速恢复(恢复后可继续提问,含工具过程)。'))
        tip.setWordWrap(True); tip.setStyleSheet(f"color: {muted_color()}; font-size:11px;")
        lay.addWidget(tip)
        self._archive_list = QListWidget()
        self._archive_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        set_style(self._archive_list, list_style)
        lay.addWidget(self._archive_list, 1)
        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        save_btn = QPushButton(t('💾 存档当前'))
        save_btn.clicked.connect(self._archive_current)
        restore_btn = QPushButton(t('↩ 恢复选中'))
        restore_btn.clicked.connect(self._restore_selected)
        del_btn = QPushButton(t('删 除'))
        del_btn.clicked.connect(self._delete_selected)
        for b in (save_btn, restore_btn, del_btn):
            b.setStyleSheet(f"QPushButton{{background:{current_color('btn_bg')};color:{text_color()};border:1px solid {current_color('btn_border')};"
                            f"border-radius:6px;padding:4px 8px;}} QPushButton:hover{{border-color:{accent_color()};}}")
            btn_row.addWidget(b)
        lay.addLayout(btn_row)
        self._refresh_archive_list()
        return w

    def _on_tab_changed(self, idx: int):
        """切到归档 tab 时刷新列表。"""
        if idx == 1:
            self._refresh_archive_list()

    def _refresh_archive_list(self):
        import launcher_app.ai.chat_archive as ca
        self._archive_list.clear()
        for s in ca.list_sessions():
            item = QListWidgetItem(f"{s['title']}\n{s['created_at']}  ·  {s['count']} 条")
            item.setData(Qt.ItemDataRole.UserRole, s["path"])
            self._archive_list.addItem(item)

    def _archive_current(self):
        """把当前对话存成一份会话。"""
        self.save_current_session(show_feedback=True)

    def save_current_session(self, *, show_feedback=False):
        """Save the live conversation with its selected instance for focus mode."""
        import launcher_app.ai.chat_archive as ca
        if not any(entry.kind in ('user', 'amcl') for entry in self._entries):
            if show_feedback:
                QMessageBox.information(self, t('存档'), t('当前没有会话内容可存档。'))
            return False
        r = ca.save_session(self._chat_messages, self._entries,
                            instance_id=self._session_instance_id)
        if r.get("ok"):
            self._session_dirty = False
            self._refresh_archive_list()
            self.archive_changed.emit()
            if show_feedback:
                QMessageBox.information(self, t('存档'), t('✅ 已存档:「{v0}」').format(v0=(r['title'])))
            return True
        else:
            QMessageBox.warning(self, t('存档'), t('❌ 存档失败:{v0}').format(v0=(r.get('error'))))
            return False

    def new_session(self):
        """Keep the previous exchange in the archive before clearing the chat."""
        if getattr(self, '_agent_running', False):
            QMessageBox.information(self, t('新会话'), t('请先等待当前 AI 任务结束。'))
            return False
        if self._session_dirty and any(entry.kind in ('user', 'amcl') for entry in self._entries):
            if not self.save_current_session():
                return False
        self._chat_messages.clear()
        self._entries.clear()
        self._session_instance_id = ''
        self._session_dirty = False
        self._focus_show_history = False
        self._tool_expand_levels.clear()
        self._expanded_ai.clear()
        self.input.clear()
        self._render_all()
        self.tabs.setCurrentIndex(0)
        self.input.setFocus()
        self.conversation_changed.emit()
        return True

    def _restore_selected(self):
        """从归档恢复选中会话(替换当前对话历史,可继续提问)。"""
        import launcher_app.ai.chat_archive as ca
        cur = self._archive_list.currentItem()
        if cur is None:
            return
        path = cur.data(Qt.ItemDataRole.UserRole)
        self.load_session_path(path)

    def load_session_path(self, path):
        if getattr(self, '_agent_running', False):
            QMessageBox.information(self, t('切换会话'), t('请先等待当前 AI 任务结束。'))
            return False
        if self._session_dirty and any(entry.kind in ('user', 'amcl') for entry in self._entries):
            if not self.save_current_session():
                return False
        import launcher_app.ai.chat_archive as ca
        s = ca.load_session(path)
        if not s.get("ok"):
            QMessageBox.warning(self, t('恢复'), t('❌ 读取失败:{v0}').format(v0=(s.get('error'))))
            return False
        instance_id = s.get('instance_id') or ''
        source = self.main.instance_list
        if instance_id:
            match = next((source.item(index) for index in range(source.count())
                          if (source.item(index).data(Qt.ItemDataRole.UserRole) or {}).get('id')
                          == instance_id), None)
            if match is not None:
                source.setCurrentItem(match)
            else:
                source.setCurrentRow(-1)
        else:
            source.setCurrentRow(-1)
        self._chat_messages = list(s.get("chat_messages", []))
        self._entries = coerce_entries(s.get("entries", []))
        self._session_instance_id = instance_id
        self._session_dirty = False
        self._render_all()
        self.tabs.setCurrentIndex(0)          # 切回聊天 tab
        self.input.setFocus()
        self._append_system(f"已从归档恢复「{s.get('title','')}」,可继续提问。")
        self.conversation_changed.emit()
        return True

    def _delete_selected(self):
        import launcher_app.ai.chat_archive as ca
        cur = self._archive_list.currentItem()
        if cur is None:
            return
        path = cur.data(Qt.ItemDataRole.UserRole)
        if ca.delete_session(path):
            QMessageBox.information(self, t('删除'), t('已删除该归档会话。'))
            self._refresh_archive_list()
            self.archive_changed.emit()

    # ---- 消息显示(条目化,渲染委托给 chat_view) ----
    def _append_system(self, text: str):
        if getattr(self, '_focus_mode', False):
            self._focus_show_history = True
        self._entries.append(ChatEntry(kind="system", text=text))
        self._render_all()

    def _append_user(self, text: str, *, kind='user'):
        if not any(entry.kind in ('user', 'amcl') for entry in self._entries):
            current = self.main.instance_list.currentItem()
            inst = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
            self._session_instance_id = (inst or {}).get('id', '')
        self._entries.append(ChatEntry(kind=kind, text=text))
        self._session_dirty = True
        self._render_all()
        self.conversation_changed.emit()

    def _append_ai(self, text: str):
        self._entries.append(ChatEntry(kind="ai", text=text))
        self._session_dirty = True
        self._render_all()

    def append_table(self, title: str, columns: list, rows: list):
        """追加一张结构化表格到对话流(工具返回结构化数据时的展示落点)。"""
        self._entries.append(ChatEntry(kind="table", title=title,
                                       columns=list(columns or []),
                                       rows=[list(r) for r in (rows or [])]))
        self._render_all()

    def _ai_summary(self, text: str, width: int = 90) -> str:
        """长 AI 回答的折叠摘要(实现见 chat_view,保留此名以兼容既有调用)。"""
        from launcher_app.ai.chat_view import ai_summary
        return ai_summary(text, width)

    def _is_long_ai(self, text: str) -> bool:
        """答案是否值得折叠(实现见 chat_view,保留此名以兼容既有调用)。"""
        from launcher_app.ai.chat_view import is_long_ai
        return is_long_ai(text)

    def _render_all(self):
        """把展示流交给渲染层重绘(条目/展开状态由本类提供,渲染逻辑在 chat_view)。
        t13 防御:仅主线程调用(worker 走 system_msg/reply/tool_called 等队列信号);
        控件销毁中(关闭窗口竞态)的迟到调用由 ChatView 内部忽略。"""
        self.history.set_entries(
            self._entries,
            tool_level=self._tool_expand_levels.get,
            expanded_ai=self._expanded_ai)
        self._update_focus_empty_state()
        self._update_ctx_ring()

    def _update_ctx_ring(self):
        """按真实对话历史估算已用上下文 tokens,更新发送按钮外圈的占用环(绿→黄→红)。
        t13 防御:仅主线程调用(worker 走 ring_update 信号);部件销毁中(关闭窗口)迟到调用直接忽略。"""
        try:
            inp = getattr(self, "input", None)
            if inp is None or getattr(inp, "send_btn", None) is None:
                return
            used = sum(self._est_message(m) for m in self._chat_messages)
            limit = int(self.settings.get("context_window", 65536) or 65536)
            inp.send_btn.set_usage(used, limit)
        except RuntimeError:
            pass   # C++ 对象已销毁(窗口关闭竞态)→ 忽略
        except Exception:
            pass

    def _show_tool(self, name: str, args: dict, result: str):
        """把一次工具调用记入历史。结果太长默认折叠,点 [展开] 看全文。"""
        self._tool_id += 1
        self._entries.append(ChatEntry(kind="tool", tool_id=self._tool_id,
                                       name=name, args=args or {}, result=result))
        self._render_all()

    # ---- 图片输入 ----
    def _pick_images(self):
        """📷 按钮:打开文件选择框,可多选图片"""
        if not self._vision_on():
            return   # 模型不支持多模态:按钮已隐藏,这里只是兜底
        paths_, _f = QFileDialog.getOpenFileNames(
            self, t('添加图片'), "",
            t('图片 (*.png *.jpg *.jpeg *.webp *.gif *.bmp);;所有文件 (*)'))
        for p in paths_:
            self._add_image_path(p)

    def _pick_recent_screenshots(self):
        """🖼 最近照片:列出 .minecraft 里的游戏截图,选中的添加进输入"""
        if not self._vision_on():
            return   # 模型不支持多模态:按钮已隐藏,这里只是兜底
        import paths as _paths
        dlg = RecentScreenshotsDialog(_paths.GAME_DIR, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            for p in dlg.picked:
                self._add_image_path(p)

    def _add_image_data(self, img: QImage):
        """从剪贴板粘贴的图片:存成临时 png 再走统一添加流程"""
        if img.isNull():
            return
        fd, tmp = tempfile.mkstemp(suffix=".png", prefix="aml_img_")
        os.close(fd)
        if img.save(tmp, "PNG"):
            self._add_image_path(tmp)

    def _add_image_path(self, path: str):
        if not self._vision_on():
            self._append_system("⚠️ 当前模型不支持图片输入(设置 → AI 助手 → 多模态 可开启)")
            return
        if not path or not os.path.isfile(path):
            return
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        if size > 8 * 1024 * 1024:
            self._append_system(f"⚠️ 图片超过 8MB,未添加:{os.path.basename(path)}")
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
            self._append_system(f"⚠️ 不支持的图片格式:{ext or '(无扩展名)'},支持 png/jpg/webp/gif/bmp")
            return
        self.pending_images.append({"path": path})
        self._rebuild_thumb_row()
        self._append_system(f"📷 已添加图片:{os.path.basename(path)}(发送时随问题一起发给 AI)")

    def _rebuild_thumb_row(self):
        """重建缩略图列表(每张图 42px 缩略图 + 右上角 × 删除)"""
        for w in self._thumb_widgets:
            w.deleteLater()
        self._thumb_widgets = []
        for i, item in enumerate(self.pending_images):
            wrap = QWidget()
            hl = QHBoxLayout(wrap)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(2)
            thumb = QLabel()
            pix = QPixmap(item["path"])
            thumb.setPixmap(pix.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))
            thumb.setFixedSize(42, 42)
            thumb.setStyleSheet(f"border:1px solid {current_color('btn_border')}; border-radius:3px;")
            thumb.setToolTip(os.path.basename(item["path"]))
            x = QPushButton("×")
            x.setFixedSize(16, 16)
            x.setStyleSheet(f"QPushButton{{background:{danger_color()};color:white;border:none;"
                            f"border-radius:8px;font-size:10px;font-weight:bold;}}")
            x.setToolTip(t('移除这张图片'))
            x.clicked.connect(lambda _c, idx=i: self._remove_image(idx))
            hl.addWidget(thumb)
            hl.addWidget(x)
            self.thumb_row.addWidget(wrap)
            self._thumb_widgets.append(wrap)

    def _remove_image(self, idx: int):
        if 0 <= idx < len(self.pending_images):
            self.pending_images.pop(idx)
            self._rebuild_thumb_row()

    def _on_anchor(self, url: QUrl):
        """点击对话流里的链接:tool:N 展开/收起工具结果;ai:idx 展开/收起长回答;http(s) 用系统浏览器打开"""
        href = url.toString()
        if href.startswith("tool:"):
            try:
                tid = int(href.split(":", 1)[1])
            except ValueError:
                return
            level = self._tool_expand_levels.get(tid, 0)
            self._tool_expand_levels[tid] = 0 if level >= 2 else level + 1
            self._render_all()
        elif href.startswith("ai:"):
            try:
                idx = int(href.split(":", 1)[1])
            except ValueError:
                return
            if idx in self._expanded_ai:
                self._expanded_ai.discard(idx)
            else:
                self._expanded_ai.add(idx)
            self._render_all()
        elif href.startswith(("http://", "https://")):
            QDesktopServices.openUrl(url)

    # ---- 本地推理(§8.1 拍板 xLAM 模型,grammar 约束) ----
    def _local_backend(self) -> str:
        """本地后端类型:builtin(内置)/ ollama / lmstudio。"""
        return (self.settings.get("ai_local_mode", "builtin") or "builtin").strip()

    def _local_enabled(self) -> bool:
        """是否进入『本地路由』:策略用本地(local_first 或 hybrid)且本地后端是内置。
        云端优先(cloud_first)或本地后端是 ollama/lmstudio 时,不走本地 grammar 引擎
        ——ollama/lmstudio 走 OpenAI 兼容路径(chat_with_tools),由云端分支承担。
        (t14 修复:不再看可能过期的 ai_provider,避免『选了本地模型却仍走云端 401』。)"""
        if self._current_strategy() == "cloud_first":
            return False
        return self._local_backend() == "builtin"

    def _cloud_available(self) -> bool:
        """云端/兼容通道是否可用:是否配了可用的接口地址(http 开头),公网云还要求有密钥。
        (t14 修复:
          1) 不再被『当前是内置本地模型』一刀切挡住——本地优先/混合策略下复杂任务要能落到云端;
          2) 公网云(如 DeepSeek)没填密钥 → 视为不可用,给友好提示,而不是让用户撞 401。)"""
        base = (self.settings.get("ai_cloud_base_url")
                or self.settings.get("ai_base_url") or "").strip()
        if not base.startswith(("http://", "https://")):
            return False
        # 本地 OpenAI 兼容服务(127.0.0.1/localhost)无需密钥;公网云端需要密钥,否则发出去就是 401
        h = base.split("://", 1)[-1].split("/", 1)[0].lower()
        # 取主机名(去端口,IPv6 去方括号): localhost:11434 -> localhost ; [::1]:1234 -> ::1
        if h.startswith("["):
            host = h.split("]")[0][1:] if "]" in h else h
        else:
            host = h.split(":")[0]
        if host in ("localhost", "127.0.0.1", "::1") or host.startswith("127.0.0.1"):
            return True
        key = (self.settings.get("ai_cloud_api_key")
               or self.settings.get("ai_api_key") or "").strip()
        return bool(key)

    def _cloud_settings(self) -> dict:
        """云端/兼容通道实际用的那组设置:本地模式下落到云端时用 ai_cloud_*(避免用空 base_url),
        否则用当前生效的 ai_base_url 等(ollama/lmstudio 等本地兼容服务)。"""
        s = self.settings
        if (s.get("ai_cloud_base_url") or "").strip():
            return {**s,
                    "ai_provider": s.get("ai_cloud_provider", "deepseek"),
                    "ai_base_url": s.get("ai_cloud_base_url") or "",
                    "ai_api_key": s.get("ai_cloud_api_key") or "",
                    "ai_model": s.get("ai_cloud_model") or ""}
        return s

    def _cloud_unavailable_hint(self) -> str:
        """§1.3 业务语言:本地模型下没有云端通道时的友好提示(不是技术报错)。"""
        return ("这个任务超出了本地模型的基础能力(比如深度诊断/复杂分析),需要联网的云端模型。"
                "你可以:① 换一种本地模型能处理的说法(装 Mod/查配方/改设置等);"
                "② 在设置 → AI 助手里切换到云端服务(如 DeepSeek),输入密钥即可。")

    def _get_local_engine(self):
        """懒加载本地推理引擎单例(首次用到才起;窗口关闭/游戏启动时 stop)"""
        if self._local_engine is None:
            from launcher_app.ai.local_ai import GrammarToolEngine
            self._local_engine = GrammarToolEngine(model_id=LOCAL_MODEL_ID)
        return self._local_engine

    def _local_model_ready(self) -> bool:
        """模型文件是否已下载且校验通过(§2 懒加载:没下就提示+走云端)"""
        try:
            import launcher_app.ai.model_registry as model_registry
            return model_registry.is_downloaded(LOCAL_MODEL_ID)
        except Exception:
            return False

    def _local_tool_call(self, text: str, executor, on_tool):
        """本地路径:grammar 工具调用 → 复用 executor 执行。
        返回 (reply 文本, 是否成功);失败时上层落云端(§1.4)。"""
        # 主动避让(§5):游戏运行中且「游戏内 AI」不用本地模型 → 暂停本地推理(资源让给游戏)
        blocked = self._local_infer_blocked()
        if blocked:
            return (blocked, True)   # 视为已处理,直接展示提示,不再落云端
        self.signals.local_status.emit("本地模型:推理中…")
        self._start_infer_monitor()
        self._warn_if_hot()          # 温控意识(§5):过热则劝退重任务
        try:
            engine = self._get_local_engine()
            engine.start()   # 幂等:已启动则直接返回
            # 注入真实启动器上下文(§7.3 最轻量 RAG):实例清单 + 设置,避免模型乱编实例 id
            try:
                from launcher_app.ai.local_ai import build_launcher_context
                context = build_launcher_context()
            except Exception:
                context = ""
            from launcher_app.ai.local_ai import two_stage_tool_call, reasoning_effort_from_settings
            call = two_stage_tool_call(text, context=context, engine=engine,
                                       effort=reasoning_effort_from_settings())
            name = call.get("name", "")
            args = call.get("arguments", {})
            if not name:
                return ("(本地模型未给出明确动作)", False)
            result = executor(name, args)
            text_result = str(result)
            if on_tool:
                on_tool(name, args, text_result)   # 工具卡片显示真实结果
            # 转人话:按混合路由把工具结果总结成正式回答,不再裸奔原始结果
            reply = _synthesize_tool_reply(
                text, name, text_result, self.settings,
                context=context, executor=executor, engine=engine)
            return (reply, True)
        except PermissionDenied:
            return ("权限拒绝:当前是只读权限,不能修改文件(可在 AI 设置中改为\"工作区可写\")", True)
        except Exception as e:
            return (f"(本地推理失败:{type(e).__name__}: {e})", False)
        finally:
            self._stop_infer_monitor()
            self.signals.local_idle.emit()   # 用完即卸:主线程安排闲置卸载
            self.signals.local_status.emit(self._local_status_text())

    def _local_chat(self, text: str):
        """本地简单对话(寒暄/基础介绍/功能简介):引擎 chat() 自由回答,不走工具。
        返回 (reply 文本, 是否成功);失败时上层落云端(§1.4)。"""
        blocked = self._local_infer_blocked()
        if blocked:
            return (blocked, True)   # 主动避让:游戏运行中且非本地通道 → 提示,不落云端
        self.signals.local_status.emit("本地模型:推理中…")
        self._start_infer_monitor()
        self._warn_if_hot()          # 温控意识(§5)
        try:
            engine = self._get_local_engine()
            engine.start()
            try:
                from launcher_app.ai.local_ai import build_launcher_context
                context = build_launcher_context()
            except Exception:
                context = ""
            reply = engine.chat(text, context=context)
            if not reply.strip():
                return ("(本地模型没有回答)", False)
            return (reply, True)
        except Exception as e:
            return (f"(本地对话失败:{type(e).__name__}: {e})", False)
        finally:
            self._stop_infer_monitor()
            self.signals.local_idle.emit()   # 用完即卸
            self.signals.local_status.emit(self._local_status_text())

    # ---- 本地模型下载(懒加载 §2):首次用到且未下载 → 后台下载带进度,期间走云端 ----
    def _on_dl_progress(self, title: str, status: str, done: int, total: int):
        """主线程:AI 发起的下载进度 → 写主窗口下载日志 + 更新左下角圆环(详情可点开看)。"""
        try:
            if getattr(self, "main", None) is not None and hasattr(self.main, "report_download_progress"):
                self.main.report_download_progress(title, status, done, total)
        except Exception:
            pass

    def _on_dl_done(self, title: str, ok: bool, msg: str):
        """主线程:AI 发起的下载结束 → 写主窗口下载日志 + 满环收起。"""
        try:
            if getattr(self, "main", None) is not None and hasattr(self.main, "report_download_done"):
                self.main.report_download_done(title, ok, msg)
        except Exception:
            pass

    def _download_progress_cb(self, title: str):
        """给 build_executor 的进度回调(在 worker 线程调用):包装成跨线程信号,回主线程更新。"""
        def cb(done, total):
            self.signals.dl_progress.emit(title, "", done, total)
        return cb

    def _start_local_download(self):
        """主线程:创建下载进度弹窗,后台线程下载模型(镜像优先),完成后关闭弹窗。"""
        if self._local_downloading:
            return
        if not bool(self.settings.get("ai_local_auto_download", True)):
            return
        self._local_downloading = True
        self._on_local_status("本地模型:下载中 0%…")
        dlg = QProgressDialog("正在下载本地模型(约500MB,镜像优先)…", None, 0, 0, self)
        dlg.setWindowTitle(t('下载本地模型'))
        dlg.setWindowModality(Qt.WindowModality.NonModal)
        dlg.setMinimumDuration(0)
        dlg.setCancelButton(None)
        dlg.setAutoClose(False)
        dlg.show()
        self._local_dlg = dlg

        def dl():
            try:
                import launcher_app.ai.model_registry as model_registry
                model_registry.download(
                    LOCAL_MODEL_ID,
                    progress_callback=lambda d, t: self.signals.local_dl_progress.emit(d, t))
                self.signals.local_dl_done.emit("✅ 本地模型下载完成,之后可用内置本地模型。")
            except Exception as e:
                self.signals.local_dl_done.emit(
                    f"❌ 本地模型下载失败:{type(e).__name__}: {str(e)[:200]}(可稍后重新触发)")

        threading.Thread(target=dl, daemon=True).start()

    def _on_local_dl_progress(self, done, total):
        """主线程:更新下载进度弹窗 + 状态栏文字(跨线程信号已搬回主线程)。"""
        if self._local_dlg is not None:
            self._local_dlg.setMaximum(max(total, 1))
            self._local_dlg.setValue(done)
            if total:
                self._local_dlg.setLabelText(
                    f"下载本地模型…  {done/1024/1024:.0f} / {total/1024/1024:.0f} MB")
        # 同步到主窗口下载日志 + 左下角圆环(点圆环 → 下载详情可见)
        self._on_dl_progress("本地模型", "", done, total)
        if self._local_enabled():
            self._on_local_status(
                f"本地模型:下载中 {done/1024/1024:.0f}MB…" if total
                else "本地模型:下载中…")

    def _on_local_dl_done(self, msg):
        """主线程:下载结束,关弹窗 + 提示 + 刷新状态。"""
        self._local_downloading = False
        if self._local_dlg is not None:
            self._local_dlg.close()
            self._local_dlg = None
        self._on_dl_done("本地模型", ("完成" in msg), msg)
        self._append_system(msg)
        self.update_local_status()
        if "完成" in msg:
            settings_center = getattr(getattr(self, "main", None), "settings_center", None)
            if settings_center is not None and hasattr(settings_center, "refresh_ai_config_visibility"):
                settings_center.refresh_ai_config_visibility()

    # ---- 本地模型状态显示(未下载/下载中/预加载/已就绪/推理中) ----
    def _local_status_text(self) -> str:
        """本地模型当前状态文字(只读,不碰 UI,可在任意线程算)。"""
        try:
            import launcher_app.ai.model_registry as model_registry
            ready = model_registry.is_downloaded(LOCAL_MODEL_ID)
        except Exception:
            ready = False
        if getattr(self, "_local_preloading", False):
            return "本地模型:预热中…"
        if self._local_downloading:
            return "本地模型:下载中…"
        if ready:
            return "本地模型:已就绪"
        return "本地模型:未下载\n(在设置 → AI 助手里点「下载模型」)"

    def _on_local_status(self, text: str):
        """主线程:更新顶部本地模型状态标签。"""
        if not hasattr(self, "local_status_label"):
            return
        if not self._local_enabled():
            self.local_status_label.setVisible(False)
            return
        self.local_status_label.setVisible(True)
        self.local_status_label.setText(text)
        if "中" in text:          # 预热中/下载中/推理中 → 进行中
            color = warning_color()      # 进行中:橙
        elif "已就绪" in text:
            color = success_color()      # 就绪:绿
        else:
            color = muted_color()
        self.local_status_label.setStyleSheet(f"color: {color}; background: transparent;")

    def update_local_status(self):
        """按当前 provider/下载状态刷新本地模型状态标签(主线程)。"""
        if self._local_enabled():
            self._on_local_status(self._local_status_text())
        elif hasattr(self, "local_status_label"):
            self.local_status_label.setVisible(False)

    # ---- 冷启动预加载(§8.2):本地 provider 且模型已下载时,后台预热 llama-server ----
    def maybe_preload_local(self):
        """空闲时预热本地模型,让首次本地提问不再等 server 冷启动。

        仅当:选的是内置本地模型、模型已下载、且当前未在预热/未在运行时才触发。
        游戏启动时会按 ai_in_game 决定是否 stop(见 launch_selected),两者不冲突:
        预热只在这不干扰游戏内存时进行。t13 防御:整体兜底,定时器回调异常不冒泡。"""
        try:
            if not self._local_enabled():
                return
            try:
                import launcher_app.ai.model_registry as model_registry
                if not model_registry.is_downloaded(LOCAL_MODEL_ID):
                    return
            except Exception:
                return
            # 主动避让(§5):游戏运行中且「游戏内 AI」非本地 → 不预热(避免跟 off/cloud 的卸载打架,抢内存)
            if self._game_running and self._game_ai_mode() != "local":
                return
            if getattr(self, "_local_preloading", False):
                return
            eng = getattr(self, "_local_engine", None)
            if eng is not None and getattr(eng, "proc", None) and eng.proc.poll() is None:
                return   # 已在运行
            self._local_preloading = True
            self._on_local_status("本地模型:预热中…")

            def warm():
                try:
                    engine = self._get_local_engine()
                    engine.start()   # 阻塞直至 /health 就绪(后台线程,不卡 UI)
                except Exception:
                    pass
                finally:
                    self._local_preloading = False
                    self.signals.local_status.emit(self._local_status_text())

            threading.Thread(target=warm, daemon=True).start()
        except Exception:
            pass   # 预热失败不影响主流程(懒加载兜底)

    # ---- 本地引擎生命周期:游戏启动/窗口关闭时卸载(省内存/无残留进程) ----
    def stop_local_engine(self):
        """卸载本地模型引擎(llama-server 进程)。off/cloud 时游戏启动会调用;窗口关闭也会调用。"""
        self._cpu_sample = {}   # 量化提示:引擎重启后重新采样
        eng = getattr(self, "_local_engine", None)
        if eng is not None:
            try:
                eng.stop()
            except Exception:
                pass
            self._local_engine = None     # 下次要用会重新懒加载

    def shutdown(self):
        """窗口关闭时调用:卸载本地模型,确保无残留进程。"""
        if getattr(self, '_agent_cancel', None) is not None:
            self._agent_cancel.set()
        self._infer_monitor_stop.set()   # 停 CPU 采样监控线程(§5)
        self.stop_local_engine()

    # ---- 性能策略(§5):量化提示 / 主动避让 / 用完即卸 / 温控意识 ----
    def _game_ai_mode(self) -> str:
        """游戏内 AI 通道:off / cloud / local(见 settings.ai_in_game)。"""
        return str(self.settings.get("ai_in_game", "off") or "off")

    def set_game_running(self, proc):
        """主动避让(§5):游戏进程启动 → 标记运行中,并把本地推理优先级降到游戏之下。"""
        self._game_running = True
        self._game_proc = proc
        self._apply_engine_priority()
        # 内存监控(§5.1 local 通道):游戏+本地模型共存,可用内存不足先提示用户(不崩游戏)
        if self._game_ai_mode() == "local":
            self._warn_if_mem_low()

    def _warn_if_mem_low(self):
        """§5.1 local 通道内存监控:可用内存低于阈值 → 提醒用户(游戏+本地模型共存可能吃紧)。"""
        try:
            free = _system_available_memory_mb()
            if free is None or free >= _MEM_LOW_MB:
                return
            self.signals.system_msg.emit(
                f"⚠️ 当前可用内存仅剩约 {free:.0f}MB,游戏内又常驻本地模型,可能影响流畅度。"
                "建议到 设置→AI 助手 把「游戏内 AI」改为关闭/云端,或加内存。")
        except Exception:
            pass

    def set_game_stopped(self):
        """主动避让(§5):游戏退出 → 恢复本地推理正常优先级,并按冷启动策略预热下次要用。"""
        self._game_running = False
        self._game_proc = None
        self._apply_engine_priority()
        # 游戏退出后,若选的是内置本地模型且已下载 → 后台预热(下次本地提问秒开;§8.2)
        try:
            if self._game_ai_mode() != "local":
                QTimer.singleShot(1500, self.maybe_preload_local)
        except Exception:
            pass

    def _apply_engine_priority(self):
        """把 llama-server 优先级调到与游戏运行状态匹配(游戏进程优先级始终高于推理)。"""
        eng = getattr(self, "_local_engine", None)
        proc = getattr(eng, "proc", None) if eng else None
        if proc is None or proc.poll() is not None:
            return
        pid = getattr(proc, "pid", None)
        if not pid:
            return
        cls = _PRIORITY_BELOW_NORMAL if self._game_running else _PRIORITY_NORMAL
        _set_process_priority_class(pid, cls)

    def _local_infer_blocked(self) -> str | None:
        """主动避让(§5):游戏运行中且「游戏内 AI」不用本地模型 → 暂停本地推理(资源让给游戏)。
        返回阻止文案;不阻止则返回 None。"""
        if not self._game_running:
            return None
        if self._game_ai_mode() == "local":
            return None   # 游戏内 AI 用本地模型 → 保持加载,仅优先级避让(_apply_engine_priority)
        return ("游戏运行中,已暂停本地推理(把资源让给游戏)。"
                "你可以稍后再试,或到 设置→AI 助手 把「游戏内 AI」设为本地模型后,"
                "游戏期间也能用本地模型。")

    # ---- 量化提示(§5):推理时显示 CPU 占用(约) ----
    def _start_infer_monitor(self):
        self._inferring = True

    def _stop_infer_monitor(self):
        self._inferring = False

    def _infer_monitor_loop(self):
        """后台守护线程:推理期间每秒采样一次 llama-server CPU%,经信号回主线程显示。
        不触碰任何 Qt 部件(t13 规则),只读状态 + 发信号;daemon,不阻塞退出。"""
        while not self._infer_monitor_stop.is_set():
            time.sleep(1.0)
            if not self._inferring:
                continue
            eng = getattr(self, "_local_engine", None)
            proc = getattr(eng, "proc", None) if eng else None
            if proc is None or proc.poll() is not None:
                continue
            pct = _process_cpu_percent(getattr(proc, "pid", 0) or 0, self._cpu_sample)
            if pct is not None:
                self.signals.local_status.emit(f"本地模型:推理中… CPU≈{pct:.0f}%")

    def _warn_if_hot(self):
        """温控意识(§5):推理前查一次 CPU 温度,过高则劝退重任务(每 5 分钟最多提醒一次)。"""
        try:
            now = time.time()
            if now - self._hot_warned_at < 300:
                return
            temp = _cpu_temperature()
            if temp is None:
                return
            if temp >= _CPU_HOT_C:
                self._hot_warned_at = now
                self.signals.system_msg.emit(
                    f"⚠️ 检测到 CPU 温度较高(约 {temp:.0f}℃),本地推理可能让笔记本过热降频。"
                    "这个任务建议改用云端(更稳),或等降温后再试。")
        except Exception:
            pass

    # ---- 用完即卸(§5):任务结束后闲置卸载模型,回到几百 KB 空闲态 ----
    def _schedule_idle_unload(self):
        """吃完即卸:本地推理结束后安排闲置卸载(主线程);ai_in_game=local 则常驻不卸。"""
        if self._game_ai_mode() == "local":
            return   # 游戏内 AI 用本地模型 → 常驻(游戏内要用),不卸
        if self._idle_timer is None:
            self._idle_timer = QTimer(self)
            self._idle_timer.setSingleShot(True)
            self._idle_timer.timeout.connect(self._idle_unload_now)
        self._idle_timer.start(60_000)   # 闲置 60 秒后卸载

    def _idle_unload_now(self):
        """闲置卸载执行:没在推理且引擎还在跑 → 停掉,回到空闲态(§5 用完即卸)。"""
        if self._inferring:
            return
        if self._game_ai_mode() == "local":
            return
        if getattr(self, "_local_engine", None) is None:
            return
        self.stop_local_engine()

    # ---- 发送(后台线程,带工具调用,过程实时显示) ----
    def ask(self, text: str):
        """Application-originated task, shown as AMCL without consuming drafts."""
        self.send(amcl_text=text)

    def send(self, *, amcl_text=None):
        is_amcl = amcl_text is not None
        if getattr(self, '_agent_running', False):
            self._append_system('任务仍在执行，请先停止，等待结束后再发送。')
            return
        # 未选择模型 → 提示去设置里选,不发(按钮虽已隐藏,这里兜底)
        if not ((self.settings.get("ai_model") or "").strip()
                or (self.settings.get("ai_local_model") or "").strip()):
            self._append_system("尚未选择 AI 模型,请先在 设置 → AI 助手 里选择一个模型。")
            return
        text = str(amcl_text).strip() if is_amcl else self.input.text().strip()
        images = [] if is_amcl else list(self.pending_images)
        if images and not self._vision_on():
            # 模型不支持多模态的兜底:忽略待发图片
            self._append_system("⚠️ 当前模型不支持图片输入,已忽略待发送的图片。")
            images = []
            self.pending_images = []
            self._rebuild_thumb_row()
        if not text and not images:
            return
        if not self._confirm_if_heavy(text):
            return   # 用户取消:保留输入,不发送
        if not is_amcl:
            self.input.clear()
        if not is_amcl and text.startswith("/"):
            # 以 / 开头的输入 = 直接给运行中的游戏发指令(如 /summon zombie),不走 AI
            from launcher_app.instances.game_command import send_command
            result = send_command(text, self.main)
            self._append_system(f"🎮 {result}")
            return
        self._append_user(text + (f"  [📷×{len(images)}]" if images else ""),
                          kind='amcl' if is_amcl else 'user')
        pin_context = '' if self._focus_mode or is_amcl else self.context_pins.message()
        if pin_context:
            self._append_system("📍 本条消息附带固定对象快照：" +
                                ", ".join(d.get("name", "参考对象") for d, _ in self.context_pins.records))
            text += pin_context
        self._append_system("⏳ 正在请求 AI...")
        # 无图片时 content 保持纯字符串(省 token、兼容老接口);有图片才用多模态 list
        # (OpenAI 兼容 data URL 格式;模型不支持视觉会报错提示)
        content = text
        if images:
            content = []
            if text:
                content.append({"type": "text", "text": text})
            for item in images:
                try:
                    with open(item["path"], "rb") as f:
                        b64 = base64.b64encode(f.read()).decode()
                except OSError as e:
                    self._append_system(f"⚠️ 读取图片失败:{os.path.basename(item['path'])} ({e})")
                    continue
                mime = mimetypes.guess_type(item["path"])[0] or "image/png"
                content.append({"type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{b64}"}})
        if not is_amcl:
            self.pending_images = []
            self._rebuild_thumb_row()
        # 真正的多轮记忆:历史消息(含工具调用)保存在 _chat_messages,
        # 每次发送 = 最新 system + 历史 + 当前问题
        message = {"role": "user", "content": content}
        if is_amcl:
            # An application task is not a new high-priority system instruction.
            message['name'] = 'AMCL'
        self._chat_messages.append(message)
        self._trim_history()
        messages = [
            {"role": "system", "content": self.main.ai_context()},
        ] + list(self._chat_messages)
        s = self.settings
        # AI 发起的下载(装 Mod/创建实例等)进度 → 左下角圆环 + 下载详情
        executor = build_executor(s, progress_cb=self._download_progress_cb("Mod / 实例"),
                                  confirm_action=self._confirm_ai_action,
                                  notice_cb=self._notify_ai_autonomy)
        tools_called = []
        is_local = self._local_enabled()

        def on_tool(name, args, result):
            tools_called.append(name)
            self.signals.tool_called.emit(name, args, result)   # 跨线程安全:信号回主线程渲染

        def worker():
            # t13 修复:worker 线程【禁止】直接调用任何 Qt 部件方法(_append_system/_update_ctx_ring
            # 等),跨线程碰 UI 是未定义行为,实测可原生崩溃(0xC0000005/0x8 空指针)。
            # 全部改走队列信号:signals.system_msg / signals.ring_update → 主线程槽执行。
            try:
                # 路由分流(§1):本地 provider 时先判规则/难度/歧义;ai_strategy 三档 + 追问降级
                if is_local and not images:
                    from launcher_app.ai.task_router import route, match_rule
                    strategy = str(self.settings.get("ai_strategy", "local_first") or "local_first")
                    # 追问降级:上一轮是规则/chat 作答 → 本轮 follow_up=True,强制转模型
                    follow_up = is_amcl or bool(getattr(self, "_cheap_replied", False)) or bool(pin_context)
                    setattr(self, "_cheap_replied", False)
                    # cloud_first 时把云端可用性告诉 route:未配云端 → 规则/本地兜底(降级链不报错)
                    have_cloud = (self._cloud_available() if strategy == "cloud_first" else True)
                    decision = route(text, strategy=strategy, have_cloud=have_cloud,
                                     follow_up=follow_up)
                    if decision["target"] == "rule":
                        reply = match_rule(text) or "(没想好怎么答,稍后再试试)"
                        self.signals.reply.emit(reply)
                        self.signals.ring_update.emit()
                        setattr(self, "_cheap_replied", True)   # 规则答过 → 下轮追问强制转模型
                        return
                    if decision["target"] == "chat":
                        # 简单对话/寒暄/基础介绍:本地自由回答(不需要工具)
                        if self._local_model_ready():
                            reply, ok = self._local_chat(text)
                            if ok:
                                self.signals.reply.emit(reply)
                                self.signals.ring_update.emit()
                                setattr(self, "_cheap_replied", True)   # chat 答过 → 下轮追问转模型
                                return
                            # 本地 chat 失败 → 有云端则落云端,否则友好提示
                            if self._cloud_available():
                                self.signals.system_msg.emit("本地对话未成功,已转云端处理…")
                            else:
                                self.signals.reply.emit(self._cloud_unavailable_hint())
                                self.signals.ring_update.emit()
                                return
                        else:
                            self.signals.system_msg.emit("本地模型未下载,先走云端…")
                            self.signals.local_dl_start.emit()
                            if not self._cloud_available():
                                self.signals.reply.emit(
                                    "本地模型还没下载,而且当前没有可用的云端服务。"
                                    "模型正在后台下载,下载完成后就能离线用了。")
                                self.signals.ring_update.emit()
                                return
                    if decision["target"] == "local":
                        if self._local_model_ready():
                            reply, ok = self._local_tool_call(text, executor, on_tool)
                            if ok:
                                if not tools_called:
                                    self.signals.no_tool.emit()
                                self.signals.reply.emit(reply)
                                self.signals.ring_update.emit()
                                return
                            # 本地失败 → 有云端则落云端,否则友好提示(§1.3/§1.4)
                            if self._cloud_available():
                                self.signals.system_msg.emit("本地推理未成功,已转云端处理…")
                            else:
                                self.signals.reply.emit(self._cloud_unavailable_hint())
                                self.signals.ring_update.emit()
                                return
                        else:
                            # 模型未下载(§2 懒加载):提示后走云端;同时后台触发下载(带进度弹窗)
                            self.signals.system_msg.emit(
                                "本地模型未下载,先走云端(设置里可关本地模型)。"
                                "首次使用会在后台下载约 500MB…")
                            self.signals.local_dl_start.emit()
                            if not self._cloud_available():
                                # 本地模型也没下、云端也没有 → 无法继续,友好提示
                                self.signals.reply.emit(
                                    "本地模型还没下载,而且当前没有可用的云端服务。"
                                    "模型正在后台下载,下载完成后就能离线用了;"
                                    "或者到设置里配置云端服务(如 DeepSeek)。")
                                self.signals.ring_update.emit()
                                return
                    # decision==ask 或模型未就绪:落云端(ask 由云端循环触发 ask_user 交互)
                    if not self._cloud_available():
                        # 本地模式下路由判到 cloud/ask 但没有云端通道 → 友好提示,不拼空 URL
                        self.signals.reply.emit(self._cloud_unavailable_hint())
                        self.signals.ring_update.emit()
                        return
                # t15 修复:纯云端路径(is_local=False)进 chat_with_tools 前也校验云端通道——
                # ai_base_url 无效(空/无 http scheme)时不发起请求,直接友好提示
                # (is_local 分支内已有同款检查,这里补云端 provider 直通路径的漏网)。
                # t14 修复:落到云端时用 _cloud_settings()(本地模型下取 ai_cloud_* 那组),
                # 避免内置本地模型的空 base_url 拼出 "/chat/completions"。
                if not self._cloud_available():
                    self.signals.reply.emit(self._cloud_unavailable_hint())
                    self.signals.ring_update.emit()
                    return
                result = chat_with_tools(messages, self._cloud_settings(), mount_tools_for(text, self._cloud_settings()), executor,
                                         on_tool=on_tool, on_user_ask=self.on_user_ask,
                                         return_messages=True, cancel_event=self._agent_cancel)
                if isinstance(result, tuple):
                    reply, working = result
                    # 存回完整历史(去掉 system,下次重新生成)
                    self._chat_messages = [m for m in working
                                           if m.get("role") != "system"]
                else:   # 兼容旧 mock(返回字符串)
                    reply = result
                if not tools_called:
                    self.signals.no_tool.emit()
                self.signals.reply.emit(reply)
                self.signals.ring_update.emit()
            except Exception as e:
                # t15 修复:请求异常翻译成业务化中文(401/402/404/429/连接失败/超时),
                # 不再把技术栈原样冒泡给用户
                self.signals.error.emit(_friendly_cloud_error(e))

        self._agent_cancel = threading.Event()
        self._agent_running = True
        def tracked_worker():
            try:
                worker()
            finally:
                self._agent_running = False
        threading.Thread(target=tracked_worker, daemon=True).start()

    def _stop_agent_run(self):
        event = getattr(self, '_agent_cancel', None)
        if event is not None:
            event.set()
            dismiss = getattr(self, '_dismiss_action_confirmation', None)
            if dismiss is not None:
                dismiss(False)
            self._append_system('已请求停止；等待当前请求或工具安全结束。')

    def _open_run_records(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from paths import data_dir
        folder = data_dir('ai_runs')
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _est_message(self, m: dict) -> int:
        """估算一条消息的 token 数(支持多模态 content list)"""
        content = m.get("content")
        if isinstance(content, list):
            text = " ".join(str(c.get("text", "")) for c in content
                            if isinstance(c, dict) and c.get("type") == "text")
            return estimate_tokens(text)
        return estimate_tokens(str(content or ""))

    def _confirm_if_heavy(self, new_text: str) -> bool:
        """对话已用较多上下文时,发送前弹提示(这可需要不少 token),问是否继续。
        用户取消 → 保留输入框内容,不发送。"""
        from PySide6.QtWidgets import QMessageBox
        limit = int(self.settings.get("context_window", 65536) or 65536)
        used = sum(self._est_message(m) for m in self._chat_messages)
        used += estimate_tokens(new_text)
        if used <= int(limit * 0.6):
            return True
        ret = QMessageBox.question(
            self, t('继续对话?'),
            t('当前对话已用约 {v0:.1f}k tokens(占上下文 {v1}%)。\n继续这一轮会消耗不少 token,确定要继续吗?\n\n(选择"No"可保留输入内容,或开启新对话后重发)').format(v0=(used / 1000), v1=(used * 100 // limit)), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
        return ret == QMessageBox.StandardButton.Yes

    def _trim_history(self):
        """上下文超限时丢弃最早的消息(保留最近的,让对话能继续)"""
        limit = int(self.settings.get("context_window", 65536) or 65536)
        budget = int(limit * 0.7)   # 给回复留 30%
        while len(self._chat_messages) > 1:
            used = sum(self._est_message(m) for m in self._chat_messages)
            if used <= budget:
                break
            self._chat_messages.pop(0)   # 丢最早的一条(保留刚发的当前问题)
        self._update_ctx_ring()

    def _on_no_tool(self):
        self._append_system(
            "⚠️ 本轮对话模型没有调用任何工具。如果它只是说\"我将...\"而没动手,"
            "说明当前模型不支持工具调用(小模型常见),建议换更强的模型,"
            "或用 🛠 自测确认。")

    # ---- ask_user 交互:AI 不确定时显示输入框上方的选择卡片 ----
    def on_user_ask(self, question: str, options: list) -> str:
        """worker 线程调用:等待主线程卡片返回选择文本。"""
        result_box = []
        ev = threading.Event()
        self.signals.user_ask.emit(question, options, result_box, ev)
        while not ev.wait(0.2):
            if getattr(self, '_agent_cancel', threading.Event()).is_set():
                self.signals.user_ask_cancel.emit()
                return '用户已停止任务'
        picked = result_box[0] if result_box else []
        if not picked:
            return "用户取消了选择(未给答案)。请根据上下文自行处理,或向用户说明你需要的选择。"
        return "用户选择了:" + "、".join(str(p) for p in picked)

    def _confirm_ai_action(self, name: str, preview: str) -> bool:
        """worker 线程等待主线程完成“预览—确认”；同类动作可在本次会话中放行。"""
        if name not in {'restore_instance_snapshot', 'replace_mod_version', 'reset_instance'} and name in getattr(self, "_session_action_allow", set()):
            return True
        result_box = []
        ev = threading.Event()
        self.signals.system_msg.emit("需要你确认一个处理方案；请看 AI 助手里的操作卡片，也可以停止任务。")
        self.signals.action_confirm.emit(name, preview, result_box, ev)
        while not ev.wait(0.2):
            if getattr(self, '_agent_cancel', threading.Event()).is_set():
                return False
        if getattr(self, '_agent_cancel', threading.Event()).is_set():
            return False
        approved, remember = result_box[0] if result_box else (False, False)
        if approved and remember:
            self._session_action_allow = getattr(self, "_session_action_allow", set()) | {name}
        return bool(approved)

    def _notify_ai_autonomy(self, message: str):
        """Worker-safe notice shown once when backup-and-continue starts."""
        self.signals.system_msg.emit("🛟 " + message)

    def _on_action_confirm_ui(self, name, preview, result_box, ev):
        """Show the pending decision inside AI Dock without blocking the launcher."""
        if ev.is_set() or getattr(self, '_agent_cancel', threading.Event()).is_set():
            result_box.append((False, False))
            ev.set()
            return
        dismiss = getattr(self, '_dismiss_action_confirmation', None)
        if dismiss is not None:
            dismiss(False)
        plain = self.settings.get('ai_response_style', 'plain') == 'plain'
        card = QWidget(self)
        card.setObjectName('aiActionConfirmation')
        card.setStyleSheet(
            f'QWidget#aiActionConfirmation {{ background: {current_color("bg1")};'
            f' border: 1px solid {current_color("btn_border")}; border-radius: 8px; }}')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)
        heading = QLabel(t('AI 想执行这一步，请确认：') if plain else t('确认 AI 操作：'), card)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        details = QPlainTextEdit(card)
        details.setReadOnly(True)
        details.setPlainText(preview)
        details.setFixedHeight(92)
        layout.addWidget(details)
        remember = QCheckBox(t('本次同类操作直接继续'), card)
        layout.addWidget(remember)
        buttons = QHBoxLayout()
        approve = QPushButton(t('同意执行'), card)
        decline = QPushButton(t('先不要'), card)
        stop = QPushButton(t('停止任务'), card)
        buttons.addWidget(approve)
        buttons.addWidget(decline)
        buttons.addWidget(stop)
        layout.addLayout(buttons)
        self.widget().layout().insertWidget(0, card)
        self._confirm_card = card

        def finish(approved=False):
            if ev.is_set():
                return
            result_box.append((approved, approved and remember.isChecked()))
            ev.set()
            self._dismiss_action_confirmation = None
            self._confirm_card = None
            card.hide()
            card.deleteLater()

        self._dismiss_action_confirmation = finish
        approve.clicked.connect(lambda: finish(True))
        decline.clicked.connect(lambda: finish(False))
        stop.clicked.connect(self._stop_agent_run)
        self.show()

    def _undo_last_setting(self):
        from launcher_app.ai.ai_action_log import undo_last_setting
        self._append_system("↩ " + undo_last_setting())

    def _show_action_history(self):
        """Show the local audit trail without exposing it as a raw data file."""
        from launcher_app.ai.ai_action_log import recent_text
        dlg = QDialog(self)
        dlg.setWindowTitle(t('AI 操作记录'))
        dlg.resize(650, 500)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(t('记录保存在本机 AMCL/ai_actions.json；设置可用“撤销设置”回退。')))
        text = QPlainTextEdit(recent_text())
        text.setReadOnly(True)
        layout.addWidget(text, 1)
        close = QPushButton(t('关闭'))
        close.clicked.connect(dlg.accept)
        layout.addWidget(close)
        dlg.exec()

    def _on_user_ask_ui(self, question, options, result_box, ev):
        """主线程:显示卡片，提交后唤醒 worker。"""
        if getattr(self, '_agent_cancel', threading.Event()).is_set():
            result_box.append([])
            ev.set()
            return
        self._cancel_user_ask()
        self._pending_user_ask = (result_box, ev)
        self.show()
        self.raise_()
        self.tabs.setCurrentIndex(0)
        self.ask_user_panel.show_question(question, options)

    def _finish_user_ask(self, picked: list):
        pending = self._pending_user_ask
        if pending is None:
            return
        self._pending_user_ask = None
        self.ask_user_panel.hide()
        result_box, ev = pending
        result_box.append(picked)
        ev.set()

    def _cancel_user_ask(self):
        self._finish_user_ask([])

    # ---- 自测工具调用 ----
    def self_test_tools(self):
        if getattr(self, '_agent_running', False):
            self._append_system('当前任务还在运行。先点“停止任务”，结束后再自测。')
            return
        self._append_system("🛠 正在自测:让模型调用 list_instances 工具...")
        messages = [
            {"role": "system", "content": "请调用 list_instances 工具,把结果原样告诉我。不要只描述计划。"},
            {"role": "user", "content": "测试工具调用"},
        ]
        tools_called = []

        def on_tool(name, args, result):
            tools_called.append(name)
            self.signals.tool_called.emit(name, args, result)   # 跨线程安全

        def worker():
            try:
                chat_with_tools(messages, self.settings, TOOLS[:1],
                                build_executor(self.settings), on_tool=on_tool,
                                cancel_event=self._agent_cancel,
                                stop_after_first_tool=True)
                if not self._agent_cancel.is_set():
                    self.signals.self_test.emit(bool(tools_called))
            except Exception as e:
                self.signals.error.emit(str(e))
            finally:
                self._agent_running = False

        self._agent_cancel = threading.Event()
        self._agent_running = True
        threading.Thread(target=worker, daemon=True).start()

    def _on_self_test(self, ok: bool):
        if ok:
            self._append_system("✅ 自测通过:模型能正常调用工具。")
        else:
            self._append_system(
                "❌ 自测失败:模型没有调用任何工具。它可能不支持工具调用——\n"
                "建议换模型:qwen2.5-14b/32b-instruct 等支持工具调用的模型,"
                "或云端 DeepSeek(工具调用很稳);在 LM Studio 里确认模型的"
                "chat template 支持 function calling。")

    def _on_reply(self, text: str):
        self._append_ai(text)

    def _on_error(self, err: str):
        self._append_system(f"请求失败:{err}")

    # ---- 技能管理(入口在 AI 子窗口顶部) ----
    def open_skill_manager(self):
        if self.main is not None and hasattr(self.main, "open_skill_manager"):
            self.main.open_skill_manager()
        else:
            self._append_system("技能管理需要在主窗口打开")

    # ---- 设置 ----
    def apply_settings(self, settings: dict):
        """同步已保存配置及所有依赖配置的面板显示。"""
        self.settings = settings
        self._sync_preference_popover()
        self.update_vision_ui()
        self.update_local_status()
        self.maybe_preload_local()

    def open_settings(self):
        def autosave(live: dict):
            # 表单每次改动 → 立即落盘并同步三处(主窗/设置中心/dock),无需手动保存
            self.settings = live
            self.main.settings = live
            if getattr(self.main, "settings_center", None) is not None:
                self.main.settings_center.settings.update(live)
            save_settings(live)
            self.apply_settings(live)
            settings_center = getattr(self.main, "settings_center", None)
            if settings_center is not None and hasattr(settings_center, "refresh_ai_config_visibility"):
                settings_center.refresh_ai_config_visibility()

        dlg = AISettingsDialog(self.settings, self, autosave=autosave)
        dlg.exec()   # 改动已实时自动保存;关闭即结束,无需再点保存
