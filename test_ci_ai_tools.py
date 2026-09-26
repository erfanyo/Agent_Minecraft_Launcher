"""CI coverage for AI tool exposure, dispatch, permission, and download wiring."""
import unittest
from unittest.mock import Mock, patch

import agent_tools
from assistant import build_executor, mount_tools_for
from settings import DEFAULTS


class AIToolContractTests(unittest.TestCase):
    def settings(self, **overrides):
        result = dict(DEFAULTS)
        result.update(ai_permission="launcher_write", ai_confirmation_mode="per_action",
                      mcp_clients=[])
        result.update(overrides)
        return result

    def test_common_tasks_mount_expected_tools(self):
        for prompt, expected in (
            ("查找 1.20.1 的 Mod", "search_mods"),
            ("下载并安装 Mod 到实例", "install_mod"),
            ("创建 1.21.1 实例", "install_instance"),
            ("检查崩溃日志", "read_crash_report"),
        ):
            with self.subTest(prompt=prompt):
                names = [row["function"]["name"] for row in mount_tools_for(prompt)]
                self.assertIn(expected, names)
                self.assertEqual(len(names), len(set(names)))

    def test_read_tool_filters_unknown_arguments(self):
        with patch.object(agent_tools, "list_instances", return_value="instances") as tool:
            execute = build_executor(self.settings(ai_permission="read_only"))
            self.assertEqual(execute("list_instances", {"made_up": "ignored"}), "instances")
        tool.assert_called_once_with()
        self.assertIn("未知工具", execute("unknown_ci_tool", {}))

    def test_write_tool_requires_confirmation_and_permission(self):
        args = {"version": "1.20.1", "loader": "fabric"}
        with patch.object(agent_tools, "install_instance", return_value="installed") as tool:
            self.assertIn("需要你确认", build_executor(self.settings())("install_instance", args))
            self.assertIn("用户取消", build_executor(
                self.settings(), confirm_action=Mock(return_value=False))("install_instance", args))
            tool.assert_not_called()

    def test_confirmed_install_instance_receives_progress(self):
        progress = Mock()
        confirm = Mock(return_value=True)
        with patch.object(agent_tools, "install_instance", autospec=True,
                          return_value="installed") as tool, \
             patch("ai_action_log.record"):
            result = build_executor(self.settings(), progress_cb=progress,
                                    confirm_action=confirm)(
                "install_instance", {"version": "1.20.1", "loader": "fabric",
                                     "invented": "ignored"})
        self.assertEqual(result, "installed")
        self.assertEqual(tool.call_args.kwargs["progress_callback"], progress)
        self.assertNotIn("invented", tool.call_args.kwargs)
        confirm.assert_called_once()

    def test_install_mod_backs_up_before_download(self):
        events = []

        def backup(instance):
            events.append("backup")
            return "saved"

        def install(instance, slug, progress_callback=None):
            events.append("install")
            return "installed"

        with patch.object(agent_tools, "backup_instance", side_effect=backup), \
             patch.object(agent_tools, "install_mod", side_effect=install), \
             patch("ai_action_log.record"):
            result = build_executor(self.settings(), confirm_action=Mock(return_value=True))(
                "install_mod", {"instance": "demo", "slug": "sodium"})
        self.assertEqual(events, ["backup", "install"])
        self.assertIn("installed", result)
        self.assertIn("saved", result)


if __name__ == "__main__":
    unittest.main()
