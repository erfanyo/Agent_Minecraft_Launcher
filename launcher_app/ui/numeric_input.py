"""Compact settings numbers: page scrolling never changes saved values."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSpinBox


class SettingsSpinBox(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(168)
        self.setMinimumHeight(34)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        event.ignore()
