import os
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QListWidget


class InstanceDropList(QListWidget):
    folders_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setToolTip('可以拖入已有实例文件夹，复制导入并保留原文件')

    @staticmethod
    def folders(event):
        urls = event.mimeData().urls()
        if not urls or not all(u.isLocalFile() and os.path.isdir(u.toLocalFile()) for u in urls):
            return []
        return list(dict.fromkeys(u.toLocalFile() for u in urls))

    def dragEnterEvent(self, event):
        if self.folders(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        folders = self.folders(event)
        if folders:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.folders_dropped.emit(folders)
        else:
            event.ignore()
