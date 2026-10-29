"""GUI task presentation API. Work stays in its existing worker/controller.

begin_task/update_task/finish_task describe state; register_page supplies details;
request_confirmation queues an asynchronous choice without blocking the window.
All methods are called on the Qt GUI thread. See docs/task-center.md.
"""
from launcher_app.core.i18n import t
from collections import deque
from dataclasses import dataclass, field
import uuid

from PySide6.QtCore import Qt, QObject, Signal, QPoint, QRect, QEvent, QEventLoop, QVariantAnimation, QEasingCurve
from PySide6.QtWidgets import (QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout,
                              QLabel, QPushButton, QTabWidget, QPlainTextEdit, QProgressBar, QMessageBox, QScrollArea)
from launcher_app.ui.ui_style import set_style, current_color, text_color, card_btn_style, progress_bar_style
from launcher_app.ui.ui_anim import is_animations_enabled, track_animation


@dataclass
class TaskState:
    id: str
    title: str
    state: str = 'running'
    message: str = ''
    done: int = 0
    total: int = 0
    cancel: object = None
    page: object = None
    view: dict = field(default_factory=dict)


class FloatingTaskWindow(QDialog):
    """Nonmodal, draggable tool window; hiding never cancels work."""
    hidden = Signal()

    def __init__(self, title, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle(title)
        self._drag = None
        self._placed = False
        self._collapsing = False
        self._expanded_geometry = None
        self._animation = QVariantAnimation(self)
        track_animation(self._animation)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._animate_frame)
        self._animation.finished.connect(self._animation_finished)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(8, 6, 8, 8)
        self.body.setSpacing(4)
        self.header = QLabel(title)
        self.header.setObjectName('task_window_drag_handle')
        self.header.setCursor(Qt.CursorShape.SizeAllCursor)
        self.header.setFixedHeight(20)
        title_font = self.header.font()
        title_font.setPointSizeF(9)
        self.header.setFont(title_font)
        self.header.installEventFilter(self)
        self.body.addWidget(self.header)
        set_style(self, lambda: f'QDialog {{ background:{current_color("bg0")}; color:{text_color()};'
                  f' border:1px solid {current_color("btn_border")}; border-radius:12px; }}'
                  f'QLabel {{ color:{text_color()}; border:0; background:transparent; }}')

    def eventFilter(self, obj, event):
        if obj is self.header:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._animation.stop()
                self._placed = True
                handle = self.windowHandle()
                if handle and handle.startSystemMove():
                    return True
                self._drag = event.globalPosition().toPoint() - self.pos()
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag is not None:
                self.move(event.globalPosition().toPoint() - self._drag)
                self._clamp()
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag = None
        return super().eventFilter(obj, event)

    def _clamp(self):
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.setMaximumSize(area.size())
            self.resize(min(self.width(), area.width()), min(self.height(), area.height()))
            self.move(max(area.left(), min(self.x(), area.right() - self.width() + 1)),
                      max(area.top(), min(self.y(), area.bottom() - self.height() + 1)))

    def present(self, ball):
        owner = ball.window()
        if not owner.isVisible() or owner.isMinimized():
            return
        if self._collapsing:
            self._animation.stop()
            self._collapsing = False
            self.setGeometry(self._expanded_geometry)
        self.setWindowOpacity(1.0)
        origin = ball.mapToGlobal(QPoint(0, 0))
        area = QRect(owner.mapToGlobal(QPoint(0, 0)), owner.size()).adjusted(8, 8, -8, -8)
        screen = owner.screen()
        if screen:
            area = area.intersected(screen.availableGeometry())
        sphere = QRect(origin, ball.size())
        gap = 8
        regions = [
            ('above', QRect(area.left(), area.top(), area.width(), max(0, sphere.top() - gap - area.top()))),
            ('below', QRect(area.left(), sphere.bottom() + gap + 1, area.width(), max(0, area.bottom() - sphere.bottom() - gap))),
            ('left', QRect(area.left(), area.top(), max(0, sphere.left() - gap - area.left()), area.height())),
            ('right', QRect(sphere.right() + gap + 1, area.top(), max(0, area.right() - sphere.right() - gap), area.height())),
        ]
        regions = [(side, region.intersected(area)) for side, region in regions]
        preferred = self._expanded_geometry.size() if self._expanded_geometry else self.size()
        side, region = max(regions, key=lambda item:
            min(preferred.width(), item[1].width()) * min(preferred.height(), item[1].height()))
        self.setMaximumSize(region.size())
        self.resize(min(preferred.width(), region.width()), min(preferred.height(), region.height()))
        width, height = self.width(), self.height()
        x = max(region.left(), min(sphere.center().x() - width // 2, region.right() - width + 1))
        y = max(region.top(), min(sphere.center().y() - height // 2, region.bottom() - height + 1))
        if side == 'above':
            y = region.bottom() - height + 1
        elif side == 'below':
            y = region.top()
        elif side == 'left':
            x = region.right() - width + 1
        else:
            x = region.left()
        previous = self.geometry()
        if not (self._placed and getattr(self, '_last_ball_origin', None) == origin
                and area.contains(previous) and not previous.intersects(sphere)):
            self.move(x, y)
        self._last_ball_origin = origin
        target = self.geometry()
        self._expanded_geometry = target
        self.show()
        self.raise_()  # no activateWindow: opening a request does not steal typing.
        if is_animations_enabled():
            start = ball.geometry()
            start.moveTopLeft(origin)
            self._animation.setStartValue(start)
            self._animation.setEndValue(target)
            self._animation.start()

    def collapse(self, ball):
        if self._collapsing or not self.isVisible():
            return
        if not is_animations_enabled():
            self.hide()
            return
        if self._animation.state() != QVariantAnimation.State.Running:
            self._expanded_geometry = self.geometry()
        self._animation.stop()
        self._collapsing = True
        target = ball.geometry()
        target.moveTopLeft(ball.mapToGlobal(QPoint(0, 0)))
        self._animation.setStartValue(self.geometry())
        self._animation.setEndValue(target)
        self._animation.start()

    def _animate_frame(self, geometry):
        self.setGeometry(geometry)
        if self._collapsing:
            elapsed = self._animation.currentTime() / max(1, self._animation.duration())
            self.setWindowOpacity(1.0 if elapsed <= 0.5 else max(0.0, 2.0 * (1.0 - elapsed)))

    def _animation_finished(self):
        if self._collapsing:
            self._collapsing = False
            self.hide()
            self.setGeometry(self._expanded_geometry)

    def closeEvent(self, event):
        self.hide()
        event.ignore()

    def hideEvent(self, event):
        was_animating = self._animation.state() == QVariantAnimation.State.Running
        self._animation.stop()
        self._drag = None
        restore_geometry = self._collapsing or was_animating
        self._collapsing = False
        if restore_geometry and self._expanded_geometry is not None:
            self.setGeometry(self._expanded_geometry)
        self.setWindowOpacity(1.0)
        super().hideEvent(event)
        self.hidden.emit()


class TaskCenter(QObject):
    changed = Signal()
    update_requested = Signal(str, object)

    def __init__(self, ball, parent=None):
        super().__init__(parent)
        self.ball = ball
        self.owner = ball.window()
        self.tasks = {}
        self._requests = deque()
        self._answering = False
        self.details = FloatingTaskWindow('任务与状态', self.owner)
        self.details.resize(760, 560)
        self.tabs = QTabWidget()
        self.tabs.setObjectName('task_center_tabs')
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.details.setObjectName('task_center_window')
        self.details.body.addWidget(self.tabs, 1)
        self.card = FloatingTaskWindow('等待确认', self.owner)
        self.card.setObjectName('task_confirmation_window')
        self.card.resize(440, 240)
        self.question = QLabel()
        self.question.setObjectName('task_confirmation_question')
        self.question.setWordWrap(True)
        self.question.setTextFormat(Qt.TextFormat.PlainText)
        self.question.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        question_scroll = QScrollArea()
        question_scroll.setWidgetResizable(True)
        question_scroll.setWidget(self.question)
        set_style(question_scroll, lambda: f'QScrollArea {{ background:{current_color("bg0")}; border:0; }}')
        self.card.body.addWidget(question_scroll, 1)
        self.choices = QHBoxLayout()
        self.card.body.addLayout(self.choices)
        self.card.hidden.connect(self._card_hidden)
        self.changed.connect(self._refresh)
        self.update_requested.connect(self._apply_report)
        QApplication.instance()._amcl_task_center = self
        QApplication.instance().installEventFilter(self)
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def eventFilter(self, obj, event):
        if obj is self.owner and (event.type() == QEvent.Type.Hide or
                (event.type() == QEvent.Type.WindowStateChange and self.owner.isMinimized())):
            # Stop in-flight geometry animations as well as hiding the windows.
            # Pending work/questions remain available through the ball on restore.
            self.card.hide()
            self.details.hide()
        # Clicking back into the launcher collapses the card to its waiting
        # ball instead of leaving an inaccessible tool window behind it.
        if (event.type() == QEvent.Type.MouseButtonPress and self.card.isVisible()
                and isinstance(obj, QWidget) and obj is not self.ball and obj.window() is not self.card):
            self.card.collapse(self.ball)
        return super().eventFilter(obj, event)

    def _card_hidden(self):
        self.ball.show()
        self.ball.raise_()

    def begin_task(self, title, *, task_id=None, page=None, cancel=None):
        task_id = task_id or uuid.uuid4().hex
        if task_id not in self.tasks:
            record = self.tasks[task_id] = TaskState(task_id, title, cancel=cancel)
            if page is None:
                page = QWidget()
                layout = QVBoxLayout(page)
                status = QLabel(t('正在处理…'))
                status.setTextFormat(Qt.TextFormat.PlainText)
                status.setWordWrap(True)
                progress = QProgressBar()
                set_style(progress, progress_bar_style)
                progress.setRange(0, 0)
                log = QPlainTextEdit()
                log.setReadOnly(True)
                log.setMaximumBlockCount(2000)
                button = QPushButton(t('取消任务'))
                button.clicked.connect(lambda: self.cancel_task(task_id))
                set_style(button, card_btn_style)
                for widget in (status, progress, log, button):
                    layout.addWidget(widget)
                record.view = {'status': status, 'progress': progress, 'log': log, 'cancel': button}
            self.register_page(task_id, page)
        else:
            record = self.tasks[task_id]
            record.title, record.cancel, record.state = title, cancel, 'running'
            record.done = record.total = 0
            if page is not None:
                self.register_page(task_id, page)
            elif self.tabs.indexOf(record.page) < 0:
                self.register_page(task_id, record.page)
        self.changed.emit()
        return task_id

    def register_page(self, task_id, page):
        record = self.tasks[task_id]
        if record.page is not None:
            self.tabs.removeTab(self.tabs.indexOf(record.page))
        page.setParent(self.tabs)
        page.setWindowFlags(Qt.WindowType.Widget)
        page._status_task_id = task_id
        record.page = page
        self.tabs.addTab(page, record.title)

    def _close_tab(self, index):
        page = self.tabs.widget(index)
        if page is None:
            return
        # Retain the page/controller: closing presentation must not cancel work.
        self.tabs.removeTab(index)
        page.hide()
        if self.tabs.count() == 0:
            self.details.collapse(self.ball)

    def update_task(self, task_id, *, message=None, done=None, total=None, state=None):
        record = self.tasks.get(task_id)
        if record is None:
            return
        if message is not None:
            from launcher_app.core.log_privacy import redact_text
            record.message = redact_text(message, getattr(self.parent(), 'settings', None))
            if record.view:
                record.view['status'].setText(record.message)
                record.view['log'].appendPlainText(record.message)
        if done is not None:
            record.done = max(0, int(done))
        if total is not None:
            record.total = max(0, int(total))
        if state is not None:
            record.state = state
        if record.view:
            bar = record.view['progress']
            bar.setRange(0, 1000 if record.total else 0)
            if record.total:
                bar.setValue(min(1000, record.done * 1000 // record.total))
            record.view['cancel'].setEnabled(record.cancel is not None and record.state == 'running')
        self.changed.emit()

    def report(self, task_id, **fields):
        """Thread-safe status/progress submission for workers and plugins."""
        self.update_requested.emit(task_id, fields)

    def _apply_report(self, task_id, fields):
        self.update_task(task_id, **fields)

    def finish_task(self, task_id, state='completed', message=None):
        self.update_task(task_id, state=state, message=message)
        record = self.tasks.get(task_id)
        if record and record.view:
            record.view['progress'].setRange(0, 1000)
            record.view['progress'].setValue(1000 if state == 'completed' else 0)

    def cancel_task(self, task_id):
        record = self.tasks.get(task_id)
        if record and record.cancel:
            record.cancel()

    def attach_background(self, task, task_id, *, finish=True):
        task.status.connect(lambda message: self.update_task(task_id, message=message))
        task.progress.connect(lambda done, total: self.update_task(task_id, done=done, total=total))
        task.failed.connect(lambda error: self.finish_task(task_id, 'failed', error))
        task.cancelled_signal.connect(lambda: self.finish_task(task_id, 'cancelled', '任务已取消'))
        if finish:
            task.succeeded.connect(lambda _: self.finish_task(task_id))
        self.update_task(task_id, state='running', done=0, total=0)

    def request_confirmation(self, task_id, title, question, choices, callback):
        """choices: [(button text, value)]. callback(None) on application shutdown."""
        if task_id not in self.tasks:
            self.begin_task(title, task_id=task_id)
        self._requests.append((task_id, title, question, choices, callback))
        self.changed.emit()
        if len(self._requests) == 1 and not self._answering:
            self._present_question()

    def cancel_confirmation(self, task_id):
        matches = [request for request in self._requests if request[0] == task_id]
        if not matches:
            return False
        self._requests = deque(request for request in self._requests if request[0] != task_id)
        self.card.hide()
        for request in matches:
            request[4](None)
        self.changed.emit()
        if self._requests:
            self._present_question()
        return True

    def _present_question(self):
        if not self._requests:
            return
        task_id, title, question, choices, _ = self._requests[0]
        self.card.header.setText(t('{v0} · 待确认 {v1} 项').format(v0=(title), v1=(len(self._requests))))
        self.question.setText(question)
        while self.choices.count():
            old = self.choices.takeAt(0).widget()
            old.hide()
            old.setObjectName('')
            old.setParent(None)
            old.deleteLater()
        for index, (label, value) in enumerate(choices):
            button = QPushButton(label)
            button.setObjectName(f'task_confirmation_choice_{index}')
            button.setAutoDefault(False)
            button.setDefault(False)
            set_style(button, card_btn_style)
            button.clicked.connect(lambda checked=False, v=value: self._answer(v))
            self.choices.addWidget(button)
        self.card.present(self.ball)
        self.details.hide()
        self.ball.show()
        self.ball.raise_()

    def _answer(self, value):
        if not self._requests or self._answering:
            return
        self._answering = True
        request = self._requests.popleft()
        # Disable old buttons before invoking a continuation that may queue another request.
        for index in range(self.choices.count()):
            self.choices.itemAt(index).widget().setEnabled(False)
        self.card.hide()
        try:
            request[4](value)
        finally:
            self._answering = False
            self.changed.emit()
            if self._requests:
                self._present_question()

    def present(self):
        for window in (self.card, self.details):
            if window._collapsing:
                window.present(self.ball)
                return
        if self.card.isVisible() or self.details.isVisible():
            self.card.collapse(self.ball)
            self.details.collapse(self.ball)
            return
        if self._requests:
            self._present_question()
        else:
            for record in self.tasks.values():
                if record.state in ('running', 'incomplete') and self.tabs.indexOf(record.page) < 0:
                    self.register_page(record.id, record.page)
            self.details.present(self.ball)

    def show_task(self, task_id):
        self.card.hide()
        record = self.tasks.get(task_id)
        if record:
            if self.tabs.indexOf(record.page) < 0:
                self.register_page(task_id, record.page)
            self.tabs.setCurrentWidget(record.page)
        self.details.present(self.ball)

    def _refresh(self):
        waiting = {request[0] for request in self._requests}
        labels = {'running': '进行中', 'completed': '完成', 'failed': '失败', 'cancelled': '已取消', 'idle': '就绪', 'incomplete': t('导入未完成')}
        for record in self.tasks.values():
            state = '待确认' if record.id in waiting else labels.get(record.state, record.state)
            index = self.tabs.indexOf(record.page)
            if index >= 0:
                self.tabs.setTabText(index, f'{record.title} · {state}')
        active = sum(record.state == 'running' and record.id not in waiting for record in self.tasks.values())
        failed = any(record.state == 'failed' for record in self.tasks.values())
        self.ball.set_persistent_failure(any(record.state == 'incomplete' for record in self.tasks.values()))
        if not active and not waiting:
            if failed:
                self.ball.set_failed()
            elif any(record.state == 'completed' for record in self.tasks.values()):
                self.ball.set_completed()
            else:
                self.ball.set_waiting()
        if self._requests and self.card.isVisible():
            self.card.header.setText(t('{v0} · 待确认 {v1} 项').format(v0=(self._requests[0][1]), v1=(len(self._requests))))
        self.ball.set_task_summary(active, len(self._requests), failed)
        if self.ball._persistent_failure:
            self.ball.setToolTip(t('整合包导入未完成，点击继续补齐或手动忽略'))

    def shutdown(self):
        requests = list(self._requests)
        self._requests.clear()
        self.card.hide()
        self.details.hide()
        for request in requests:
            request[4](None)


def task_center_for(widget=None):
    app = QApplication.instance()
    return getattr(app, '_amcl_task_center', None) if app else None


def task_choice(parent, title, text, choices):
    """GUI-thread compatibility bridge for task confirmations with several choices.

    choices contains (label, value) pairs; dismissing the prompt returns None.
    """
    center = task_center_for(parent)
    from launcher_app.ui.ui_notifications import notifications_enabled
    if center is None or not notifications_enabled():
        dialog = QMessageBox(parent)
        dialog.setWindowTitle(title)
        dialog.setText(text)
        mapped = [(dialog.addButton(label, QMessageBox.ButtonRole.ActionRole), value)
                  for label, value in choices]
        dialog.exec()
        return next((value for button, value in mapped
                     if dialog.clickedButton() is button), None)
    import hashlib
    key = hashlib.sha256((type(parent).__name__ + ':' + title).encode()).hexdigest()[:20]
    task_id = center.begin_task(title, task_id='prompt-' + key)
    loop = QEventLoop()
    answer = [None]
    def done(value):
        answer[0] = value
        center.finish_task(task_id, 'cancelled' if value is None else 'completed')
        loop.quit()
    center.request_confirmation(task_id, title, text, choices, done)
    loop.exec()
    return answer[0]


def task_question(parent, title, text, buttons=None, default=None, *, yes_text='确认', no_text='取消'):
    """Compatibility bridge for existing GUI-thread Yes/No callers.

    New flows should use request_confirmation callbacks directly. The local
    Qt event loop keeps the main window responsive for legacy synchronous code.
    """
    center = task_center_for(parent)
    from launcher_app.ui.ui_notifications import notifications_enabled
    if center is None or not notifications_enabled():
        return QMessageBox.question(parent, title, text, buttons or
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default or QMessageBox.StandardButton.Yes)
    owner = parent
    task_id = None
    while owner is not None:
        task_id = getattr(owner, '_status_task_id', None)
        if task_id:
            break
        owner = owner.parentWidget()
    standalone = not task_id
    if not task_id:
        import hashlib
        key = hashlib.sha256((type(parent).__name__ + ':' + title).encode()).hexdigest()[:20]
        task_id = center.begin_task(title, task_id='prompt-' + key)
    loop = QEventLoop()
    answer = [QMessageBox.StandardButton.No]
    def done(value):
        answer[0] = QMessageBox.StandardButton.Yes if value else QMessageBox.StandardButton.No
        if standalone:
            center.finish_task(task_id, 'completed' if value else 'cancelled')
        loop.quit()
    center.request_confirmation(task_id, title, text, [(yes_text, True), (no_text, False)], done)
    loop.exec()
    return answer[0]
