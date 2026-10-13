"""Streaming log viewer with browser-style keyword search."""

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTextEdit, QWidget,
)


class SearchableLogView(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self._matches = []
        self._current = -1
        self._generation = 0
        self._scanning = False
        self.search_bar = self._bar = QWidget(parent)
        row = QHBoxLayout(self._bar)
        row.setContentsMargins(6, 3, 6, 3)
        self._input = QLineEdit(self._bar)
        self._input.setPlaceholderText('搜索服务端日志关键词')
        self._count = QLabel(self._bar)
        self._previous = QPushButton('上一个', self._bar)
        self._next = QPushButton('下一个', self._bar)
        self._close = QPushButton('清除', self._bar)
        row.addWidget(self._input, 1)
        for widget in (self._count, self._previous, self._next, self._close):
            row.addWidget(widget)
        self._close.clicked.connect(self.close_search)
        self._previous.clicked.connect(lambda: self._step(-1))
        self._next.clicked.connect(lambda: self._step(1))
        self._input.textChanged.connect(self._query_changed)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self._scan)
        self.textChanged.connect(self._schedule_scan)
        self._highlight()

    @property
    def search_active(self):
        return bool(self._input.text())

    def close_search(self):
        self._refresh_timer.stop()
        self._input.clear()
        self.setExtraSelections([])
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)
        self.setFocus()

    def _query_changed(self):
        self._generation += 1
        self._scanning = False
        self._matches = []
        self._current = -1
        self.setExtraSelections([])
        self._previous.setEnabled(False)
        self._next.setEnabled(False)
        if self.search_active:
            self._count.setText('搜索中…')
            self._refresh_timer.start()
        else:
            self._refresh_timer.stop()
            self._highlight()

    def _schedule_scan(self):
        self._generation += 1
        self._scanning = False
        if self.search_active and not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _scan(self):
        query = self._input.text()
        if not query:
            return
        anchor = (QTextCursor(self._matches[self._current])
                  if 0 <= self._current < len(self._matches) else None)
        generation = self._generation
        self._scanning = True
        self._previous.setEnabled(False)
        self._next.setEnabled(False)
        matches = []
        cursor = QTextCursor(self.document())

        def batch():
            nonlocal cursor
            if generation != self._generation:
                return
            for _ in range(300):
                cursor = self.document().find(query, cursor, QTextDocument.FindFlag(0))
                if cursor.isNull():
                    break
                matches.append(QTextCursor(cursor))
            if not cursor.isNull():
                QTimer.singleShot(0, batch)
                return
            self._scanning = False
            self._matches = matches
            self._current = 0 if matches else -1
            if anchor is not None and anchor.hasSelection():
                for index, match in enumerate(matches):
                    if match.selectionStart() == anchor.selectionStart():
                        self._current = index
                        break
            elif matches:
                self.setTextCursor(matches[0])
                self.ensureCursorVisible()
            self._highlight()

        batch()

    def _step(self, direction):
        if not self.search_active or not self._matches or self._scanning:
            return
        self._current = (self._current + direction) % len(self._matches)
        self.setTextCursor(self._matches[self._current])
        self.ensureCursorVisible()
        self._highlight()

    def _highlight(self):
        selections = []
        # Bound repaint cost for common keywords; navigation still covers every hit.
        indices = set(range(min(len(self._matches), 1000)))
        if self._current >= 0:
            indices.add(self._current)
        for index in sorted(indices):
            cursor = self._matches[index]
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format.setBackground(QColor('#f5a623' if index == self._current else '#ffe082'))
            selection.format.setForeground(QColor('#202020'))
            selections.append(selection)
        self.setExtraSelections(selections)
        total = len(self._matches)
        self._count.setText(f'{self._current + 1} / {total}' if total else
                            ('无匹配' if self._input.text() else '输入关键词'))
        self._count.setToolTip('匹配较多时仅高亮前 1000 个及当前结果；可切换全部结果。'
                               if total > 1000 else '')
        self._previous.setEnabled(bool(total))
        self._next.setEnabled(bool(total))

    def appendPlainText(self, text):
        scrollbar = self.verticalScrollBar()
        position = scrollbar.value()
        cursor = self.textCursor()
        super().appendPlainText(text)
        if self.search_active:
            self.setTextCursor(cursor)
            scrollbar.setValue(position)
