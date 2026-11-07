"""Bind wallpaper assets to explicit surfaces, without owning a main window.

Surfaces implement set_wallpaper / set_shared_view / clear. A future frontend
can use its own presenter while reusing the asset provider's input contract.
"""
from dataclasses import dataclass
from PySide6.QtCore import QSize
from PySide6.QtGui import QPixmap
from launcher_app.ui.wallpaper_assets import prepare_shared_wallpaper


@dataclass(frozen=True)
class WallpaperCanvas:
    pixmap: QPixmap | None = None
    x: int = 0
    y: int = 0


def present_wallpaper(source, mask, *, background=None, online=None,
                      settings_surface=None, focus_surface=None,
                      focus_width=0, dock_width=0):
    """Return shared canvas, or None when settings leaves the old canvas intact."""
    if online is not None:
        online.set_wallpaper(source, mask)
    if settings_surface is not None:
        settings_surface.set_wallpaper(source, mask)
        return None
    surface = focus_surface if focus_surface is not None else background
    if source is None or surface is None:
        if surface is not None:
            surface.clear()
        if online is not None:
            online.clear()
        return WallpaperCanvas()
    if focus_surface is not None:
        size = QSize(max(1, focus_width), max(1, surface.height()))
        dock_width = 0
    else:
        size = surface.size()
    scaled, x, y = prepare_shared_wallpaper(source, size, dock_width)
    if scaled is not None or focus_surface is not None:
        surface.set_shared_view(scaled, x, y, mask)
    return WallpaperCanvas(scaled, x, y)
