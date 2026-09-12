import io
import json
import sys
import os
import unittest
from unittest.mock import Mock, patch

import plugin_manager as pm
import plugin_web_worker as worker


class PluginUITests(unittest.TestCase):
    def test_page_validation_and_registration(self):
        with patch.object(pm, 'CENTER_PAGES', {}):
            api = pm.PluginAPI('example')
            builder = Mock()
            api.register_center_page('online', 'editor', '编辑器', builder)
            builder.assert_not_called()
            self.assertEqual('example', pm.CENTER_PAGES['online'][0][0])
            with self.assertRaises(ValueError):
                api.register_center_page('online', 'editor', '其他标题', builder)
            with self.assertRaises(ValueError):
                api.register_center_page('missing', 'editor', '编辑器', builder)

    def test_failed_plugin_leaves_no_center_page(self):
        def register(api):
            api.register_center_page('online', 'x', '坏插件', lambda: None)
            raise RuntimeError('fail')
        mod = Mock(PLUGIN_API_VERSION=1, register=register)
        with patch.object(pm, 'CENTER_PAGES', {}), patch.object(pm, '_load_plugin_module', return_value=mod):
            self.assertFalse(pm.load_plugin('bad', 'unused', set()))
            self.assertEqual([], pm.CENTER_PAGES['online'])

    def test_worker_forces_system_engine_and_explicit_rpc(self):
        config = {'title': '测试', 'html': '<h1>Hi</h1>', 'width': 800, 'height': 600}
        source = io.StringIO(json.dumps(config) + '\n{"ok":true,"result":42}\n')
        sink = io.StringIO()
        webview = Mock(settings={})
        def start(**kwargs):
            self.assertEqual('edgechromium', kwargs['gui'])
            args = webview.create_window.call_args.kwargs
            self.assertIn("connect-src 'none'", args['html'])
            bridge = args['js_api']
            self.assertFalse(bridge.call('wrong', 'summary')['ok'])
            self.assertEqual(42, bridge.call('token', 'summary', {})['result'])
        webview.start.side_effect = start
        with patch.dict(sys.modules, {'webview': webview}), patch.object(sys, 'stdin', source), patch.object(sys, 'stdout', sink), patch.object(sys, 'platform', 'win32'), patch.object(worker.secrets, 'token_hex', return_value='token'):
            self.assertEqual(0, worker.main())
        self.assertEqual('summary', json.loads(sink.getvalue())['name'])
        self.assertFalse(webview.settings['ALLOW_FILE_URLS'])

    def test_worker_missing_dependency_is_actionable(self):
        source = io.StringIO('{"title":"test","html":"","width":800,"height":600}\n')
        sink = io.StringIO()
        with patch.dict(sys.modules, {'webview': None}), patch.object(sys, 'stdin', source), patch.object(sys, 'stdout', sink):
            self.assertEqual(1, worker.main())
        self.assertIn('pywebview', json.loads(sink.getvalue())['message'])

    @unittest.skipUnless(os.environ.get('AMCL_TEST_WEBVIEW') == '1', 'Opt-in visible system WebView test')
    def test_real_window_roundtrip(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QEventLoop, QTimer
        from plugin_web_window import open_web_window
        app = QApplication.instance() or QApplication([])
        loop = QEventLoop()
        received, errors = [], []
        def done(payload):
            received.append(payload)
            QTimer.singleShot(100, loop.quit)
            return 'OK'
        html = '''<h1>AMCL 网页窗口自检</h1><script>
        addEventListener('pywebviewready', async()=>{
          const r=await amcl.call('echo', {value:42});
          await amcl.call('done', r);
        });</script>'''
        window = open_web_window('AMCL WebView 自检（自动关闭）', html,
                                 handlers={'echo': lambda p: p, 'done': done},
                                 on_error=lambda e: (errors.append(e), loop.quit()))
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(25000)
        loop.exec()
        window.close()
        window.process.waitForFinished(3000)
        self.assertFalse(errors, errors)
        self.assertEqual([{'ok': True, 'result': {'value': 42}}], received)


if __name__ == '__main__':
    unittest.main()
