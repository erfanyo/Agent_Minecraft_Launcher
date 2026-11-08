"""Run the experimental Qt Quick launcher shell: ``python qml_main.py``."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from launcher_app.qml.bridge import LauncherBridge


def main() -> int:
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Agent Minecraft Launcher · Qt Quick")
    engine = QQmlApplicationEngine()
    bridge = LauncherBridge()
    engine.rootContext().setContextProperty("amclBridge", bridge)
    qml = os.path.join(os.path.dirname(__file__), "qml", "ui", "Main.qml")
    engine.load(QUrl.fromLocalFile(qml))
    if not engine.rootObjects():
        return 1
    app.aboutToQuit.connect(bridge.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
