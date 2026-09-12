import json
import os
import tempfile
import unittest
from unittest.mock import patch

import updater


class UpdaterRollbackTests(unittest.TestCase):
    def test_update_script_keeps_backup_and_waits_for_startup_marker(self):
        with tempfile.TemporaryDirectory() as root:
            exe = os.path.join(root, "AgentMinecraftLauncher.exe")
            new = os.path.join(root, "AMCL", "update", "AgentMinecraftLauncher.exe")
            bat = os.path.join(root, "AMCL", "update", "update.bat")
            os.makedirs(os.path.dirname(new))
            open(exe, "wb").close()
            open(new, "wb").close()

            updater.make_update_bat(exe, new, bat, current_pid=1234)
            with open(bat, encoding="utf-8") as f:
                script = f.read()

            self.assertIn(".update-backup", script)
            self.assertIn("startup_timeout", script)
            self.assertIn("for /l %%i in (1,1,90)", script)
            self.assertIn("chcp 65001", script)
            self.assertIn("taskkill /f /pid 1234", script)
            staged = os.path.join(root, "AMCL", "update", "pending-update.staged.json")
            with open(staged, encoding="utf-8") as f:
                marker = json.load(f)["marker"]
            self.assertRegex(marker, r"^startup-ok-[0-9a-f]{32}\.marker$")

    def test_new_window_confirms_only_a_safe_pending_marker(self):
        with tempfile.TemporaryDirectory() as root:
            update = os.path.join(root, "AMCL", "update")
            os.makedirs(update)
            marker = "startup-ok-" + "a" * 32 + ".marker"
            with open(os.path.join(update, "pending-update.json"), "w", encoding="utf-8") as f:
                json.dump({"marker": marker}, f)
            self.assertTrue(updater.confirm_pending_update(root))
            self.assertTrue(os.path.isfile(os.path.join(update, marker)))

            os.remove(os.path.join(update, marker))
            with open(os.path.join(update, "pending-update.json"), "w", encoding="utf-8") as f:
                json.dump({"marker": "..\\outside.txt"}, f)
            self.assertFalse(updater.confirm_pending_update(root))
            self.assertFalse(os.path.exists(os.path.join(root, "outside.txt")))

    def test_rollback_notice_is_plain_language_and_consumed_once(self):
        with tempfile.TemporaryDirectory() as root:
            update = os.path.join(root, "AMCL", "update")
            os.makedirs(update)
            notice = os.path.join(update, "rollback.notice")
            with open(notice, "w", encoding="ascii") as f:
                f.write("startup_timeout")
            message = updater.consume_rollback_notice(root)
            self.assertIn("已自动恢复", message)
            self.assertIn("游戏、存档和设置没有变化", message)
            self.assertEqual(updater.consume_rollback_notice(root), "")

    def test_incomplete_or_non_executable_download_is_removed(self):
        class Response:
            headers = {"content-length": "4"}

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size):
                yield b"nope"

        with tempfile.TemporaryDirectory() as root, patch("updater.requests.get", return_value=Response()):
            target = os.path.join(root, "new.exe")
            with self.assertRaisesRegex(ValueError, "不是有效"):
                updater.download_to("https://example.invalid/app.exe", target, expected_size=4)
            self.assertFalse(os.path.exists(target))


if __name__ == "__main__":
    unittest.main()
