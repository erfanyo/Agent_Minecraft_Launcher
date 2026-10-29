import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from launcher_app.ui.numeric_input import SettingsSpinBox

pytestmark = pytest.mark.ui


def test_wheel_cannot_change_settings_number_even_with_focus(qtbot):
    spin = SettingsSpinBox()
    qtbot.addWidget(spin)
    spin.setValue(50)
    spin.show()
    spin.setFocus()
    event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(spin, event)
    assert spin.value() == 50
    assert not event.isAccepted()
    spin.stepUp()
    assert spin.value() == 51
