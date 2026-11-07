"""Widgets editor for JVM options; parsing rules live in runtime."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit, QLabel
from launcher_app.core.i18n import t
from launcher_app.runtime.jvm_options import parse_jvm
from launcher_app.ui.ui_switch import ToggleSwitch, setting_switch_row


class JvmOptionsEditor(QWidget):
    def __init__(self, value='', instance=False, parent=None):
        super().__init__(parent)
        self.instance = instance
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.expanded_switch = ToggleSwitch(False)
        self.expanded_switch.setObjectName('jvm_advanced_switch')
        layout.addWidget(setting_switch_row(t('高级设置选项'), self.expanded_switch))
        self.body = QWidget()
        fields = QVBoxLayout(self.body)
        fields.setContentsMargins(0, 0, 0, 0)
        self.inherit_switch = ToggleSwitch(value is None)
        self.inherit_switch.setObjectName('jvm_inherit_switch')
        inherit_row = setting_switch_row(t('跟随全局 JVM 参数'), self.inherit_switch)
        inherit_row.setVisible(instance)
        fields.addWidget(inherit_row)
        self.text = QPlainTextEdit(value or '')
        self.text.setPlaceholderText(t('额外 JVM 参数，例如 -XX:+UseG1GC\n带空格的参数请用双引号包起来'))
        self.text.setMaximumHeight(110)
        fields.addWidget(self.text)
        hint = QLabel(t('不合适的参数可能导致启动失败。留空使用默认参数；内存大小请在上方设置。'))
        hint.setWordWrap(True)
        fields.addWidget(hint)
        self.text.setEnabled(not (instance and self.inherit_switch.isChecked()))
        self.inherit_switch.toggled.connect(
            lambda checked: self.text.setEnabled(not (self.instance and checked)))
        layout.addWidget(self.body)
        self.expanded_switch.toggled.connect(self.body.setVisible)
        self.body.hide()

    def isChecked(self):
        """Compatibility: expansion does not control whether saved args apply."""
        return self.expanded_switch.isChecked()

    def setChecked(self, checked):
        self.expanded_switch.setChecked(checked)

    def values(self):
        if self.instance and self.inherit_switch.isChecked():
            return None
        value = self.text.toPlainText().strip()
        parse_jvm(value)
        return value


def editor(value='', instance=False):
    return JvmOptionsEditor(value, instance)
