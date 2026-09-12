"""Keyboard-accessible wallpaper picker and local-file drop target."""
import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton


class WallpaperDropButton(QPushButton):
    fileDropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__('点击选择图片，或把图片拖到这里', parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(90)
        self.setToolTip('支持 PNG、JPG、BMP、WebP；一次选择一张本机图片')

    @staticmethod
    def local_image(mime):
        urls = mime.urls() if mime.hasUrls() else []
        if len(urls) != 1 or not urls[0].isLocalFile():
            return ''
        path = urls[0].toLocalFile()
        if os.path.isfile(path) and os.path.splitext(path)[1].lower() in {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}:
            return path
        return ''

    def dragEnterEvent(self, event):
        if self.isEnabled() and self.local_image(event.mimeData()):
            self.setDown(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.isEnabled() and self.local_image(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setDown(False)
        event.accept()

    def dropEvent(self, event):
        self.setDown(False)
        path = self.local_image(event.mimeData())
        if self.isEnabled() and path:
            event.acceptProposedAction()
            self.fileDropped.emit(path)
        else:
            event.ignore()
