"""Independent real-window animation comparison; never imports AMCL settings.

Run without arguments for two live windows, or --benchmark for sequential runs.
The counters are paint/frameSwapped callbacks, NOT monitor presentation FPS.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, QUrl, QPoint, QObject, Slot
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QGridLayout,
                               QLabel, QPushButton, QGraphicsOpacityEffect)
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / '.tmp' / 'animation-compare'


class Samples(QObject):
    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        self.started = time.perf_counter()
        self.frames, self.costs, self.heartbeats = [], [], []
        self.last_heartbeat = None

    @Slot()
    def frame(self):
        now = time.perf_counter()
        if now - self.started >= 2:
            self.frames.append(now)

    def heartbeat(self):
        now = time.perf_counter()
        if now - self.started >= 2 and self.last_heartbeat is not None:
            self.heartbeats.append((now - self.last_heartbeat) * 1000)
        self.last_heartbeat = now

    def result(self):
        intervals = [(b-a)*1000 for a, b in zip(self.frames, self.frames[1:])]
        def percentile(items, p):
            return round(sorted(items)[min(len(items)-1, int((len(items)-1)*p))], 2) if items else None
        return {
            'mode': self.mode,
            'callback': 'opacity effect draw completion' if self.mode == 'widgets' else 'QQuickWindow.frameSwapped (GUI delivery)',
            'note': 'Not presented FPS. Different callback boundaries; compare visual smoothness and GUI stalls too.',
            'samples': len(self.frames),
            'callback_rate_hz': round(1000 / statistics.mean(intervals), 1) if intervals else None,
            'interval_median_ms': percentile(intervals, .5),
            'interval_p95_ms': percentile(intervals, .95),
            'interval_max_ms': round(max(intervals), 2) if intervals else None,
            'gui_timer_interval_p95_ms': percentile(self.heartbeats, .95),
            'gui_timer_interval_max_ms': round(max(self.heartbeats), 2) if self.heartbeats else None,
            'effect_draw_median_ms': percentile(self.costs, .5),
        }


class MeasuredOpacity(QGraphicsOpacityEffect):
    def __init__(self, samples, parent):
        super().__init__(parent)
        self.samples = samples

    def draw(self, painter):
        start = time.perf_counter()
        super().draw(painter)
        if start - self.samples.started >= 2:
            self.samples.costs.append((time.perf_counter() - start)*1000)
        self.samples.frame()


def widgets_window(samples):
    window = QWidget()
    window.setWindowTitle('AMCL · Qt Widgets 对比演示')
    window.resize(770, 760)
    window.setStyleSheet('QWidget {background:#18252e; color:#e3edf3; font-size:13px;} '
                         'QPushButton {background:#304b59; border:1px solid #52717e; border-radius:5px; padding:4px;} '
                         'QPushButton:hover {background:#406778;} QPushButton:pressed {background:#244451;}')
    layout = QVBoxLayout(window)
    heading = QLabel('Qt Widgets · 整页实时透明度\n120 张资源卡片 / 1.8 秒往返淡入淡出')
    heading.setStyleSheet('font-size:17px; font-weight:600;')
    layout.addWidget(heading)
    status = QLabel('采样中…前 2 秒预热；可以点击卡片试手感。')
    status.setWordWrap(True)
    layout.addWidget(status)
    lane = QWidget()
    lane.setFixedHeight(8)
    layout.addWidget(lane)
    marker = QWidget(lane)
    marker.setGeometry(0, 1, 60, 4)
    marker.setStyleSheet('background:#61d4c2; border-radius:2px;')
    motion = QPropertyAnimation(marker, b'pos', window)
    motion.setDuration(1800)
    motion.setStartValue(QPoint(0, 1))
    motion.setKeyValueAt(.5, QPoint(600, 1))
    motion.setEndValue(QPoint(0, 1))
    motion.setLoopCount(-1)
    motion.start()
    window.motion = motion
    page = QWidget()
    grid = QGridLayout(page)
    grid.setSpacing(5)
    for index in range(120):
        button = QPushButton(f'Resource {index+1:03d}')
        button.setMinimumSize(0, 0)
        button.setFixedHeight(26)
        button.clicked.connect(lambda checked=False, i=index: status.setText(f'收到点击：Resource {i+1:03d}'))
        grid.addWidget(button, index//6, index%6)
    layout.addWidget(page, 1)
    effect = MeasuredOpacity(samples, page)
    page.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b'opacity', window)
    animation.setDuration(1800)
    animation.setStartValue(.45)
    animation.setKeyValueAt(.5, 1.)
    animation.setEndValue(.45)
    animation.setEasingCurve(QEasingCurve.Type.Linear)
    animation.setLoopCount(-1)
    animation.start()
    window.animation = animation
    return window, status


def run_child(args):
    app = QApplication(sys.argv) if args.mode == 'widgets' else QGuiApplication(sys.argv)
    samples = Samples(args.mode)
    engine = None
    if args.mode == 'widgets':
        window, status = widgets_window(samples)
    else:
        engine = QQmlApplicationEngine()
        engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name('QuickDemo.qml'))))
        if not engine.rootObjects():
            return 1
        window = engine.rootObjects()[0]
        status = None
        window.frameSwapped.connect(samples.frame)
    area = app.primaryScreen().availableGeometry()
    window.setPosition(area.x() + (area.width()//2 if args.mode == 'quick' else 0), area.y()+30) if args.mode == 'quick' else window.move(area.x(), area.y()+30)
    window.show()
    timer = QTimer()
    timer.setInterval(8)
    timer.timeout.connect(samples.heartbeat)
    timer.start()

    def finish():
        result = samples.result()
        result['screen_refresh_hz'] = window.screen().refreshRate()
        result['device_pixel_ratio'] = window.devicePixelRatio()
        if args.mode == 'quick':
            result['graphics_api'] = str(window.rendererInterface().graphicsApi())
            window.grabWindow().save(str(OUTPUT / 'quick.png'))
        else:
            window.grab().save(str(OUTPUT / 'widgets.png'))
        (OUTPUT / f'{args.mode}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        text = f"动画回调 {result['callback_rate_hz']} 次/秒 · 间隔 P95 {result['interval_p95_ms']} ms"
        if status:
            status.setText(text + '\n非屏幕实测 FPS；本窗口是整页实时透明度基线。')
        else:
            window.setProperty('resultText', text + '\n非屏幕实测 FPS；硬件渲染方式见报告。')
        print(json.dumps(result), flush=True)
        if args.quit:
            app.quit()

    QTimer.singleShot(int(args.duration*1000), finish)
    return app.exec()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['widgets', 'quick'])
    parser.add_argument('--benchmark', action='store_true')
    parser.add_argument('--duration', type=float, default=12)
    parser.add_argument('--quit', action='store_true')
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.mode:
        return run_child(args)
    command = [sys.executable, str(Path(__file__).resolve())]
    if args.benchmark:
        results = []
        for mode in ('widgets', 'quick'):
            subprocess.run(command + ['--mode', mode, '--duration', str(args.duration), '--quit'], check=True)
            results.append(json.loads((OUTPUT / f'{mode}.json').read_text(encoding='utf-8')))
        (OUTPUT / 'benchmark.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print('Reports: ' + str(OUTPUT))
    else:
        # Separate processes prevent Widgets work from blocking QML's GUI thread.
        children = [subprocess.Popen(command + ['--mode', mode]) for mode in ('widgets', 'quick')]
        for child in children:
            child.wait()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
