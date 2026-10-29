"""System webview helper. No Qt imports; IPC uses private inherited pipes."""
import json
import sys
import threading
import secrets
import os


def _pipe_stream(stream, handle_id, mode):
    """Windowed PyInstaller sets sys.std* to None, despite inherited QProcess pipes."""
    if stream is not None:
        return stream
    if sys.platform != 'win32':
        raise RuntimeError('Missing IPC stream')
    import ctypes
    import msvcrt
    get_handle = ctypes.windll.kernel32.GetStdHandle
    get_handle.argtypes = [ctypes.c_ulong]
    get_handle.restype = ctypes.c_void_p
    handle = get_handle(handle_id & 0xffffffff)
    if not handle or handle == ctypes.c_void_p(-1).value:
        raise RuntimeError('Missing inherited pipe')
    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY if mode == 'r' else os.O_WRONLY)
    return os.fdopen(fd, mode, encoding='utf-8', buffering=1)

MAX_MESSAGE = 8 * 1024 * 1024


def protected_html(html):
    # Inline trusted plugin assets only. No remote navigation, network or file access.
    policy = ("default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; "
              "style-src 'unsafe-inline'; img-src data: blob:; font-src data:; "
              "connect-src 'none'; object-src 'none'; frame-src 'none'; "
              "base-uri 'none'; form-action 'none'")
    return '<meta http-equiv="Content-Security-Policy" content="' + policy + '">' + html


def main():
    source = _pipe_stream(sys.stdin, -10, 'r')
    sink = _pipe_stream(sys.stdout, -11, 'w')
    # Keep library diagnostics off the protocol channel.
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w', encoding='utf-8')
    sys.stdout = sys.stderr
    lock = threading.Lock()
    token = secrets.token_hex(32)

    def send(message):
        data = json.dumps(message, ensure_ascii=True)
        if len(data) > MAX_MESSAGE:
            raise ValueError('Message too large')
        sink.write(data + '\n')
        sink.flush()

    class Bridge:
        def call(self, key, name, payload=None):
            if not isinstance(key, str) or not secrets.compare_digest(key, token):
                return {'ok': False, 'error': 'Page not authorized'}
            with lock:
                send({'type': 'call', 'name': name, 'payload': payload})
                response = source.readline(MAX_MESSAGE + 1)
                if not response or len(response) > MAX_MESSAGE:
                    raise RuntimeError('Launcher disconnected')
                return json.loads(response)

    try:
        line = source.readline(MAX_MESSAGE + 1)
        if len(line) > MAX_MESSAGE:
            raise ValueError('Config too large')
        config = json.loads(line)
        try:
            import webview
        except ImportError:
            send({'type': 'error', 'message': '此版本未安装网页组件 pywebview；请安装带网页组件的启动器。开发环境可安装 requirements-webview.txt。'})
            return 1
        webview.settings['ALLOW_FILE_URLS'] = False
        webview.settings['ALLOW_DOWNLOADS'] = False
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
        bootstrap = ('<script>window.amcl = {call: (name, payload=null) => '
                     'window.pywebview.api.call(' + json.dumps(token) + ', name, payload)};</script>')
        webview.create_window(config['title'], html=protected_html(bootstrap + config['html']),
                              js_api=Bridge(), width=config['width'], height=config['height'],
                              confirm_close=True)
        backend = 'edgechromium' if sys.platform == 'win32' else 'cocoa' if sys.platform == 'darwin' else 'gtk'
        webview.start(gui=backend, debug=False, private_mode=True)
        return 0
    except Exception:
        send({'type': 'error', 'message': '无法打开系统网页窗口。Windows 请确认已安装 Microsoft WebView2 Runtime；Linux 需要 GTK/WebKit。不会自动下载浏览器内核。'})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
