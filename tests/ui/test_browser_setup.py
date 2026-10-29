"""Browser setup UI is isolated from unit tests' Qt lifecycles."""
from unittest.mock import patch
from launcher_app.browser import browser_setup as setup


def test_one_click_ui_reports_completion_and_allows_retry(qtbot):
    from launcher_app.features import browser_assistant
    builders = []
    api = type('API', (), {'register_settings_page': lambda self, fn: builders.append(fn)})()
    browser_assistant.register(api)

    def configure(status):
        status('正在检查…')
        return '配置完成'

    with patch.object(setup, 'ready', return_value=False), \
         patch.object(setup, 'configure', side_effect=configure) as install:
        widget = builders[0]()
        qtbot.addWidget(widget)
        widget._browser_setup_button.click()
        qtbot.waitUntil(lambda: widget._browser_setup_button.isEnabled(), timeout=5000)
        assert widget._browser_setup_status.text() == '配置完成'
        install.assert_called_once()
