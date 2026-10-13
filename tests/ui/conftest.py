"""Isolated Qt scenarios: no real accounts, downloads, games or config writes."""
import os
from pathlib import Path
import sys
import json
import re

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QFont, QFontDatabase
from download_indicator import DownloadIndicator
from task_center import TaskCenter
from ui_anim import set_animations_enabled
from ui_tokens import set_theme_mode, theme_mode, set_wallpaper_active
from ui_style import clear_registered_styles

_TEST_FONT_FAMILY = None


def pytest_addoption(parser):
    parser.addoption('--ui-artifacts', default='.tmp/ui-test-artifacts',
                     help='Directory for failed-widget screenshots and task state')


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if not report.failed:
        return
    qapp = item.funcargs.get('qapp')
    if qapp is None:
        return
    directory = Path(item.config.getoption('--ui-artifacts')) / re.sub(r'[^\w.-]+', '_', item.nodeid)
    directory.mkdir(parents=True, exist_ok=True)
    state = {'test': item.nodeid, 'phase': report.when, 'platform': qapp.platformName(), 'windows': []}
    for index, widget in enumerate(qapp.topLevelWidgets()):
        try:
            if not widget.isVisible():
                continue
            name = widget.objectName() or f'window-{index}'
            filename = re.sub(r'[^\w.-]+', '_', name) + '.png'
            widget.grab().save(str(directory / filename))
            state['windows'].append({'name': name, 'width': widget.width(), 'height': widget.height(),
                                     'devicePixelRatio': widget.devicePixelRatioF(), 'image': filename})
        except RuntimeError:
            pass
    center = item.funcargs.get('hub')
    if center:
        state['tasks'] = [{'id': task.id, 'title': task.title, 'state': task.state,
                           'done': task.done, 'total': task.total} for task in center.tasks.values()]
        state['pendingConfirmations'] = len(center._requests)
    (directory / 'state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


@pytest.fixture(autouse=True)
def isolated_theme(qapp, monkeypatch):
    global _TEST_FONT_FAMILY
    monkeypatch.setattr('ui_notifications.notifications_enabled', lambda: True)
    previous = theme_mode()
    previous_font = qapp.font()
    # Offscreen Windows Qt has no platform font fallback. Load a system CJK
    # font into this process only so artifacts contain readable Chinese text.
    font_paths = (Path('C:/Windows/Fonts/msyh.ttc'),
                  Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
                  Path('/System/Library/Fonts/PingFang.ttc'))
    if _TEST_FONT_FAMILY is None:
        _TEST_FONT_FAMILY = ''
        for path in font_paths:
            if path.is_file():
                font_id = QFontDatabase.addApplicationFont(str(path))
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    _TEST_FONT_FAMILY = families[0]
                    break
    if _TEST_FONT_FAMILY:
        qapp.setFont(QFont(_TEST_FONT_FAMILY, 10))
    set_theme_mode('light')
    set_wallpaper_active(False)
    set_animations_enabled(False)
    yield
    set_animations_enabled(True)
    set_theme_mode(previous)
    set_wallpaper_active(False)
    qapp.setFont(previous_font)
    clear_registered_styles()


@pytest.fixture
def hub(qtbot, qapp):
    owner = QWidget()
    owner.resize(900, 700)
    qtbot.addWidget(owner)
    ball = DownloadIndicator(owner)
    ball.setObjectName('status_ball')
    ball.move(830, 630)
    owner.show()
    ball.show()
    center = TaskCenter(ball, owner)
    qtbot.addWidget(center.details)
    qtbot.addWidget(center.card)
    ball.clicked.connect(center.present)
    yield center
    center.shutdown()
    qapp.removeEventFilter(center)
    qapp.aboutToQuit.disconnect(center.shutdown)
    if getattr(qapp, '_amcl_task_center', None) is center:
        del qapp._amcl_task_center
    center.deleteLater()
