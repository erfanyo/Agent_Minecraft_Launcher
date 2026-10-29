import hashlib
import subprocess
from unittest.mock import patch

import pytest
import launcher_app.browser.browser_setup as setup


def fake_run(args, **kwargs):
    return subprocess.CompletedProcess(args, 0, stdout=setup.MCP_VERSION, stderr='')


def test_existing_node_does_not_request_elevation(tmp_path):
    node = tmp_path / 'node.exe'
    npm = tmp_path / 'node_modules/npm/bin/npm-cli.js'
    npm.parent.mkdir(parents=True)
    npm.write_text('')
    with patch.object(setup, 'runtime_dir', return_value=tmp_path / 'runtime'), \
         patch.object(setup, 'find_node', return_value=str(node)), \
         patch.object(setup, '_install_node') as install, \
         patch.object(setup, 'run', side_effect=fake_run) as run, \
         patch.object(setup, 'ready', return_value=True), patch('launcher_app.browser.browser_agent.close'):
        assert '已就绪' in setup.configure()
    install.assert_not_called()
    args = run.call_args_list[0].args[0]
    assert '--ignore-scripts' in args
    assert f'@playwright/mcp@{setup.MCP_VERSION}' in args
    assert run.call_args_list[0].kwargs['env']['PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD'] == '1'


def test_failed_configuration_releases_lock_for_retry(tmp_path):
    with patch.object(setup, 'runtime_dir', return_value=tmp_path), \
         patch.object(setup, 'find_node', return_value=None), \
         patch.object(setup, '_install_node', side_effect=RuntimeError('用户取消了系统授权')):
        for _ in range(2):
            with pytest.raises(RuntimeError, match='取消'):
                setup.configure()
    assert not setup._install_lock.locked()


@pytest.mark.parametrize('valid_hash,trusted', [(False, True), (True, False)])
def test_unverified_installer_never_elevates(tmp_path, valid_hash, trusted):
    if setup.os.name != 'nt':
        pytest.skip('Windows MSI installation')
    data = b'installer'
    digest = hashlib.sha256(data).hexdigest() if valid_hash else '0' * 64
    name = f'node-v{setup.NODE_VERSION}-x64.msi'
    def download(url, path):
        from pathlib import Path
        Path(path).write_bytes(data)
    with patch.object(setup, 'NODE_SHA256', {'x64': digest}), \
         patch.object(setup.platform, 'machine', return_value='AMD64'), \
         patch('launcher_app.resources.downloader.download_file', side_effect=download), \
         patch('launcher_app.runtime.windows_runtime_support._trusted_signature', return_value=(trusted, '')), \
         patch('launcher_app.runtime.windows_runtime_support._run_elevated_installer') as elevate:
        with pytest.raises(RuntimeError, match='校验|签名'):
            setup._install_node(tmp_path, lambda text: None)
        elevate.assert_not_called()


def test_cancelled_uac_does_not_report_success(tmp_path):
    if setup.os.name != 'nt':
        pytest.skip('Windows MSI installation')
    data = b'installer'
    name = f'node-v{setup.NODE_VERSION}-x64.msi'
    def download(url, path):
        from pathlib import Path
        Path(path).write_bytes(data)
    with patch.object(setup, 'NODE_SHA256', {'x64': hashlib.sha256(data).hexdigest()}), \
         patch.object(setup.platform, 'machine', return_value='AMD64'), \
         patch('launcher_app.resources.downloader.download_file', side_effect=download), \
         patch('launcher_app.runtime.windows_runtime_support._trusted_signature', return_value=(True, '')), \
         patch('launcher_app.runtime.windows_runtime_support._run_elevated_installer', return_value=(None, '用户取消了系统授权')) as elevate:
        with pytest.raises(RuntimeError, match='取消'):
            setup._install_node(tmp_path, lambda text: None)
    assert elevate.call_args.kwargs['component'] == 'Node.js'
    assert '/passive' in elevate.call_args.kwargs['parameters']
