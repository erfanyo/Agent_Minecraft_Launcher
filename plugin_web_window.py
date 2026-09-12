"""Lazy Qt-side host for system-webview plugin windows (no Chromium bundle)."""
import json
import os
import sys

_windows = set()
MAX_MESSAGE = 8 * 1024 * 1024


def open_web_window(title, html, *, handlers=None, width=1100, height=760, on_error=None):
    from PySide6.QtCore import QProcess, QThread
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        raise RuntimeError('网页窗口必须从 GUI 线程打开')
    if not isinstance(title, str) or not title.strip() or not isinstance(html, str):
        raise ValueError('窗口需要标题和 HTML 文本')
    handlers = dict(handlers or {})
    if any(not isinstance(k, str) or not k.isidentifier() or not callable(v)
           for k, v in handlers.items()):
        raise ValueError('交互方法必须使用有效名称并提供回调')
    config = {'title': title, 'html': html, 'width': max(400, min(int(width), 3840)),
              'height': max(300, min(int(height), 2160))}
    encoded = json.dumps(config, ensure_ascii=True).encode() + b'\n'
    if len(encoded) > MAX_MESSAGE:
        raise ValueError('HTML 太大，请将大型模型数据与界面分开')

    class WindowHandle:
        def __init__(self):
            self.process = QProcess(app)
            self.buffer = b''
            self.failed = False
            self.closing = False
            self.process.started.connect(lambda: self.process.write(encoded))
            self.process.readyReadStandardOutput.connect(self.receive)
            # Drain diagnostics; never log plugin data or echo traceback to the UI.
            self.process.readyReadStandardError.connect(self.process.readAllStandardError)
            self.process.errorOccurred.connect(self.process_error)
            self.process.finished.connect(self.finished)
            app.aboutToQuit.connect(self.close)

        def process_error(self, code):
            self.error('网页窗口未能启动，请检查网页组件是否已安装。')
            if code == QProcess.ProcessError.FailedToStart:
                self.finished(0, None)

        def error(self, message):
            if self.failed or self.closing:
                return
            self.failed = True
            if on_error:
                on_error(message)
            else:
                QMessageBox.warning(None, '插件网页窗口', message)

        def receive(self):
            self.buffer += bytes(self.process.readAllStandardOutput())
            if len(self.buffer) > MAX_MESSAGE:
                self.error('网页交互数据过大，已关闭窗口。')
                self.close()
                return
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                try:
                    msg = json.loads(line)
                    if not isinstance(msg, dict):
                        continue
                    if msg.get('type') == 'error':
                        self.error(str(msg.get('message', '网页窗口异常')))
                    elif msg.get('type') == 'call':
                        response = {'ok': False, 'error': '未注册的操作'}
                        name = msg.get('name')
                        if isinstance(name, str) and name in handlers:
                            try:
                                response = {'ok': True, 'result': handlers[name](msg.get('payload'))}
                                json.dumps(response, allow_nan=False)
                            except Exception:
                                response = {'ok': False, 'error': '插件操作失败'}
                        data = json.dumps(response, ensure_ascii=True).encode() + b'\n'
                        if len(data) > MAX_MESSAGE:
                            data = b'{"ok":false,"error":"Response too large"}\n'
                        self.process.write(data)
                except (ValueError, TypeError):
                    continue

        def finished(self, code, status):
            self.receive()
            if code and not self.closing:
                self.error('网页窗口已异常退出；请检查系统 WebView 运行时。')
            _windows.discard(self)
            try:
                app.aboutToQuit.disconnect(self.close)
            except RuntimeError:
                pass
            self.process.deleteLater()

        def close(self):
            # Explicit host shutdown: normal user closing uses the native window.
            if self.closing:
                return
            self.closing = True
            self.process.kill()

    handle = WindowHandle()
    _windows.add(handle)
    if getattr(sys, 'frozen', False):
        program, args = sys.executable, ['--amcl-plugin-web-window']
    else:
        program = sys.executable
        args = [os.path.join(os.path.dirname(__file__), 'plugin_web_worker.py')]
    handle.process.start(program, args)
    return handle
