"""The server repair loop asks before each reversible change."""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

from server_center import ServerCenter


class ServerRepairLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_client_mixin_hint_is_confirmed_then_retried(self):
        panel = ServerCenter()
        panel._repair = {'id': 'server-test', 'session': 'one',
                         'processing': True, 'attempted': set(), 'disabled': []}
        server = {'id': 'server-test'}
        diagnosis = {'suggestions': [
            {'file': 'etf.jar', 'name': 'ETF', 'level': 'medium',
             'reason': '崩溃中的客户端类由该 Mod 的 Mixin 注入标记指向',
             'evidence': 'etf'},
            {'file': 'content.jar', 'name': 'Content', 'level': 'high',
             'reason': '日志中该类加载失败', 'evidence': 'missing dependency'},
        ]}
        with patch('server_center.QMessageBox.question',
                   return_value=QMessageBox.StandardButton.Yes), \
                patch('agent_tools.set_server_mod_enabled', return_value='已停用 etf.jar.disabled') as disable, \
                patch('server_center.QTimer.singleShot') as schedule:
            panel._offer_repair(server, diagnosis)
        disable.assert_called_once()
        self.assertEqual(disable.call_args.args[:3], ('server-test', 'etf.jar', False))
        self.assertEqual(panel._repair['disabled'], ['etf.jar'])
        schedule.assert_called_once()
        panel.close()

    def test_non_client_failure_stops_without_mod_changes(self):
        panel = ServerCenter()
        panel._repair = {'id': 'server-test', 'session': 'one',
                         'processing': True, 'attempted': set(), 'disabled': []}
        with patch('agent_tools.set_server_mod_enabled') as disable:
            panel._offer_repair({'id': 'server-test'}, {'suggestions': [
                {'file': 'content.jar', 'level': 'high',
                 'reason': '日志中该类加载失败'}]})
        disable.assert_not_called()
        self.assertIsNone(panel._repair)
        panel.close()

    def test_failed_session_starts_diagnosis_once(self):
        panel = ServerCenter()
        panel._repair = {'id': 'server-test', 'session': 'one',
                         'processing': False, 'attempted': set(),
                         'disabled': [], 'ready': False}
        with patch.object(panel, '_run') as run:
            panel._poll_repair({'id': 'server-test'},
                               {'sessionId': 'one', 'exitCode': 1})
            panel._poll_repair({'id': 'server-test'},
                               {'sessionId': 'one', 'exitCode': 1})
        run.assert_called_once()
        panel.close()

    def test_ready_server_finishes_without_disabling_mods(self):
        panel = ServerCenter()
        panel._repair = {'id': 'server-test', 'session': 'one',
                         'processing': False, 'attempted': set(),
                         'disabled': [], 'ready': True}
        with patch('server_center.QMessageBox.information') as notice, \
                patch.object(panel, '_run') as run:
            panel._poll_repair({'id': 'server-test'},
                               {'sessionId': 'one', 'running': True})
        self.assertIsNone(panel._repair)
        notice.assert_called_once()
        run.assert_not_called()
        panel.close()

    def test_restore_reenables_only_last_tests_mods(self):
        with tempfile.TemporaryDirectory() as root:
            panel = ServerCenter()
            item = QListWidgetItem('Test')
            item.setData(Qt.ItemDataRole.UserRole, {'id': 'server-test', 'path': root})
            panel.list.addItem(item)
            panel.list.setCurrentItem(item)
            panel._last_repair = {'id': 'server-test', 'disabled': ['etf.jar']}
            with patch.object(panel, 'is_running', return_value=False), \
                    patch('server_center.QMessageBox.question',
                          return_value=QMessageBox.StandardButton.Yes), \
                    patch('agent_tools.set_server_mod_enabled',
                          return_value='已启用 etf.jar') as enable:
                panel.restore_repair_mods()
            enable.assert_called_once()
            self.assertEqual(enable.call_args.args[:3], ('server-test', 'etf.jar', True))
            self.assertEqual(panel._last_repair['disabled'], [])
            panel.close()


if __name__ == '__main__':
    unittest.main()
