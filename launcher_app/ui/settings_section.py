"""Theme-aware settings chapters with a distinct heading and quiet border."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from launcher_app.ui.ui_style import current_color, set_style


class SettingsSection(QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName('settingsChapter')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        set_style(self, lambda: 'QWidget#settingsChapter {'
                  f'border: 1px solid {current_color("panel_border")}; border-radius: 10px;'
                  f' background: {current_color("panel_bg")}; }}')
        self.content = QVBoxLayout(self)
        self.content.setContentsMargins(16, 14, 16, 16)
        self.content.setSpacing(12)
        self.heading = QLabel(title)
        font = self.heading.font()
        font.setBold(True)
        font.setPointSizeF(max(12, font.pointSizeF() + 2))
        self.heading.setFont(font)
        self.heading.setWordWrap(True)
        self.content.addWidget(self.heading)
