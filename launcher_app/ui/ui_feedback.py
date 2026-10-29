"""Small inline feedback for successful clipboard actions."""


from launcher_app.core.i18n import t
def copy_with_feedback(button, text):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    if not text:
        return
    QApplication.clipboard().setText(str(text))
    if QApplication.clipboard().text() != str(text):
        button.setToolTip(t('复制未完成，请重试。'))
        return
    timer = getattr(button, '_copy_feedback_timer', None)
    if timer is None:
        button._copy_original_text = button.text()
        timer = QTimer(button)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: button.setText(button._copy_original_text))
        button._copy_feedback_timer = timer
    button.setText(t('已复制到剪贴板'))
    timer.start(2000)
