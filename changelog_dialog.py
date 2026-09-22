# -*- coding: utf-8 -*-
"""「更新日志」对话框:从「首页标签页」搬到「设置 → 系统」。

搬家的原因:更新日志是低频的「我想知道这版改了什么」需求,却占着首页一个平级标签页,
把「版本 / 服务端」挤窄。放到「设置 → 系统」里紧挨「检查更新」更符合使用场景——
两个都是「关于启动器自身」的动作。

拉取仍然走 :mod:`changelog`(GitHub 优先、失败回落本地),并在后台线程执行,
不在主线程里等网络。
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QTextBrowser, QVBoxLayout)

from changelog import changelog_html, load_changelog
from ui_style import card_btn_style, muted_color, set_style, text_color


class _ChangelogWorker(QThread):
    loaded = Signal(list)
    failed = Signal(str)

    def run(self):
        try:
            entries = load_changelog()
        except Exception as error:            # 网络异常不应让窗口崩
            self.failed.emit(str(error))
            return
        if entries:
            self.loaded.emit(entries)
        else:
            self.failed.emit('empty')


class ChangelogDialog(QDialog):
    """只读展示更新日志,可手动刷新。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self.setWindowTitle('更新日志')
        self.resize(720, 560)
        self._build()
        self.reload()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel('更新日志')
        title.setStyleSheet(f'font-weight:bold; font-size:15px; color:{text_color()};')
        self.status = QLabel('')
        self.status.setStyleSheet(f'color:{muted_color()};')
        self.status.setWordWrap(True)
        self.refresh_btn = QPushButton('刷新')
        set_style(self.refresh_btn, card_btn_style)
        self.refresh_btn.setMinimumHeight(30)
        self.refresh_btn.clicked.connect(self.reload)
        close_btn = QPushButton('关闭')
        set_style(close_btn, card_btn_style)
        close_btn.setMinimumHeight(30)
        close_btn.clicked.connect(self.accept)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.refresh_btn)
        header.addWidget(close_btn)
        layout.addLayout(header)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setStyleSheet(
            f'QTextBrowser {{ background: transparent; border: none; color: {text_color()}; }}')
        layout.addWidget(self.view, 1)
        layout.addWidget(self.status)

    def reload(self):
        """后台重新拉取;期间禁用刷新按钮避免并发拉取。"""
        if self._worker is not None and self._worker.isRunning():
            return
        self.status.setText('正在从 GitHub 拉取更新日志…')
        self.view.setHtml(
            f"<p style='color:{muted_color()}'>🔄 正在拉取…</p>")
        self.refresh_btn.setEnabled(False)
        self._worker = _ChangelogWorker(self)
        self._worker.loaded.connect(self._on_loaded)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(lambda: self.refresh_btn.setEnabled(True))
        self._worker.start()

    def _on_loaded(self, entries: list):
        self.view.setHtml(changelog_html(entries))
        self.status.setText(f'已加载 {len(entries)} 条更新记录。')

    def _on_failed(self, reason: str):
        self.view.setHtml(changelog_html([]))
        self.status.setText('暂时拉不到更新日志(网络或 GitHub 不可用),'
                            '可稍后点「刷新」重试。')

    def closeEvent(self, event):
        """窗口关闭时别让后台线程继续跑(否则可能回调到已销毁的控件)。"""
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.quit()
            worker.wait(2000)
        super().closeEvent(event)
