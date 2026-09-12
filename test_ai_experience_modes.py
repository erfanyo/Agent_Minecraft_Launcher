import json
import unittest
from unittest.mock import Mock, patch

import agent_tools
from ai_action_log import preview
from ai_actions import plain_language_instructions
from assistant import build_executor
from settings import DEFAULTS


class AIExperienceModeTests(unittest.TestCase):
    def settings(self, **values):
        result = dict(DEFAULTS)
        result.update(ai_permission='launcher_write', ai_confirmation_mode='backup_continue',
                      ai_response_style='plain', mcp_clients=[])
        result.update(values)
        return result

    def test_plain_mode_describes_outcomes_and_migration_decision(self):
        text = plain_language_instructions(self.settings())
        self.assertIn('能玩的实例', text)
        self.assertIn('创建一个新的可玩实例', text)
        self.assertIn('不要先用 ask_user 重复问', text)
        self.assertIn('最多给两个', text)
        self.assertNotIn('SHA', preview('repair_instance_core', {'instance': 'demo'}, 'plain'))
        self.assertIn('存档和 Mod 会保留', preview('repair_instance_core', {'instance': 'demo'}, 'plain'))

    def test_technical_mode_keeps_detailed_evidence(self):
        text = plain_language_instructions(self.settings(ai_response_style='technical'))
        self.assertIn('日志证据', text)
        self.assertIn('版本号', text)

    def test_plain_cross_version_mod_wording_matches_reversible_action(self):
        text = preview('set_mod_enabled', {
            'instance': 'demo', 'filename': 'old.jar', 'enabled': False,
            'reason': 'wrong_game_version'}, 'plain')
        self.assertIn('另一个游戏版本', text)
        self.assertIn('从本次启动中移出', text)
        self.assertIn('原文件仍会保留', text)
        self.assertNotIn('删除', text)

    def test_backup_continue_snapshots_once_and_does_not_prompt_routine_repairs(self):
        confirm = Mock(return_value=False)
        notice = Mock()
        with patch.object(agent_tools, 'snapshot_instance', return_value='{"snapshot_id":"safe"}') as snapshot, \
             patch.object(agent_tools, 'set_mod_enabled', return_value='changed') as change, \
             patch('ai_action_log.record'):
            execute = build_executor(self.settings(), confirm_action=confirm, notice_cb=notice)
            self.assertEqual(execute('set_mod_enabled',
                                     {'instance': 'demo', 'filename': 'a.jar', 'enabled': False}), 'changed')
            self.assertEqual(execute('set_mod_enabled',
                                     {'instance': 'demo', 'filename': 'b.jar', 'enabled': False}), 'changed')
        self.assertEqual(snapshot.call_count, 1)
        self.assertEqual(change.call_count, 2)
        confirm.assert_not_called()
        self.assertEqual(notice.call_count, 2)
        self.assertIn('正在保存当前实例', notice.call_args_list[0].args[0])
        self.assertIn('完整恢复点', notice.call_args_list[1].args[0])

    def test_migration_still_asks_in_backup_continue_mode(self):
        confirm = Mock(return_value=False)
        execute = build_executor(self.settings(), confirm_action=confirm)
        result = execute('install_instance', {'version': '1.21.1'})
        self.assertIn('用户取消', result)
        confirm.assert_called_once()
        self.assertIn('新的独立游戏实例', confirm.call_args.args[1])

    def test_verified_core_is_never_repaired_or_confirmed(self):
        confirm = Mock(return_value=True)
        verified = json.dumps({'status': 'verified'}, ensure_ascii=False)
        with patch.object(agent_tools, 'inspect_instance_core', return_value=verified), \
             patch.object(agent_tools, 'repair_instance_core', return_value='should not run') as repair:
            result = build_executor(self.settings(ai_confirmation_mode='per_action'),
                                    confirm_action=confirm)(
                'repair_instance_core', {'instance': 'demo'})
        self.assertIn('没有执行核心修补', result)
        confirm.assert_not_called()
        repair.assert_not_called()

    def test_verified_files_still_allow_runtime_loader_repair(self):
        confirm = Mock(return_value=False)
        verified = json.dumps({'status': 'verified'}, ensure_ascii=False)
        missing = ("Missing or unsupported mandatory dependencies\n"
                   "Mod ID: 'neoforge', Actual version: '[MISSING]'")
        with patch.object(agent_tools, 'inspect_instance_core', return_value=verified), \
             patch.object(agent_tools, 'read_instance_log', return_value=missing), \
             patch.object(agent_tools, 'repair_instance_core', return_value='repaired') as repair:
            result = build_executor(self.settings(ai_confirmation_mode='per_action'),
                                    confirm_action=confirm)(
                'repair_instance_core', {'instance': 'demo'})
        self.assertIn('用户取消', result)
        self.assertIn('加载器关系', confirm.call_args.args[1])
        repair.assert_not_called()

    def test_core_repair_status_reaches_chat_notice(self):
        confirm = Mock(return_value=True)
        notice = Mock()
        issues = json.dumps({'status': 'issues_found'}, ensure_ascii=False)

        def repair(instance, status_callback=None):
            status_callback('正在下载加载器')
            return 'repaired'

        with patch.object(agent_tools, 'inspect_instance_core', return_value=issues), \
             patch.object(agent_tools, 'repair_instance_core', side_effect=repair, autospec=True):
            result = build_executor(self.settings(ai_confirmation_mode='per_action'),
                                    confirm_action=confirm, notice_cb=notice)(
                'repair_instance_core', {'instance': 'demo'})
        self.assertEqual(result, 'repaired')
        self.assertTrue(any('正在下载加载器' in call.args[0]
                            for call in notice.call_args_list))

    def test_headless_caller_does_not_gain_continuous_write(self):
        with patch.object(agent_tools, 'set_mod_enabled', return_value='changed') as change:
            result = build_executor(self.settings())(
                'set_mod_enabled', {'instance': 'demo', 'filename': 'a.jar', 'enabled': False})
        self.assertIn('需要你确认', result)
        change.assert_not_called()


if __name__ == '__main__':
    unittest.main()
