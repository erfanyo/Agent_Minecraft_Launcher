import os
import unittest

from paths import managed_runtime_dir


class ManagedRuntimePathTests(unittest.TestCase):
    def test_ascii_windows_game_dir_keeps_portable_runtime(self):
        self.assertEqual(
            managed_runtime_dir(r"D:\Games\.minecraft", {}, "win32"),
            os.path.join(r"D:\Games\.minecraft", "runtime"),
        )

    def test_non_ascii_windows_game_dir_uses_local_app_data(self):
        result = managed_runtime_dir(
            r"D:\全体目光向我看齐 我是傻逼\.minecraft",
            {"LOCALAPPDATA": r"C:\Users\test\AppData\Local"}, "win32")
        self.assertEqual(result, r"C:\Users\test\AppData\Local\AMCL\runtime")

    def test_non_ascii_user_profile_falls_back_to_public_documents(self):
        result = managed_runtime_dir(
            r"D:\中文\.minecraft",
            {"LOCALAPPDATA": r"C:\Users\中文\AppData\Local",
             "PUBLIC": r"C:\Users\Public"}, "win32")
        self.assertEqual(result, r"C:\Users\Public\Documents\AMCL\runtime")

    def test_runtime_override_wins(self):
        result = managed_runtime_dir(
            r"D:\中文\.minecraft", {"AML_RUNTIME_DIR": r"E:\Java"}, "win32")
        self.assertEqual(result, os.path.abspath(r"E:\Java"))


if __name__ == "__main__":
    unittest.main()
