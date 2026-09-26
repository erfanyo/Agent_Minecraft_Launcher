# -*- coding: utf-8 -*-
"""Shared theme-aware switch and setting row for persistent on/off options."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui_style import accent_color, current_color, muted_color, panel_style, set_style, text_color


class ToggleSwitch(QAbstractButton):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(bool(checked))
        self.setFixedSize(46, 24)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QColor(accent_color() if self.isChecked() else current_color('btn_disabled_bg'))
        if not self.isEnabled():
            track.setAlpha(110)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(0, 0, 46, 24, 12, 12)
        painter.setBrush(QColor('#ffffff'))
        painter.drawEllipse(25 if self.isChecked() else 5, 4, 16, 16)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(current_color('focus')), 2))
            painter.drawRoundedRect(1, 1, 44, 22, 11, 11)
        painter.end()


def setting_switch_row(label: str, switch: ToggleSwitch, description: str = '') -> QWidget:
    """Use the same card rhythm as plugin switches, with the control on the right."""
    row = QWidget()
    row.setObjectName('settingSwitchRow')
    row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    set_style(row, lambda: f'QWidget#settingSwitchRow {{ {panel_style()} }}')
    switch.setAccessibleName(label)
    content = QHBoxLayout(row)
    content.setContentsMargins(12, 8, 12, 8)
    content.setSpacing(10)
    labels = QVBoxLayout()
    labels.setSpacing(2)
    title = QLabel(label)
    title.setWordWrap(True)
    title.setBuddy(switch)
    set_style(title, lambda: f'font-weight: 600; color: {text_color()};')
    labels.addWidget(title)
    if description:
        detail = QLabel(description)
        detail.setWordWrap(True)
        set_style(detail, lambda: f'color: {muted_color()}; font-size: 11px;')
        labels.addWidget(detail)
    content.addLayout(labels, 1)
    content.addWidget(switch, 0, Qt.AlignmentFlag.AlignVCenter)
    return row
