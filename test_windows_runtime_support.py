import os
import tempfile
import unittest
from unittest.mock import patch

import windows_runtime_support as support


class WindowsRuntimeSupportTests(unittest.TestCase):
    def test_recognizes_java_dll_failure(self):
        self.assertTrue(support.missing_vc_runtime("Error: could not find java.dll"))
        self.assertTrue(support.missing_vc_runtime(
            "Error: Could not find Java SE Runtime Environment."))
        self.assertFalse(support.missing_vc_runtime("openjdk version could not be parsed"))

    def test_downloads_verifies_and_runs_official_installer(self):
        statuses = []
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(support.os, "name", "nt"), \
             patch.object(support, "download_file") as download, \
             patch.object(support, "_trusted_signature", return_value=(True, "")), \
             patch.object(support, "_run_elevated_installer", return_value=(0, "")) as elevate:
            ok, detail = support.install_vc_runtime(
                directory, status_callback=statuses.append)
        self.assertTrue(ok)
        self.assertIn("重启", detail)
        download.assert_called_once()
        self.assertEqual(download.call_args.args[0], support.VC_REDIST_URLS["x64"])
        elevate.assert_called_once_with(
            os.path.join(directory, "vc_redist.x64.exe"), status_callback=statuses.append)
        self.assertTrue(any("系统提示" in message for message in statuses))
        self.assertTrue(any("安装完成" in message for message in statuses))

    def test_rejects_unsigned_installer_before_elevation(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(support.os, "name", "nt"), \
             patch.object(support, "download_file") as download, \
             patch.object(support, "_trusted_signature", return_value=(False, "NotSigned")), \
             patch.object(support, "_run_elevated_installer") as elevate:
            installer = os.path.join(directory, "vc_redist.x64.exe")
            download.side_effect = lambda _url, path, **_kwargs: open(path, "wb").close()
            ok, detail = support.install_vc_runtime(directory)
            self.assertFalse(os.path.exists(installer))
        self.assertFalse(ok)
        self.assertIn("签名验证失败", detail)
        elevate.assert_not_called()

    def test_elevated_installer_reports_progress_until_exit(self):
        class Function:
            def __init__(self, implementation):
                self.implementation = implementation
            def __call__(self, *args):
                return self.implementation(*args)

        waits = iter([258, 258, 258, 258, 258, 0])
        shell = type('Shell', (), {})()
        kernel = type('Kernel', (), {})()
        shell.ShellExecuteExW = Function(
            lambda info: setattr(info._obj, 'hProcess', 123) or 1)
        kernel.WaitForSingleObject = Function(lambda _handle, _ms: next(waits))
        kernel.GetExitCodeProcess = Function(
            lambda _handle, code: setattr(code._obj, 'value', 0) or 1)
        kernel.CloseHandle = Function(lambda _handle: 1)
        statuses = []
        with patch.object(support.os, 'name', 'nt'), \
             patch.object(support.ctypes, 'WinDLL', side_effect=[shell, kernel]):
            code, detail = support._run_elevated_installer(
                r'C:\cache\vc_redist.x64.exe', status_callback=statuses.append)
        self.assertEqual((code, detail), (0, ''))
        self.assertEqual(statuses, ['微软运行组件正在安装…（已等待 5 秒）'])


if __name__ == "__main__":
    unittest.main()
