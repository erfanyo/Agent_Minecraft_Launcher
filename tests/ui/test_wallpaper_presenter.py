"""Check shared-canvas behavior across settings, focus and dock layouts."""
import pytest
from PySide6.QtGui import QPixmap, QColor
from launcher_app.ui.ui_background import BackgroundWidget
from launcher_app.ui.wallpaper_presenter import present_wallpaper

pytestmark = pytest.mark.ui


def source():
    pixmap = QPixmap(200, 100)
    pixmap.fill(QColor('red'))
    return pixmap


def test_normal_canvas_covers_dock_and_preserves_source(qtbot):
    view = BackgroundWidget()
    qtbot.addWidget(view)
    view.resize(200, 100)
    original = source()
    canvas = present_wallpaper(original, .4, background=view, dock_width=100)
    assert canvas.pixmap.width() >= 300
    assert canvas.pixmap.height() >= 100
    assert view._shared is canvas.pixmap
    assert original.size().width() == 200


def test_settings_updates_independently_of_hidden_main_canvas(qtbot):
    background, settings = BackgroundWidget(), BackgroundWidget()
    for view in (background, settings):
        qtbot.addWidget(view)
    old = present_wallpaper(source(), .3, background=background)
    result = present_wallpaper(source(), .5, background=background, settings_surface=settings)
    assert result is None
    assert background._shared is old.pixmap
    assert settings.enabled
    assert settings._mask == .5


def test_focus_canvas_uses_window_width_not_sidebar_width(qtbot):
    sidebar = BackgroundWidget()
    qtbot.addWidget(sidebar)
    sidebar.resize(80, 200)
    canvas = present_wallpaper(source(), .2, focus_surface=sidebar, focus_width=700, dock_width=500)
    assert canvas.pixmap.width() >= 700
    assert sidebar._shared is canvas.pixmap
    # Dock width is ignored in focus mode: no extra 500-pixel canvas.
    assert canvas.pixmap.width() < 1200


def test_disabling_wallpaper_clears_online_and_focus(qtbot):
    sidebar, online = BackgroundWidget(), BackgroundWidget()
    for view in (sidebar, online):
        qtbot.addWidget(view)
    present_wallpaper(source(), .2, focus_surface=sidebar, focus_width=300, online=online)
    canvas = present_wallpaper(None, .2, focus_surface=sidebar, online=online)
    assert canvas.pixmap is None
    assert not sidebar.enabled
    assert not online.enabled
