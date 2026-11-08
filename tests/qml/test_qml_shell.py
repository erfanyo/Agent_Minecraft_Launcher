"""Focused smoke checks for the experimental Qt Quick entry point.

Run separately from the Widgets suite: ``python -m pytest tests/qml``.
"""
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6 import QtQuick  # register QQuickWindow before the QML engine loads

from launcher_app.qml.bridge import LauncherBridge


class CatalogStub:
    def refresh(self):
        return [
            {"id": "1.20.1-fabric", "loader": "fabric", "base": "1.20.1"},
            {"id": "1.21.1", "loader": None, "base": "1.21.1"},
        ]


def _app():
    return QGuiApplication.instance() or QGuiApplication([])


def test_instance_model_uses_injected_catalog():
    _app()
    bridge = LauncherBridge(catalog=CatalogStub())
    assert bridge.instances.rowCount() == 2
    assert bridge.selectedInstance == "1.20.1-fabric"
    assert bridge.instances.data(bridge.instances.index(0), bridge.instances.LoaderRole) == "fabric"
    assert bridge.colorToken("panel_bg", bridge.resolvedTheme).isValid()
    assert bridge.colorToken("text0", bridge.resolvedTheme).name() == "#e7ecf5"
    bridge.selectInstance("1.21.1")
    assert bridge.selectedInstance == "1.21.1"
    bridge.close()


def test_qml_shell_loads_and_routes_to_experiment_pages():
    app = _app()
    engine = QQmlApplicationEngine()
    bridge = LauncherBridge(catalog=CatalogStub())
    engine.rootContext().setContextProperty("amclBridge", bridge)
    qml = Path(__file__).parents[2] / "launcher_app" / "qml" / "ui" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml)))
    assert engine.rootObjects(), "Main.qml should compile and create its ApplicationWindow"
    window = engine.rootObjects()[0]
    window.show()
    for page, label in ((1, "Instances"), (3, "Agent workbench"), (4, "Settings"), (0, "Home")):
        window.setProperty("pageIndex", page)
        window.setProperty("pageName", label)
        app.processEvents()
    app.processEvents()
    image = window.grabWindow()
    assert not image.isNull()
    assert image.width() >= 800 and image.height() >= 620
    bridge.close()
    # Keep the engine alive through test teardown; QtQuick may still flush a
    # page Loader transition on the next event-loop turn.
    app.processEvents()
