"""Feedback must preserve input, custom effects and animation lifecycle."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QPushButton, QGraphicsDropShadowEffect
from launcher_app.ui.ui_anim import (
    reveal, install_interaction_feedback, set_animations_enabled,
)

pytestmark = pytest.mark.ui


def test_reveal_tracks_size_and_does_not_replace_effect(qtbot):
    page = QWidget()
    qtbot.addWidget(page)
    effect = QGraphicsDropShadowEffect(page)
    page.setGraphicsEffect(effect)
    page.show()
    set_animations_enabled(True)
    reveal(page)
    layer = page._ui_feedback_layer
    page.resize(640, 400)
    assert layer.geometry() == page.rect()
    assert page.graphicsEffect() is effect
    assert layer.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    qtbot.waitUntil(lambda: not layer.isVisible())


def test_button_click_delivered_and_release_continues_current_value(qtbot):
    root = QWidget()
    button = QPushButton('Go', root)
    qtbot.addWidget(root)
    root.show()
    root.feedback = install_interaction_feedback(root)
    set_animations_enabled(True)
    clicked = []
    button.clicked.connect(lambda: clicked.append(True))
    qtbot.mousePress(button, Qt.MouseButton.LeftButton)
    layer = button._ui_feedback_layer
    layer.animation.setCurrentTime(30)
    amount = layer.amount
    qtbot.mouseRelease(button, Qt.MouseButton.LeftButton)
    assert clicked == [True]
    assert layer.animation.startValue() == pytest.approx(amount)
    assert button.graphicsEffect() is None
    qtbot.waitUntil(lambda: not layer.isVisible())


def test_disabling_and_hiding_clear_feedback(qtbot):
    page = QWidget()
    qtbot.addWidget(page)
    page.show()
    set_animations_enabled(True)
    reveal(page)
    layer = page._ui_feedback_layer
    set_animations_enabled(False)
    assert not layer.isVisible()
    set_animations_enabled(True)
    reveal(page)
    page.hide()
    page.show()
    assert not layer.isVisible()


def test_disabled_reveal_creates_no_layer(qtbot):
    page = QWidget()
    qtbot.addWidget(page)
    page.show()
    set_animations_enabled(False)
    reveal(page)
    assert not hasattr(page, '_ui_feedback_layer')
