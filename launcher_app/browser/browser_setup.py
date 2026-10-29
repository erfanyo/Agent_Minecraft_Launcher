"""User-initiated browser prerequisites; only the signed Node installer elevates."""
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import threading

MCP_VERSION = '0.0.83'
NODE_VERSION = '22.23.4'
# Official nodejs.org v22.23.4/SHASUMS256.txt, verified 2026-10-24.
NODE_SHA256 = {
    'x64': 'ca9303d3a12e8bec6de829fcb7812fc776930e0ce5c030328a24984ef928427e',
    'arm64': '49edbb15812c13efa061c2c76b06944425f3711454845e78b625a8e865a45327',
}
_install_lock = threading.Lock()


def find_extension_browser():
    """Select a single standard Windows browser with the official extension.

    Only inspect extension directory names, never profile contents or cookies.
    Ambiguous installations keep Playwright's default / explicit environment.
    """
    if sys.platform != 'win32' or not os.environ.get('LOCALAPPDATA'):
        return None
    local = Path(os.environ['LOCALAPPDATA'])
    program_roots = [Path(os.environ[key]) for key in ('ProgramFiles', 'ProgramFiles(x86)')
                     if os.environ.get(key)]
    extension_id = 'mmlmfjhmonkocbjadbfplnigmagldckm'
    matches = []
    for vendor, browser, binary in (('Google', 'Chrome', 'chrome.exe'),
                                     ('Microsoft', 'Edge', 'msedge.exe')):
        profiles = local / vendor / browser / 'User Data'
        try:
            folders = [profiles / 'Default', *profiles.glob('Profile *')]
            installed = any((folder / 'Extensions' / extension_id).is_dir() for folder in folders)
        except OSError:
            installed = False
        if not installed:
            continue
        candidates = [root / vendor / browser / 'Application' / binary
                      for root in [*program_roots, local]]
        executable = next((str(path) for path in candidates if path.is_file()), None)
        if executable:
            matches.append(executable)
    return matches[0] if len(matches) == 1 else None


def runtime_dir():
    import paths
    return Path(paths.CONFIG_DIR) / 'runtime' / 'browser-agent'


def run(args, timeout=600, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=timeout,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), **kwargs)


def find_node():
    candidates = [shutil.which('node')]
    for key in ('ProgramW6432', 'ProgramFiles', 'ProgramFiles(x86)'):
        if os.environ.get(key):
            candidates.append(str(Path(os.environ[key]) / 'nodejs' / 'node.exe'))
    for node in dict.fromkeys(filter(None, candidates)):
        try:
            result = run([node, '--version'], timeout=10)
            if result.returncode == 0 and int(result.stdout.strip().lstrip('v').split('.')[0]) >= 22:
                return node
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return None


def ready():
    root = runtime_dir()
    try:
        data = json.loads((root / 'node_modules' / '@playwright' / 'mcp' / 'package.json').read_text(encoding='utf-8'))
        return bool(find_node() and data.get('version') == MCP_VERSION and
                    (root / 'node_modules' / '@playwright' / 'mcp' / 'cli.js').is_file())
    except (OSError, ValueError):
        return False


def _install_node(root, status):
    if os.name != 'nt':
        raise RuntimeError('请先安装 Node.js 22 或更高版本，再点一键配置。')
    arch = platform.machine().lower()
    if arch not in {'amd64', 'x86_64', 'arm64', 'aarch64'}:
        raise RuntimeError('当前架构暂不支持自动安装 Node.js。')
    arch = 'arm64' if arch in {'arm64', 'aarch64'} else 'x64'
    name = f'node-v{NODE_VERSION}-{arch}.msi'
    base = f'https://nodejs.org/dist/v{NODE_VERSION}/'
    from launcher_app.resources.downloader import download_file
    status('正在下载 Node.js 官方安装程序…')
    expected = NODE_SHA256[arch]
    cache = root / 'setup'
    cache.mkdir(parents=True, exist_ok=True)
    installer = cache / name
    download_file(base + name, str(installer))
    with installer.open('rb') as source:
        actual = hashlib.file_digest(source, 'sha256').hexdigest()
    if actual != expected.lower():
        installer.unlink(missing_ok=True)
        raise RuntimeError('Node.js 安装程序校验失败，未执行安装。')
    from launcher_app.runtime.windows_runtime_support import _trusted_signature, _run_elevated_installer
    trusted, detail = _trusted_signature(str(installer))
    if not trusted:
        raise RuntimeError('Node.js 安装程序签名未通过 Windows 验证，未执行安装。')
    status('请在 Windows 系统授权窗口中确认安装 Node.js；启动器本身不会提权。')
    executable = str(Path(os.environ['SystemRoot']) / 'System32' / 'msiexec.exe')
    parameters = subprocess.list2cmdline(['/i', str(installer), '/passive', '/norestart',
                                         '/L*v', str(cache / 'node-install.log')])
    code, detail = _run_elevated_installer(executable, status_callback=status,
                                          parameters=parameters, component='Node.js')
    if code not in {0, 1638, 3010}:
        raise RuntimeError(detail or f'Node.js 安装失败（退出码 {code}）。')
    node = find_node()
    if not node:
        raise RuntimeError('Node.js 安装已结束，请按系统提示重启后重试。')
    return node


def configure(status=lambda text: None):
    if not _install_lock.acquire(blocking=False):
        raise RuntimeError('浏览器组件正在配置，请等待当前任务完成。')
    try:
        root = runtime_dir()
        root.mkdir(parents=True, exist_ok=True)
        node = find_node() or _install_node(root, status)
        npm = Path(node).resolve().parent / 'node_modules' / 'npm' / 'bin' / 'npm-cli.js'
        if not npm.is_file():
            raise RuntimeError('当前 Node.js 缺少 npm，请修复 Node.js 安装后重试。')
        status('正在配置浏览器连接组件，不会下载浏览器内核…')
        env = dict(os.environ)
        env.pop('PLAYWRIGHT_MCP_EXTENSION_TOKEN', None)
        env['PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD'] = '1'
        env['PATH'] = str(Path(node).resolve().parent) + os.pathsep + env.get('PATH', '')
        result = run([node, str(npm), 'install', '--prefix', str(root), '--no-save',
                      '--package-lock=false', '--ignore-scripts', '--no-audit', '--no-fund',
                      '--registry=https://registry.npmjs.org', '--fetch-retries=1',
                      '--fetch-timeout=30000', f'@playwright/mcp@{MCP_VERSION}'], env=env, cwd=root)
        if result.returncode:
            raise RuntimeError('连接组件下载或安装失败，请检查网络后重试。')
        cli = root / 'node_modules' / '@playwright' / 'mcp' / 'cli.js'
        result = run([node, str(cli), '--version'], cwd=root)
        if result.returncode or MCP_VERSION not in result.stdout or not ready():
            raise RuntimeError('连接组件安装验证失败，请重试配置。')
        from launcher_app.browser.browser_agent import close
        close()
        return '浏览器组件已就绪。填写扩展令牌并开启连接后，即可使用。'
    finally:
        _install_lock.release()
