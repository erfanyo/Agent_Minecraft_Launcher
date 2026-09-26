"""Non-modal launch memory advice. The game starts while the advice stays available."""
import os
import re
import time
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox
from memory_policy import snapshot, automatic_budget, history_peak, enabled_mod_count, GIB
from memory_relief import pressure, visible_game_window


def offer_memory_actions(owner, plan, version, launch):
    from settings import load_settings, update_setting
    if load_settings().get('ignore_memory_launch_advice', False):
        return False
    state = snapshot()
    heap = next((int(m[1]) for arg in plan.command if (m := re.fullmatch(r'-Xmx(\d+)G', arg))), 2)
    import paths
    budget = automatic_budget(history_peak_bytes=history_peak(os.path.join(paths.GAME_DIR, 'versions', plan.instance_id)),
                              mods=enabled_mod_count(plan.game_dir))
    level = pressure(state[1] if state else None, heap, budget.get('desired_gb', 0))
    if not level:
        return False
    old = getattr(owner, '_memory_launch_card', None)
    if old:
        old.hide()
        old.deleteLater()
    dock = QDockWidget('内存建议 · 游戏正在启动' if level == 1 else '内存建议 · 游戏正在启动（内存可能不足）', owner)
    dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
    owner._memory_launch_card = dock
    content = QWidget()
    layout = QVBoxLayout(content)
    message = QLabel()
    message.setWordWrap(True)
    layout.addWidget(message)
    detail = QLabel('先关掉不用的微信、浏览器窗口，或关闭本地 AI，给游戏腾点地方。')
    detail.setWordWrap(True)
    layout.addWidget(detail)
    exit_check = QCheckBox('游戏窗口就绪后退出启动器（游戏内 AI、联机插件等启动器服务也会停止）')
    exit_check.setVisible(level == 2 and os.name == 'nt')
    layout.addWidget(exit_check)
    ignore_check = QCheckBox('以后不再显示内存建议')
    layout.addWidget(ignore_check)
    row = QHBoxLayout()
    layout.addLayout(row)
    controls = []
    relief = None
    def button(label, action):
        control = QPushButton(label)
        control.clicked.connect(action)
        row.addWidget(control)
        controls.append(control)
        return control
    def refresh():
        current = snapshot()
        current_level = pressure(current[1] if current else None, heap, budget.get('desired_gb', 0))
        dock.setWindowTitle('内存建议 · 游戏正在启动（内存可能不足）' if current_level == 2 else '内存建议 · 游戏正在启动')
        if relief is not None:
            relief.setVisible(current_level == 2)
        exit_check.setVisible(current_level == 2 and os.name == 'nt')
        if current_level != 2:
            exit_check.setChecked(False)
        message.setText(f'当前可用 {current[1]/GIB:.1f} GB · 本次堆上限 {heap} GB。游戏已开始启动；内存估算可能有偏差，可在此尝试释放内存。' if current else '游戏已开始启动，暂时无法读取可用内存。')
    def dismiss():
        if ignore_check.isChecked():
            update_setting('ignore_memory_launch_advice', True)
        dock.hide()
        dock.deleteLater()
        owner._memory_launch_card = None
    def exit_when_ready_changed(enabled):
        process = getattr(owner, 'game_process', None)
        if enabled and process is not None and process.poll() is None:
            exit_when_ready(owner, process)
        elif not enabled:
            timer = getattr(owner, '_memory_exit_timer', None)
            if timer is not None:
                timer.stop()
    def stop_ai():
        owner.ai_dock.stop_local_engine()
        refresh()
        detail.setText('已请求关闭对话使用的本地 AI。检查剩余内存后，可以点击继续启动。')
    def optimize():
        from background_tasks import BackgroundTask
        from memory_relief import run_elevated
        for control in controls:
            control.setEnabled(False)
        message.setText('等待管理员授权并尝试整理内存…')
        def complete(result):
            for control in controls:
                control.setEnabled(True)
            refresh()
            detail.setText('已尝试整理。其他软件再次使用时可能重新占用内存；可点击继续启动。' if result else '未完成整理（可能取消了授权）。可以继续启动，或返回调整。')
        task = BackgroundTask(lambda current: run_elevated(), dock)
        dock._task = task
        task.succeeded.connect(complete)
        task.failed.connect(lambda error: complete(False))
        task.cancelled_signal.connect(lambda: complete(False))
        task.start()
    exit_check.toggled.connect(exit_when_ready_changed)
    button('关闭本地 AI', stop_ai)
    button('重新检测', refresh)
    if os.name == 'nt':
        relief = button('尝试整理内存 🛡', optimize)
        relief.setToolTip('需要管理员授权。缩减当前用户会话中程序的工作集，不关闭应用；切回其他应用可能暂时变慢。')
    button('忽略', dismiss)
    dock.setWidget(content)
    owner.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
    refresh()
    dock.show()
    # Do not make the user acknowledge an estimate before launching. Keep the
    # non-modal card available for optional memory relief while Minecraft starts.
    QTimer.singleShot(0, lambda: launch(plan, version, False))
    return True


def exit_when_ready(owner, process):
    timer = QTimer(owner)
    timer.setInterval(1000)
    owner._memory_exit_timer = timer
    state = {'start': time.monotonic(), 'visible_since': None}
    owner.statusBar().showMessage('等待游戏窗口就绪后退出启动器；游戏自己的 logs/latest.log 会保留。')
    def poll():
        if process.poll() is not None:
            timer.stop()
            return
        now = time.monotonic()
        if now - state['start'] > 180:
            timer.stop()
            owner.statusBar().showMessage('暂未确认游戏窗口就绪，已保留启动器，请检查游戏启动情况。')
            return
        if not visible_game_window(process.pid):
            state['visible_since'] = None
            return
        if state['visible_since'] is None:
            state['visible_since'] = now
        if now - state['visible_since'] >= 10:
            timer.stop()
            if owner.close():
                QApplication.quit()
    timer.timeout.connect(poll)
    timer.start()
