"""JVM option parsing independent of GUI; shell is never involved."""
import re
import shlex


def parse_jvm(text):
    lexer = shlex.shlex(str(text or ''), posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ''
    lexer.escape = ''  # Preserve Windows paths, allow quoted properties with spaces.
    args = list(lexer)
    for arg in args:
        if not arg.startswith(('-D', '-XX:', '-X', '-ea', '-da', '-esa', '-dsa', '-verbose')) or '\x00' in arg:
            raise ValueError('这里只填写 JVM 参数，例如 -XX:+UseG1GC；不填写 Java 路径、主类或游戏参数。')
        if arg.startswith(('-Xmx', '-Xms')):
            raise ValueError('内存大小请使用内存分配选项，避免与启动器预算冲突。')
    return args


def apply_jvm(command, text):
    custom = parse_jvm(text)
    command = list(command)
    if any(re.fullmatch(r'-XX:\+Use\w+GC', arg) for arg in custom):
        command = [arg for arg in command if arg != '-XX:+UseG1GC']
    return command[:1] + custom + command[1:]


def editor(value='', instance=False):
    from PySide6.QtWidgets import QGroupBox, QWidget, QVBoxLayout, QPlainTextEdit, QLabel, QCheckBox
    box = QGroupBox('高级设置选项')
    box.setCheckable(True)
    layout = QVBoxLayout(box)
    body = QWidget()
    fields = QVBoxLayout(body)
    fields.setContentsMargins(0, 0, 0, 0)
    inherit = QCheckBox('跟随全局 JVM 参数')
    inherit.setChecked(value is None)
    inherit.setVisible(instance)
    fields.addWidget(inherit)
    text = QPlainTextEdit(value or '')
    text.setPlaceholderText('额外 JVM 参数，例如 -XX:+UseG1GC\n带空格的参数请用双引号包起来')
    text.setMaximumHeight(110)
    fields.addWidget(text)
    hint = QLabel('不合适的参数可能导致启动失败。留空使用默认参数；内存大小请在上方设置。')
    hint.setWordWrap(True)
    fields.addWidget(hint)
    text.setEnabled(not (instance and inherit.isChecked()))
    inherit.toggled.connect(lambda checked: text.setEnabled(not checked))
    layout.addWidget(body)
    box.toggled.connect(body.setVisible)
    box.setChecked(False)
    body.hide()
    def values():
        if instance and inherit.isChecked():
            return None
        value = text.toPlainText().strip()
        parse_jvm(value)
        return value
    box.values = values
    return box
