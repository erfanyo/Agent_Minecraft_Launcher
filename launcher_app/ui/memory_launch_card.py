"""Non-modal launch memory advice. The game starts while the advice stays available."""
from launcher_app.core.i18n import t
import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable
from launcher_app.runtime.launch_memory import assess_launch_memory, WindowReadiness, WindowReadinessTracker
from PySide6.QtCore import Qt, QTimer, QEvent, QPointF, QPropertyAnimation
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox
from launcher_app.ui.ui_style import set_style, card_btn_style, muted_color, accent_color, current_color, text_color
from launcher_app.runtime.memory_policy import snapshot, automatic_budget, history_peak, enabled_mod_count, GIB
from launcher_app.runtime.memory_relief import pressure, visible_game_window


class MemoryTrend(QWidget):
    """A bounded, one-minute available-memory trace; samples stay in memory."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples = deque(maxlen=60)
        self.setFixedHeight(64)

    def sample(self, available):
        self.samples.append(available / GIB if available is not None else None)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(muted_color()))
        valid = [value for value in self.samples if value is not None]
        if not valid:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '等待内存采样…')
            return
        low, high = min(valid), max(valid)
        painter.drawText(4, 14, f'最近一分钟可用内存 · {low:.1f}–{high:.1f} GB')
        path = QPainterPath()
        connected = False
        for index, value in enumerate(self.samples):
            if value is None:
                connected = False
                continue
            point = QPointF(4 + index / 59 * max(1, self.width() - 8),
                            56 - (value - low) / max(0.25, high - low) * 32)
            if connected:
                path.lineTo(point)
            else:
                path.moveTo(point)
            connected = True
        painter.setPen(QPen(QColor(accent_color()), 2))
        painter.drawPath(path)


class MemoryCompanion(QWidget):
    """A non-activating companion window with a persistent reopen button."""

    def __init__(self, owner):
        super().__init__(owner, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.owner = owner
        self.collapsed = False
        self.detached = False
        self.auto_collapse = True
        self._disposed = False
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setObjectName('memoryCompanion')
        set_style(self, lambda: (
            f'QWidget#memoryCompanion {{ background: {current_color("bg1")};'
            f' color: {text_color()}; border: 1px solid {current_color("panel_border")};'
            ' border-radius: 12px; }'))
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(12, 8, 12, 8)
        self.body.setSpacing(6)
        header = QHBoxLayout()
        header.addWidget(QLabel(t('内存守护')))
        header.addStretch()
        self.expand_button = QPushButton(t('展开详情'))
        self.expand_button.setCheckable(True)
        self.expand_button.toggled.connect(self.set_expanded)
        header.addWidget(self.expand_button)
        close_button = QPushButton(t('收起'))
        close_button.clicked.connect(self.collapse)
        header.addWidget(close_button)
        self.body.addLayout(header)
        for button in (self.expand_button, close_button):
            set_style(button, card_btn_style)
        self.details = QWidget()
        self.details_layout = QVBoxLayout(self.details)
        self.details_layout.setContentsMargins(0, 0, 0, 0)
        self.details.hide()
        self.status_button = QPushButton(t('内存守护'))
        set_style(self.status_button, card_btn_style)
        self.status_button.clicked.connect(self.reopen)
        self._status_host = getattr(owner, 'title_bar', None)
        if self._status_host is not None:
            self._status_host.add_status_widget(self.status_button)
        else:
            owner.statusBar().addPermanentWidget(self.status_button)
        owner.installEventFilter(self)

    def setWidget(self, content):
        self.body.addWidget(content)
        self.body.addWidget(self.details)

    def set_expanded(self, expanded):
        self.details.setVisible(expanded)
        self.expand_button.setText(t('收起详情') if expanded else t('展开详情'))
        self.sync_attachment(explicit=True)

    def collapse(self):
        self.collapsed = True
        self.hide()

    def reopen(self):
        self.collapsed = False
        self.detached = False
        self.auto_collapse = False
        self.sync_attachment(explicit=True)

    def sync_attachment(self, explicit=False):
        if self._disposed:
            return
        if self.collapsed or not self.owner.isVisible() or self.owner.isMinimized():
            self.hide()
            return
        screen = self.owner.screen()
        available = screen.availableGeometry()
        main = self.owner.frameGeometry()
        width = min(main.width(), available.width())
        self.setFixedWidth(width)
        height = self.sizeHint().height()
        x = max(available.left(), min(main.left(), available.right() - width + 1))
        y = main.bottom() + 6
        can_attach = not QApplication.platformName().lower().startswith('wayland')
        if not can_attach or y + height > available.bottom() + 1:
            if not explicit and not self.detached:
                self.hide()
                self.status_button.setToolTip(t('点击打开独立内存守护窗口') if not can_attach
                                              else t('下方空间不足，点击打开内存守护窗口'))
                return
            # User explicitly opens the panel when there is no attachment space.
            if self.detached and self.isVisible() and not explicit:
                self.resize(width, height)
                return
            self.detached = True
            x = available.left() + (available.width() - width) // 2
            y = available.top() + (available.height() - height) // 2
        else:
            self.detached = False
            self.status_button.setToolTip(t('查看内存守护'))
        was_visible = self.isVisible()
        self.resize(width, height)
        self.move(x, y)
        self.show()
        if not was_visible:
            from launcher_app.ui.ui_anim import is_animations_enabled, track_animation
            if is_animations_enabled():
                self._reveal = QPropertyAnimation(self, b'windowOpacity', self)
                self._reveal.setDuration(180)
                self._reveal.setStartValue(0.0)
                self._reveal.setEndValue(1.0)
                track_animation(self._reveal)
                self._reveal.start()

    def mousePressEvent(self, event):
        if self.detached and event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.owner and event.type() in (
                QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.WindowStateChange,
                QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Close):
            if event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
                self.hide()
            else:
                QTimer.singleShot(0, self.sync_attachment)
        return super().eventFilter(watched, event)

    def deleteLater(self):
        self._disposed = True
        for timer in self.findChildren(QTimer):
            timer.stop()
        self.owner.removeEventFilter(self)
        if self._status_host is not None:
            self._status_host.remove_status_widget(self.status_button)
        else:
            self.owner.statusBar().removeWidget(self.status_button)
        self.status_button.deleteLater()
        super().deleteLater()


def _offer_memory_actions(owner, plan, version, launch, ports, state_owner):
    if ports.read_settings().get('ignore_memory_launch_advice', False):
        return False
    root = getattr(plan, 'game_root', None)
    history_dir = os.path.join(root, 'versions', plan.instance_id) if root else ports.history_dir(plan.instance_id)
    assessment = assess_launch_memory(
        plan.command, history_dir, plan.game_dir,
        sampler=snapshot, budgeter=automatic_budget, history_reader=history_peak,
        mod_counter=enabled_mod_count, pressure_reader=pressure)
    state, heap, budget, level = assessment.state, assessment.heap, assessment.budget, assessment.level
    if not level:
        return False
    old = state_owner.card
    if old:
        old.hide()
        old.deleteLater()
    dock = MemoryCompanion(owner)
    state_owner.card = dock
    content = QWidget()
    layout = QVBoxLayout(content)
    message = QLabel()
    message.setWordWrap(True)
    layout.addWidget(message)
    advice = '先关掉不用的微信、浏览器窗口，给游戏腾点地方。'
    ai_advice = '先关掉不用的微信、浏览器窗口，或关闭本地 AI，给游戏腾点地方。'
    detail = QLabel(advice)
    detail.setWordWrap(True)
    layout.addWidget(detail)
    exit_check = QCheckBox(t('游戏窗口就绪后退出启动器（游戏内 AI、联机插件等启动器服务也会停止）'))
    exit_check.setVisible(level == 2 and os.name == 'nt')
    dock.details_layout.addWidget(exit_check)
    ignore_check = QCheckBox(t('以后不再显示内存建议'))
    dock.details_layout.addWidget(ignore_check)
    usage_label = QLabel()
    usage_label.setWordWrap(True)
    dock.details_layout.insertWidget(0, usage_label)
    basis_label = QLabel(t('建议游戏堆上限 {v0} GB · {v1}。\n游戏实际占用包含堆内存之外的资源，可能超过设置的堆上限。').format(v0=(budget.get("gb", heap)), v1=(budget.get("basis", "按可用内存估算"))))
    basis_label.setWordWrap(True)
    set_style(basis_label, lambda: f'color: {muted_color()};')
    dock.details_layout.addWidget(basis_label)
    trend = MemoryTrend()
    dock.details_layout.addWidget(trend)
    row = QHBoxLayout()
    layout.addLayout(row)
    controls = []
    relief = None
    stop_ai_control = None
    stable_since = None
    had_game = False
    previous_running = False
    def button(label, action):
        control = QPushButton(label)
        control.clicked.connect(action)
        row.addWidget(control)
        controls.append(control)
        return control
    def refresh_local_ai():
        process = ports.local_ai_process()
        running = process is not None and process.poll() is None
        if stop_ai_control is not None:
            stop_ai_control.setVisible(running)
        if detail.text() in (advice, ai_advice):
            detail.setText(ai_advice if running else advice)
    def refresh():
        nonlocal stable_since, had_game, previous_running
        refresh_local_ai()
        current = snapshot()
        trend.sample(current[1] if current else None)
        current_level = pressure(current[1] if current else None, heap, budget.get('desired_gb', 0))
        dock.setWindowTitle(t('内存建议 · 游戏正在启动（内存可能不足）') if current_level == 2 else t('内存建议 · 游戏正在启动'))
        if relief is not None:
            relief.setVisible(current_level == 2)
        exit_check.setVisible(current_level == 2 and os.name == 'nt')
        if current_level != 2:
            exit_check.setChecked(False)
        message.setText(t('当前可用 {v0:.1f} GB · 本次堆上限 {v1} GB。游戏已开始启动；内存估算可能有偏差，可在此尝试释放内存。').format(v0=(current[1]/GIB), v1=(heap)) if current else t('游戏已开始启动，暂时无法读取可用内存。'))
        process = ports.current_process()
        running = process is not None and process.poll() is None
        had_game = had_game or running
        status = '内存紧张' if current_level == 2 else ('运行中' if running else '正在启动')
        if had_game and not running:
            status = '游戏已退出'
        dock.status_button.setText(t('内存守护 · {v0}').format(v0=(status)))
        def rss(pid):
            try:
                import psutil
                return f'{psutil.Process(pid).memory_info().rss / GIB:.2f} GB'
            except Exception:
                return '暂不可读'
        ai_process = ports.local_ai_process()
        ai_usage = rss(ai_process.pid) if ai_process is not None and ai_process.poll() is None else '未启动'
        system_usage = f'{(current[0] - current[1]) / GIB:.1f} / {current[0] / GIB:.1f} GB' if current else '暂不可读'
        usage_label.setText(t('系统已用 {v0} · 游戏实际占用 {v1}\n启动器 {v2} · 本地 AI {v3}').format(v0=(system_usage), v1=(rss(process.pid) if running else "未运行"), v2=(rss(os.getpid())), v3=(ai_usage)))
        if running and current_level == 0:
            stable_since = stable_since or time.monotonic()
            if dock.auto_collapse and time.monotonic() - stable_since >= 30:
                dock.collapse()
        else:
            stable_since = None
        if previous_running and not running:
            dock.collapse()
        previous_running = running
        dock.sync_attachment()
    def dismiss():
        if ignore_check.isChecked():
            ports.write_setting('ignore_memory_launch_advice', True)
            dock.hide()
            dock.deleteLater()
            state_owner.card = None
        else:
            dock.collapse()
    def exit_when_ready_changed(enabled):
        process = ports.current_process()
        if enabled and process is not None and process.poll() is None:
            state_owner.exit_when_ready(process)
        elif not enabled:
            timer = state_owner.exit_timer
            if timer is not None:
                timer.stop()
    def stop_ai():
        ports.stop_local_ai()
        refresh()
        detail.setText(t('已请求关闭对话使用的本地 AI，游戏会继续启动。'))
    def optimize():
        from launcher_app.core.background_tasks import BackgroundTask
        from launcher_app.runtime.memory_relief import run_elevated
        before = snapshot()
        for control in controls:
            control.setEnabled(False)
        message.setText(t('等待管理员授权并尝试整理内存…'))
        def complete(result):
            for control in controls:
                control.setEnabled(True)
            refresh()
            after = snapshot()
            change = f'；系统可用内存增加 {max(0, after[1] - before[1]) / GIB:.2f} GB' if before and after else ''
            detail.setText(t('已尝试整理内存{v0}。其他程序的活动也会影响这个数值。').format(v0=(change)) if result else t('未完成整理（可能取消了授权），游戏会继续启动。'))
        task = BackgroundTask(lambda current: run_elevated(), dock)
        dock._task = task
        task.succeeded.connect(complete)
        task.failed.connect(lambda error: complete(False))
        task.cancelled_signal.connect(lambda: complete(False))
        task.start()
    exit_check.toggled.connect(exit_when_ready_changed)
    stop_ai_control = button('关闭本地 AI', stop_ai)
    button('重新检测', refresh)
    if os.name == 'nt':
        relief = button('尝试整理内存', optimize)
        relief.setToolTip(t('需要管理员授权。缩减当前用户会话中程序的工作集，不关闭应用；切回其他应用可能暂时变慢。'))
    button('忽略', dismiss)
    dock.setWidget(content)
    refresh()
    local_ai_timer = QTimer(dock)
    local_ai_timer.setInterval(1000)
    local_ai_timer.timeout.connect(refresh)
    local_ai_timer.start()
    dock.sync_attachment()
    # Do not make the user acknowledge an estimate before launching. Keep the
    # non-modal card available for optional memory relief while Minecraft starts.
    QTimer.singleShot(0, lambda: launch(plan, version, False))
    return True



@dataclass
class MemoryLaunchPorts:
    read_settings: Callable
    write_setting: Callable
    current_process: Callable
    local_ai_process: Callable
    stop_local_ai: Callable
    history_dir: Callable


class MemoryLaunchController:
    def __init__(self, parent, ports):
        self.parent, self.ports = parent, ports
        self.card = None
        self.exit_timer = None

    def offer(self, plan, version, launch):
        return _offer_memory_actions(self.parent, plan, version, launch, self.ports, self)

    def exit_when_ready(self, process):
        if self.exit_timer is not None:
            self.exit_timer.stop()
        timer = QTimer(self.parent)
        timer.setInterval(1000)
        self.exit_timer = timer
        tracker = WindowReadinessTracker(time.monotonic())
        self.parent.statusBar().showMessage('等待游戏窗口就绪后退出启动器；游戏自己的 logs/latest.log 会保留。')
        def poll():
            running = process.poll() is None
            outcome = tracker.observe(now=time.monotonic(), running=running,
                                      visible=bool(running and visible_game_window(process.pid)))
            if outcome is WindowReadiness.WAIT:
                return
            timer.stop()
            if outcome is WindowReadiness.TIMED_OUT:
                self.parent.statusBar().showMessage('暂未确认游戏窗口就绪，已保留启动器，请检查游戏启动情况。')
            elif outcome is WindowReadiness.READY and self.parent.close():
                QApplication.quit()
        timer.timeout.connect(poll)
        timer.start()

    def close(self):
        if self.exit_timer is not None:
            self.exit_timer.stop()
        if self.card is not None:
            self.card.hide()
            self.card.deleteLater()
            self.card = None


def _legacy_controller(owner):
    """Old entry points adapt once; new frontends provide explicit ports."""
    controller = getattr(owner, '_memory_launch_controller', None)
    if controller is None:
        from settings import load_settings, update_setting
        import paths
        def local_process():
            engine = getattr(getattr(owner, 'ai_dock', None), '_local_engine', None)
            return getattr(engine, 'proc', None)
        controller = MemoryLaunchController(owner, MemoryLaunchPorts(
            read_settings=load_settings, write_setting=update_setting,
            current_process=lambda: getattr(owner, 'game_process', None), local_ai_process=local_process,
            stop_local_ai=lambda: owner.ai_dock.stop_local_engine(),
            history_dir=lambda instance: os.path.join(paths.GAME_DIR, 'versions', instance)))
        owner._memory_launch_controller = controller
    return controller


def offer_memory_actions(owner, plan, version, launch):
    controller = _legacy_controller(owner)
    result = controller.offer(plan, version, launch)
    owner._memory_launch_card = controller.card
    return result


def exit_when_ready(owner, process):
    controller = _legacy_controller(owner)
    controller.exit_when_ready(process)
    owner._memory_exit_timer = controller.exit_timer
