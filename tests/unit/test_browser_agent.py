import unittest
from unittest.mock import patch
import launcher_app.browser.browser_agent as browser_agent


class BrowserPolicyTests(unittest.TestCase):
    def test_dangerous_capabilities_fail_closed(self):
        for name in ('browser_evaluate', 'browser_run_code', 'browser_file_upload',
                     'browser_install', 'browser_cookie_list', 'new_upstream_tool'):
            with self.assertRaises(ValueError):
                browser_agent.validate(name, {})

    def test_urls_and_local_file_outputs(self):
        for url in ('file:///C:/secret', 'javascript:alert(1)', 'chrome://settings',
                    'https://user:password@example.com'):
            with self.assertRaises(ValueError):
                browser_agent.validate('browser_navigate', {'url': url})
        with self.assertRaises(ValueError):
            browser_agent.validate('browser_take_screenshot', {'filename': 'C:/target'})
        browser_agent.validate('browser_navigate', {'url': 'https://www.bilibili.com'})

    def test_untrusted_annotations_cannot_bypass_confirmation(self):
        class Fake:
            def tools(self):
                return [{'name': n, 'annotations': {'readOnlyHint': True}} for n in
                        ('browser_snapshot', 'browser_click', 'browser_evaluate', 'unknown')]
        with patch.object(browser_agent, 'connection', return_value=Fake()):
            schemas, callers = browser_agent.tools({})
        self.assertEqual(len(schemas), 2)
        self.assertFalse(callers['mcp__browser__browser_click'][2]['readOnlyHint'])
        self.assertTrue(callers['mcp__browser__browser_snapshot'][2]['readOnlyHint'])

    def test_disabled_connection_never_starts_process(self):
        with patch('launcher_app.browser.mcp_client.MCPStdioClient') as client:
            self.assertIsNone(browser_agent.connection({'browser_agent_enabled': False}))
        client.assert_not_called()


if __name__ == '__main__':
    unittest.main()
