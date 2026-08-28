# -*- coding: utf-8 -*-
"""
「检查更新」对话框(从 main.py 拆分而来):AMCL 启动器 + bridge-mod 的更新检查。

**为什么拆**:main.py 原 2000+ 行,MainWindow 高度耦合 self 状态难以整体拆分;
本模块是其中**完全自包含**的独立 UI——只依赖 updater / paths / bridge_mod_dist /
i18n / Qt,不引用 MainWindow 或 AI 核心,故抽出独立成模块,降低 main.py 体积、提升可维护性。

被 main.py 经 `from updater_dialog import UpdateDialog` 复用。
"""
import os
import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

import updater
import paths
from bridge_mod_dist import BRIDGE_MOD_VERSION
from i18n import t


class _UpdateSignals(QObject):
    checked = Signal()        # 版本检查完成(主线程刷新界面)
    progress = Signal(int, int)
    downloaded = Signal()
    failed = Signal(str)


class UpdateDialog(QDialog):
    """检查更新:AMCL 启动器 + bridge-mod(从 GitHub Releases 拉取)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("CHECK_FOR_UPDATES_ALT"))
        self.setMinimumWidth(440)
        self.sig = _UpdateSignals()
        self.sig.checked.connect(self._refresh)
        self.sig.progress.connect(self._on_progress)
        self.sig.downloaded.connect(self._on_downloaded)
        self.sig.failed.connect(self._on_failed)
        self.result = {"launcher": None, "bridge": None, "error": ""}

        self.launcher_label = QLabel("AMCL 启动器: 正在检查...")
        self.bridge_label = QLabel("bridge-mod: 正在检查...")
        self.launcher_btn = QPushButton(t("DOWNLOAD_UPDATE"))
        self.launcher_btn.setVisible(False)
        self.launcher_btn.clicked.connect(self._do_launcher_update)
        self.bridge_btn = QPushButton(t("OPEN_RELEASE_PAGE"))
        self.bridge_btn.setVisible(False)
        self.bridge_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(updater.RELEASES_API)))
        close_btn = QPushButton(t("CLOSE"))
        close_btn.clicked.connect(self.accept)

        row = QHBoxLayout()
        row.addWidget(close_btn)
        row.addStretch()

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(t("AMCL_LAUNCHER")))
        layout.addWidget(self.launcher_label)
        layout.addWidget(self.launcher_btn)
        layout.addSpacing(10)
        layout.addWidget(QLabel(t("BRIDGE_MOD")))
        layout.addWidget(self.bridge_label)
        layout.addWidget(self.bridge_btn)
        layout.addSpacing(10)
        layout.addLayout(row)

        threading.Thread(target=self._check, daemon=True).start()

    def _check(self):
        try:
            self.result["launcher"] = updater.check_launcher_update()
            self.result["bridge"] = updater.check_bridge_mod_update()
        except Exception as e:
            self.result["error"] = str(e)
        self.sig.checked.emit()

    def _refresh(self):
        err = self.result.get("error")
        if err:
            self.launcher_label.setText(f"检查失败: {err[:120]}")
            self.bridge_label.setText("—")
            return
        # AMCL
        upd = self.result.get("launcher")
        cur = updater.VERSION
        if upd:
            new_ver = upd["version"]
            if updater.parse_version(new_ver) <= updater.parse_version(cur):
                self.launcher_label.setText(f"AMCL 启动器: 已是最新 (v{cur}) ✅")
            else:
                self.launcher_label.setText(
                    f"AMCL 启动器: 当前 v{cur} → 发现新版本 {new_ver}")
                self.launcher_btn.setVisible(True)
        else:
            self.launcher_label.setText(
                f"AMCL 启动器: 当前 v{cur}(未能获取最新版本,请检查网络)")
        # bridge-mod
        br = self.result.get("bridge")
        if br:
            self.bridge_label.setText(
                f"bridge-mod: 本地 {BRIDGE_MOD_VERSION} → GitHub {br['version']}")
            self.bridge_btn.setVisible(True)
        else:
            self.bridge_label.setText(
                f"bridge-mod: 本地 {BRIDGE_MOD_VERSION}(未能获取最新版本)")

    def _do_launcher_update(self):
        info = self.result.get("launcher")
        if not info:
            return
        self.launcher_btn.setEnabled(False)
        self.launcher_btn.setText("下载中 0%")
        exe_path = (sys.executable if getattr(sys, "frozen", False)
                    else os.path.join(paths.BASE_DIR, updater.LAUNCHER_ASSET))
        update_dir = os.path.join(paths.BASE_DIR, "AMCL", "update")
        new_exe = os.path.join(update_dir, updater.LAUNCHER_ASSET)
        threading.Thread(target=self._download_and_apply,
                         args=(info["url"], new_exe, exe_path),
                         daemon=True).start()

    def _download_and_apply(self, url, new_exe, exe_path):
        try:
            updater.download_to(url, new_exe, progress_callback=self.sig.progress.emit)
            bat = os.path.join(os.path.dirname(new_exe), "update.bat")
            updater.make_update_bat(exe_path, new_exe, bat)
            updater.run_update_bat(bat)
            self.sig.downloaded.emit()
        except Exception as e:
            self.sig.failed.emit(str(e))

    def _on_progress(self, done, total):
        pct = int(done * 100 / total) if total else 0
        self.launcher_btn.setText(f"下载中 {pct}%")

    def _on_downloaded(self):
        QMessageBox.information(
            self, t("UPDATE"),
            t("UPDATE_DOWNLOADED_THE_APP_WILL_RESTART"))
        QTimer.singleShot(300, QApplication.instance().quit)

    def _on_failed(self, msg):
        self.launcher_btn.setEnabled(True)
        self.launcher_btn.setText(t("DOWNLOAD_UPDATE"))
        QMessageBox.warning(self, t("UPDATE_FAILED"),
                            f"下载/替换失败:{msg[:200]}")
