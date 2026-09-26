"""Conversation-first launcher mode and its fixed-length transition."""

import math

from PySide6.QtCore import QElapsedTimer, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ui_style import (accent_color, card_btn_style, current_color,
                      muted_color, set_style, text_color)
from ui_background import BackgroundWidget
from version_home import LoginCard


class AIFocusSidebar(BackgroundWidget):
    """Account and instance shortcuts beside the existing live AI conversation."""

    def __init__(self, launcher):
        super().__init__(launcher)
        self.launcher = launcher
        self.setMinimumWidth(220)
        self.setMaximumWidth(300)
        set_style(self, lambda: (
            f"border-right: 1px solid {current_color('panel_border')};"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 14)
        layout.setSpacing(12)
        self.login_card = LoginCard(self)
        self.login_card.changed.connect(launcher._on_login_changed)
        layout.addWidget(self.login_card)

        instance_title = QLabel("实例与会话")
        set_style(instance_title, lambda: f"color: {muted_color()}; font-size: 12px;")
        layout.addWidget(instance_title)
        new_button = QPushButton('＋ 新会话')
        set_style(new_button, card_btn_style)
        new_button.clicked.connect(self._new_session)
        layout.addWidget(new_button)
        self.sessions = QTreeWidget()
        self.sessions.setHeaderHidden(True)
        set_style(self.sessions, lambda: (
            f'QTreeWidget {{ background: transparent; color: {text_color()};'
            ' border: none; outline: none; }'
            'QTreeWidget::item { padding: 5px 3px; }'
            f'QTreeWidget::item:selected {{ background: {current_color("sel_bg")};'
            f' color: {text_color()}; }}'
            f'QTreeWidget::item:hover {{ background: {current_color("list_hover")}; }}'))
        self.sessions.itemClicked.connect(self._activate_item)
        self.sessions.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sessions.customContextMenuRequested.connect(self._instance_context_menu)
        layout.addWidget(self.sessions, 1)
        save_button = QPushButton('保存当前会话')
        set_style(save_button, card_btn_style)
        save_button.clicked.connect(self._save_session)
        layout.addWidget(save_button)

        self.launch_button = QPushButton("▶ 启动选中实例")
        set_style(self.launch_button, card_btn_style)
        self.launch_button.clicked.connect(launcher.launch_selected_instance)
        layout.addWidget(self.launch_button)
        self.refresh_sessions()

    def refresh_from_home(self):
        self.login_card.refresh()
        self.refresh_sessions()

    def refresh_sessions(self):
        import chat_archive
        groups = {}
        source = self.launcher.instance_list
        self.sessions.clear()
        for index in range(source.count()):
            original = source.item(index)
            inst = original.data(Qt.ItemDataRole.UserRole) or {}
            instance_id = inst.get('id')
            if instance_id:
                item = QTreeWidgetItem(self.sessions, [original.text()])
                item.setIcon(0, original.icon())
                item.setData(0, Qt.ItemDataRole.UserRole, ('instance', instance_id))
                groups[instance_id] = item
        dock = getattr(self.launcher, 'ai_dock', None)
        if dock is not None:
            current_id = getattr(dock, '_session_instance_id', '') or ''
            first_user = next((entry.text for entry in dock._entries
                               if entry.kind == 'user'), '')
            if first_user:
                QTreeWidgetItem(groups.get(current_id, self.sessions),
                                ['当前 · ' + first_user[:18]])
        for session in chat_archive.list_sessions():
            instance_id = session.get('instance_id') or ''
            item = QTreeWidgetItem(groups.get(instance_id, self.sessions), [session['title']])
            item.setData(0, Qt.ItemDataRole.UserRole, ('session', session['path']))
            item.setToolTip(0, session.get('created_at', ''))
        self.sessions.expandAll()
        self.launch_button.setEnabled(source.currentItem() is not None)

    def _activate_item(self, item, _column):
        kind, value = item.data(0, Qt.ItemDataRole.UserRole) or (None, None)
        if kind == 'session':
            self.launcher.ai_dock.load_session_path(value)
        elif kind == 'instance':
            self._select_instance(value)

    def _instance_context_menu(self, pos):
        item = self.sessions.itemAt(pos)
        if item is None:
            return
        kind, instance_id = item.data(0, Qt.ItemDataRole.UserRole) or (None, None)
        if kind != 'instance':
            return
        source = self.launcher.instance_list
        for index in range(source.count()):
            original = source.item(index)
            inst = original.data(Qt.ItemDataRole.UserRole) or {}
            if inst.get('id') == instance_id:
                self._select_instance(instance_id)
                self.launcher._show_instance_menu(
                    inst, self.sessions.viewport().mapToGlobal(pos))
                return

    def _save_session(self):
        if self.launcher.ai_dock.save_current_session(show_feedback=True):
            self.refresh_sessions()

    def _new_session(self):
        if self.launcher.ai_dock.new_session():
            self.launcher.instance_list.setCurrentRow(-1)
            self.launch_button.setEnabled(False)
            self.refresh_sessions()

    def _select_instance(self, instance_id):
        source = self.launcher.instance_list
        for index in range(source.count()):
            original = source.item(index)
            if (original.data(Qt.ItemDataRole.UserRole) or {}).get('id') == instance_id:
                source.setCurrentItem(original)
                self.launch_button.setEnabled(True)
                return


class AIFocusTransition(QWidget):
    """A 1.8-second overlay; completion is driven by time, not AI readiness."""

    finished = Signal()
    DURATION_MS = 1800

    def __init__(self, parent, entering=True):
        super().__init__(parent)
        self.entering = entering
        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._advance)

    def start(self):
        self.clock.start()
        self.timer.start()
        self.show()
        self.raise_()

    def _advance(self):
        if self.clock.elapsed() >= self.DURATION_MS:
            self.timer.stop()
            self.finished.emit()
        else:
            self.update()

    def paintEvent(self, _event):
        progress = min(1.0, self.clock.elapsed() / self.DURATION_MS)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(current_color('bg1')))
        center = self.rect().center()
        accent = QColor(accent_color())
        for index, radius in enumerate((46, 66, 88)):
            color = QColor(accent)
            color.setAlpha((200, 115, 55)[index])
            pen = QPen(color, 3 if index == 0 else 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            angle = (progress * (270 if index % 2 == 0 else -210) + index * 95) % 360
            painter.drawArc(QRectF(center.x() - radius, center.y() - radius - 28,
                                   radius * 2, radius * 2), int(angle * 16), 105 * 16)
        painter.setPen(accent)
        font = QFont()
        font.setPointSize(27)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(center.x() - 150, center.y() - 70, 300, 84),
                         Qt.AlignmentFlag.AlignCenter, "✦")
        painter.setPen(QColor(text_color()))
        font.setPointSize(17)
        painter.setFont(font)
        title = "进入 AI 模式" if self.entering else "切换到常规模式"
        painter.drawText(QRectF(0, center.y() + 72, self.width(), 40),
                         Qt.AlignmentFlag.AlignCenter, title)
        painter.setPen(QColor(muted_color()))
        font.setPointSize(10)
        painter.setFont(font)
        phase = ("整理工作台" if progress < .35 else
                 "接入对话" if progress < .72 else "准备就绪")
        painter.drawText(QRectF(0, center.y() + 112, self.width(), 28),
                         Qt.AlignmentFlag.AlignCenter, phase)
        bar_width = min(280, max(120, self.width() - 80))
        bar_x = (self.width() - bar_width) / 2
        bar_y = center.y() + 155
        painter.setPen(Qt.PenStyle.NoPen)
        track = QColor(accent)
        track.setAlpha(45)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_width, 4), 2, 2)
        painter.setBrush(accent)
        # Gentle easing, while still reaching 100% at the fixed deadline.
        eased = .5 - .5 * math.cos(progress * math.pi)
        painter.drawRoundedRect(QRectF(bar_x, bar_y, bar_width * eased, 4), 2, 2)
        painter.end()
