"""Switches control expansion and inheritance without losing saved options."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QGroupBox
from launcher_app.ui.jvm_options_editor import editor

pytestmark = pytest.mark.ui


def test_advanced_switch_only_folds_and_preserves_args(qtbot):
    widget = editor('-XX:+UseG1GC')
    qtbot.addWidget(widget)
    widget.show()
    assert not widget.body.isVisible()
    assert widget.values() == '-XX:+UseG1GC'
    qtbot.mouseClick(widget.expanded_switch, Qt.MouseButton.LeftButton)
    assert widget.body.isVisible()
    widget.text.setPlainText('-Dname="My Pack"')
    qtbot.mouseClick(widget.expanded_switch, Qt.MouseButton.LeftButton)
    assert not widget.body.isVisible()
    assert widget.values() == '-Dname="My Pack"'
    assert not widget.findChildren(QCheckBox)
    assert not widget.findChildren(QGroupBox)


def test_instance_inheritance_preserves_custom_text(qtbot):
    widget = editor(None, instance=True)
    qtbot.addWidget(widget)
    widget.show()
    widget.setChecked(True)
    assert widget.values() is None
    assert not widget.text.isEnabled()
    qtbot.mouseClick(widget.inherit_switch, Qt.MouseButton.LeftButton)
    widget.text.setPlainText('-XX:+UseZGC')
    assert widget.text.isEnabled()
    assert widget.values() == '-XX:+UseZGC'
    qtbot.mouseClick(widget.inherit_switch, Qt.MouseButton.LeftButton)
    assert widget.values() is None
    qtbot.mouseClick(widget.inherit_switch, Qt.MouseButton.LeftButton)
    assert widget.values() == '-XX:+UseZGC'


def test_keyboard_and_validation_when_collapsed(qtbot):
    widget = editor('-Xmx8G')
    qtbot.addWidget(widget)
    widget.show()
    widget.expanded_switch.setFocus()
    qtbot.keyClick(widget.expanded_switch, Qt.Key.Key_Space)
    assert widget.isChecked()
    widget.setChecked(False)
    with pytest.raises(ValueError):
        widget.values()
