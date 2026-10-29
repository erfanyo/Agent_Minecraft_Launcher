"""Explicit notification routing: task notices, inline feedback, local choices.

Never monkeypatch QMessageBox globally: AI, authorization, file picking and
EULA retain their specialized interactions. All entry points run on GUI thread.
"""
from launcher_app.core.i18n import t
from PySide6.QtCore import Qt, QEvent, QEventLoop, Signal, QTimer, QPoint
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox, QWidget
from launcher_app.ui.ui_style import set_style, current_color, text_color, warning_color, card_btn_style


def notifications_enabled():
    from settings import load_settings
    return bool(load_settings().get('ui_task_notifications', True))


def _owner_task(parent):
    from launcher_app.ui.task_center import task_center_for
    hub = task_center_for(parent)
    owner = parent
    while owner is not None:
        task_id = getattr(owner, '_status_task_id', None)
        if hub and task_id in hub.tasks:
            return hub, task_id
        owner = owner.parentWidget()
    return hub, None


def task_notice(parent, title, message, *, error=False):
    """Record a task outcome without forcing a blocking acknowledgement."""
    hub, task_id = _owner_task(parent)
    if hub is None or not notifications_enabled():
        method = QMessageBox.warning if error else QMessageBox.information
        return method(parent, title, str(message))
    if task_id is None:
        import hashlib
        task_id = 'notice-' + hashlib.sha256((type(parent).__name__ + title).encode()).hexdigest()[:20]
        hub.begin_task(title, task_id=task_id)
    hub.finish_task(task_id, 'failed' if error else 'completed', f'{title}\n{message}')
    record = hub.tasks[task_id]
    label = getattr(record.page, 'progress_label', None)
    if label is not None:
        label.setText(f'{title}：{message}')
    hub.ball.show()
    hub.ball.raise_()


def task_warning(parent, title, message):
    return task_notice(parent, title, message, error=True)


class LocalPrompt(QFrame):
    answered = Signal(bool)

    def __init__(self, parent, title, message):
        root = parent.window()
        super().__init__(root)
        self.setObjectName('local_notification')
        self.body = QVBoxLayout(self)
        heading = QLabel(str(title))
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setStyleSheet('font-weight:bold;')
        label = QLabel(str(message))
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        self.body.addWidget(heading)
        self.body.addWidget(label)
        self._answered = False
        set_style(self, lambda: f'QFrame#local_notification {{ background:{current_color("bg0")};'
                  f' border:1px solid {current_color("btn_border")}; border-radius:9px; }}'
                  f'QLabel {{ color:{text_color()}; background:transparent; border:0; }}')

    def place(self, anchor=None):
        root = self.parentWidget()
        self.setFixedWidth(min(420, max(180, root.width() - 24)))
        self.adjustSize()
        point = root.mapFromGlobal(QCursor.pos())
        if anchor is not None and anchor.window() is root:
            point = anchor.mapTo(root, QPoint(0, anchor.height() + 6))
        if not root.rect().contains(point):
            point = QPoint(12, 12)
        self.move(max(8, min(point.x(), root.width() - self.width() - 8)),
                  max(8, min(point.y(), root.height() - self.height() - 8)))
        self.show()
        self.raise_()

    def answer(self, value):
        if self._answered:
            return
        self._answered = True
        self.hide()
        self.answered.emit(value)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.answer(False)
                return True
        if (event.type() == QEvent.Type.MouseButtonPress and isinstance(obj, QWidget)
                and obj is not self and not self.isAncestorOf(obj)):
            self.answer(False)
        return False


def inline_notice(parent, title, message, *, anchor=None, kind='information'):
    """Show validation feedback at the edit/action location, with no event loop."""
    from launcher_app.ui.task_center import task_center_for
    if task_center_for(parent) is None or not notifications_enabled():
        return getattr(QMessageBox, kind)(parent, title, str(message))
    previous = getattr(parent, '_inline_notification', None)
    if previous is not None:
        previous.hide()
        previous.deleteLater()
    prompt = LocalPrompt(parent, title, message)
    parent._inline_notification = prompt
    close = QPushButton(t('关闭'), prompt)
    set_style(close, card_btn_style)
    close.clicked.connect(prompt.hide)
    prompt.body.addWidget(close)
    prompt.place(anchor or QApplication.focusWidget())
    timer = QTimer(prompt)
    timer.setSingleShot(True)
    timer.timeout.connect(prompt.hide)
    timer.start(8000)
    return prompt


def inline_warning(parent, title, message):
    return inline_notice(parent, title, message, kind='warning')


def action_question(parent, title, message, buttons=None, default=None, *,
                    anchor=None, yes_text='确认', no_text='取消', kind='question'):
    """Immediate Yes/No confirmation next to the action; never enters task hub."""
    from launcher_app.ui.task_center import task_center_for
    supported = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    if (task_center_for(parent) is None or not notifications_enabled()
            or buttons is not None and buttons != supported):
        return getattr(QMessageBox, kind)(parent, title, message, buttons or supported,
                                          default or QMessageBox.StandardButton.Yes)
    prompt = LocalPrompt(parent, title, message)
    prompt.setObjectName('local_action_confirmation')
    # Keep the frame selector used by the common style.
    set_style(prompt, lambda: f'QFrame#local_action_confirmation {{ background:{current_color("bg0")};'
              f' border:1px solid {current_color("btn_border")}; border-radius:9px; }}'
              f'QLabel {{ color:{text_color()}; border:0; }}')
    row = QHBoxLayout()
    for index, (label, value) in enumerate(((yes_text, True), (no_text, False))):
        button = QPushButton(label)
        button.setObjectName(f'local_action_choice_{index}')
        button.setAutoDefault(False)
        button.setDefault(False)
        set_style(button, card_btn_style)
        button.clicked.connect(lambda checked=False, v=value: prompt.answer(v))
        row.addWidget(button)
    prompt.body.addLayout(row)
    loop = QEventLoop()
    answer = [False]
    def chosen(value):
        answer[0] = value
        loop.quit()
    prompt.answered.connect(chosen)
    app = QApplication.instance()
    app.installEventFilter(prompt)
    app.aboutToQuit.connect(loop.quit)
    prompt.place(anchor or QApplication.focusWidget())
    try:
        loop.exec()
    finally:
        app.removeEventFilter(prompt)
        app.aboutToQuit.disconnect(loop.quit)
        prompt.hide()
        prompt.deleteLater()
    return QMessageBox.StandardButton.Yes if answer[0] else QMessageBox.StandardButton.No
