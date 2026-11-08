"""Python/QML boundary for the experimental Qt Quick launcher shell.

The bridge owns presentation state only. Instance discovery and launch preparation
stay in the same services used by the Widgets application.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, Property, Signal, Slot, Qt
from PySide6.QtGui import QColor, QGuiApplication

import paths
from settings import load_settings, save_settings
from launcher_app.ui import ui_tokens
from launcher_app.instances.instance_catalog_service import InstanceCatalogService
from launcher_app.instances.instance_install_service import InstanceInstallService
from launcher_app.instances.launch_preparation import LaunchRequest
from launcher_app.runtime.game_session_controller import GameSessionController
from launcher_app.runtime.launch_preparation_controller import LaunchPreparationController


class InstanceModel(QAbstractListModel):
    IdRole = int(Qt.ItemDataRole.UserRole) + 1
    LoaderRole = IdRole + 1
    BaseRole = IdRole + 2
    RunningRole = IdRole + 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []

    def roleNames(self):
        return {
            self.IdRole: b"instanceId",
            self.LoaderRole: b"loader",
            self.BaseRole: b"baseVersion",
            self.RunningRole: b"running",
        }

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() < 0 or index.row() >= len(self._rows):
            return None
        row = self._rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, self.IdRole):
            return row.get("id", "")
        if role == self.LoaderRole:
            return row.get("loader") or "Vanilla"
        if role == self.BaseRole:
            return row.get("base") or row.get("id", "")
        if role == self.RunningRole:
            return bool(row.get("running", False))
        return None

    def replace(self, rows):
        self.beginResetModel()
        self._rows = [dict(row) for row in rows]
        self.endResetModel()

    def row(self, index):
        return dict(self._rows[index]) if 0 <= index < len(self._rows) else {}


class LauncherBridge(QObject):
    selectedInstanceChanged = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    progressChanged = Signal()
    launchReadyChanged = Signal()
    themeChanged = Signal()
    resolvedThemeChanged = Signal()
    gameDirectoryChanged = Signal()

    def __init__(self, *, catalog=None, launch_controller=None, sessions=None, parent=None):
        super().__init__(parent)
        self.settings = load_settings()
        self._resolved_theme = self._resolve_theme()
        app = QGuiApplication.instance()
        if app is not None:
            try:
                app.styleHints().colorSchemeChanged.connect(self._on_system_theme_changed)
            except (AttributeError, RuntimeError):
                pass
        ui_tokens.set_theme_mode(self._resolved_theme)
        ui_tokens.set_custom_colors(self.settings.get("ui_custom_colors", {}))
        self._installer = InstanceInstallService(
            lambda: paths.GAME_DIR,
            lambda: bool(self.settings.get("version_isolation", True)),
        )
        self.catalog = catalog or InstanceCatalogService(
            lambda: paths.GAME_DIR, self._installer.game_dir_for)
        self.instances = InstanceModel(self)
        self._selected_instance = ""
        self._busy = False
        self._status = "Ready when you are."
        self._progress = 0
        self._launch_ready = False
        self._prepared_plan = None
        self._prepared_version = None
        self._task = None
        self._launch_controller = launch_controller or LaunchPreparationController(
            lambda: paths.GAME_DIR, self)
        self.sessions = sessions or GameSessionController(self)
        self._launch_controller.status.connect(self._on_status)
        self._launch_controller.progress.connect(self._on_progress)
        self._launch_controller.prepared.connect(self._on_prepared)
        self._launch_controller.failed.connect(self._on_failed)
        self._launch_controller.cancelled.connect(self._on_cancelled)
        self._launch_controller.failed.connect(self._finish_task)
        self._launch_controller.cancelled.connect(self._finish_task)
        self._launch_controller.prepared.connect(lambda *_: self._finish_task())
        self.sessions.exited.connect(self._on_game_exit)
        self.refreshInstances()

    @Property(QObject, constant=True)
    def instanceModel(self):
        return self.instances

    @Property(str, notify=selectedInstanceChanged)
    def selectedInstance(self):
        return self._selected_instance

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    @Property(float, notify=progressChanged)
    def progress(self):
        return self._progress

    @Property(bool, notify=launchReadyChanged)
    def launchReady(self):
        return self._launch_ready

    @Property(str, notify=themeChanged)
    def theme(self):
        return self.settings.get("ui_theme", "system")

    @Property(str, notify=resolvedThemeChanged)
    def resolvedTheme(self):
        return self._resolved_theme

    @Slot(str, str, result=QColor)
    def colorToken(self, name, _resolved_theme):
        value = ui_tokens.current_token(name)
        color = QColor(value)
        if color.isValid():
            return color
        # ui_tokens keeps legacy CSS rgba() values for Widgets; convert them to
        # QColor here because QML color literals use #AARRGGBB rather than CSS.
        import re
        match = re.fullmatch(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([0-9.]+)\s*\)", value)
        if match:
            red, green, blue = (int(match.group(i)) for i in (1, 2, 3))
            alpha = max(0.0, min(1.0, float(match.group(4))))
            return QColor.fromRgbF(red / 255, green / 255, blue / 255, alpha)
        return QColor("#ff000000")

    @Property(str, notify=gameDirectoryChanged)
    def gameDirectory(self):
        return paths.GAME_DIR

    def _on_system_theme_changed(self, *_args):
        if self.settings.get("ui_theme", "system") != "system":
            return
        self._resolved_theme = self._resolve_theme()
        ui_tokens.set_theme_mode(self._resolved_theme)
        self.resolvedThemeChanged.emit()

    def _resolve_theme(self):
        mode = self.settings.get("ui_theme", "system")
        if mode in ("dark", "light"):
            return mode
        app = QGuiApplication.instance()
        if app is not None:
            try:
                scheme = app.styleHints().colorScheme()
                if getattr(scheme, "name", "") == "Light":
                    return "light"
                if getattr(scheme, "name", "") == "Dark":
                    return "dark"
            except Exception:
                pass
        return "dark"

    def _set_status(self, text):
        self._status = str(text)
        self.statusChanged.emit()

    @Slot()
    def refreshInstances(self):
        try:
            rows = self.catalog.refresh()
            self.instances.replace(rows)
            ids = [row.get("id", "") for row in rows]
            wanted = self._selected_instance or self.settings.get("last_played_instance", "")
            if wanted not in ids:
                wanted = ids[0] if ids else ""
            if wanted != self._selected_instance:
                self._selected_instance = wanted
                self.selectedInstanceChanged.emit()
            self._set_status(f"{len(rows)} instance{'s' if len(rows) != 1 else ''} ready. Pick one to continue.")
        except Exception as exc:
            self.instances.replace([])
            self._set_status(f"Couldn't read the instance folder: {exc}")

    @Slot(str)
    def selectInstance(self, instance_id):
        if instance_id != self._selected_instance:
            self._selected_instance = instance_id
            self.selectedInstanceChanged.emit()
        self._discard_prepared()

    @Slot()
    def prepareLaunch(self):
        if self._busy or not self._selected_instance:
            return
        row = next((self.instances.row(i) for i in range(self.instances.rowCount())
                    if self.instances.row(i).get("id") == self._selected_instance), None)
        if row is None:
            self._set_status("That instance is no longer in the list. Refresh and try again.")
            return
        version = {**row, "local": True}
        request = LaunchRequest.capture(version, load_settings(), paths.GAME_DIR, paths.RUNTIME_DIR)
        try:
            self._task = self._launch_controller.create_task(request)
        except Exception as exc:
            self._set_status(str(exc))
            return
        self._busy = True
        self.busyChanged.emit()
        self._progress = 0
        self.progressChanged.emit()
        self._launch_ready = False
        self.launchReadyChanged.emit()
        self._set_status(f"Checking {self._selected_instance} and preparing Java…")
        self._task.start()

    @Slot()
    def cancelTask(self):
        if self._task is not None:
            self._task.cancel()
            self._set_status("Cancelling safely…")

    @Slot()
    def launchPrepared(self):
        if not self._launch_ready or not self._prepared_plan:
            return
        plan, version = self._prepared_plan, self._prepared_version
        try:
            started = self.sessions.start(plan.command, plan.java_exe, plan.game_dir)
            self.settings = load_settings()
            self.settings["last_played_instance"] = version["id"]
            save_settings(self.settings)
            self._discard_prepared()
            self._set_status(f"{version['id']} started (PID {started.pid}). Keep this window open to follow it.")
        except Exception as exc:
            self._set_status(f"Launch failed: {exc}. Your instance files were not removed.")

    @Slot(str)
    def setTheme(self, mode):
        if mode not in ("system", "dark", "light"):
            return
        self.settings["ui_theme"] = mode
        self._resolved_theme = self._resolve_theme()
        ui_tokens.set_theme_mode(self._resolved_theme)
        ui_tokens.set_custom_colors(self.settings.get("ui_custom_colors", {}))
        save_settings(self.settings)
        self.themeChanged.emit()
        self.resolvedThemeChanged.emit()

    @Slot(str)
    def setGameDirectory(self, folder):
        folder = folder.strip()
        if folder.startswith("file://"):
            from PySide6.QtCore import QUrl
            folder = QUrl(folder).toLocalFile()
        if not folder:
            return
        if os.path.isfile(folder):
            self._set_status("Choose a folder, not a file. The current game directory was left unchanged.")
            return
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            self._set_status(f"Couldn't use that folder: {exc}")
            return
        self.settings["game_dir"] = folder
        save_settings(self.settings)
        paths.set_game_dir(folder)
        self._installer = InstanceInstallService(
            lambda: paths.GAME_DIR, lambda: bool(self.settings.get("version_isolation", True)))
        self.catalog = InstanceCatalogService(lambda: paths.GAME_DIR, self._installer.game_dir_for)
        self.gameDirectoryChanged.emit()
        self.refreshInstances()

    def _on_status(self, message):
        self._set_status(message)

    def _on_progress(self, done, total):
        self._progress = (float(done) / float(total)) if total else 0.0
        self.progressChanged.emit()

    def _on_prepared(self, plan, version):
        self._prepared_plan, self._prepared_version = plan, dict(version)
        self._launch_ready = True
        self.launchReadyChanged.emit()
        self._set_status(f"Ready to start {version['id']}. Review the instance, then continue when you're ready.")

    def _on_failed(self, message):
        self._launch_ready = False
        self.launchReadyChanged.emit()
        self._set_status(f"Preparation didn't finish: {message}. You can retry; no instance was deleted.")

    def _on_cancelled(self):
        self._launch_ready = False
        self.launchReadyChanged.emit()
        self._set_status("Preparation cancelled. Nothing was removed from the instance.")

    def _finish_task(self, *_args):
        self._busy = False
        self._task = None
        self.busyChanged.emit()

    def _on_game_exit(self, code):
        self._set_status(f"Game closed (exit code {code}). Your saves remain in the instance folder.")

    def _discard_prepared(self):
        self._prepared_plan = None
        self._prepared_version = None
        if self._launch_ready:
            self._launch_ready = False
            self.launchReadyChanged.emit()

    @Slot()
    def close(self):
        if self._task is not None:
            self._task.cancel()
        self.sessions.detach()
