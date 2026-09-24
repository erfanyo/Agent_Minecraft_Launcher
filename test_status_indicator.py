import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QWidget

from download_indicator import DownloadDetailWidget, DownloadIndicator, _paint_color
from ui_tokens import set_theme_mode, set_wallpaper_active, current_token


def test_status_ball_states_and_drag():
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(300, 200)
    parent.show()
    ball = DownloadIndicator(parent)
    ball.move(230, 130)
    ball.show()
    assert ball._waiting
    ball.set_progress(1, 10)
    assert not ball._waiting and not ball._completed
    ball.set_completed()
    assert ball._completed
    ball.set_failed()
    assert ball._failed and not ball._completed
    ball.set_waiting()
    assert ball._waiting and not ball._failed

    QTest.mousePress(ball, Qt.MouseButton.LeftButton, pos=ball.rect().center())
    QTest.mouseMove(ball, ball.rect().center() + ball.rect().topLeft() + ball.rect().center())
    QTest.mouseRelease(ball, Qt.MouseButton.LeftButton, pos=ball.rect().center())
    assert ball.parentWidget() is parent
    app.processEvents()


def test_status_details_has_separate_logs():
    app = QApplication.instance() or QApplication([])
    launcher_log = QPlainTextEdit()
    details = DownloadDetailWidget(["下载测试"], launcher_log_view=launcher_log)
    assert details.tabs.count() == 2
    assert details.tabs.tabText(0) == "下载任务"
    assert details.tabs.tabText(1) == "启动器日志"
    assert details.tabs.widget(1) is launcher_log
    details.close()
    app.processEvents()


def test_wallpaper_button_color_is_not_black_in_light_mode():
    app = QApplication.instance() or QApplication([])
    set_theme_mode("light")
    set_wallpaper_active(True)
    try:
        color = _paint_color(current_token("btn_bg"))
        assert color.isValid()
        assert color.red() > 220 and color.green() > 220 and color.blue() > 220
    finally:
        set_wallpaper_active(False)
        set_theme_mode("system")
    app.processEvents()
