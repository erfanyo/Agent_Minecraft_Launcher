from unittest.mock import patch
from launcher_app.ai.run_retention_ui import RunRetentionPanel


def test_settings_values_and_manual_cleanup(qtbot, tmp_path):
    panel = RunRetentionPanel({})
    qtbot.addWidget(panel)
    assert panel.values() == {'ai_run_log_auto_cleanup': True,
                              'ai_run_log_retention_days': 30, 'ai_run_log_max_mb': 100}
    panel.auto.setChecked(False)
    panel.days.setValue(7)
    panel.capacity.setValue(20)
    with patch('paths.data_dir', return_value=str(tmp_path)), \
         patch('launcher_app.ai.run_retention.cleanup_run_logs', return_value={
             'deleted': 2, 'freed_bytes': 1024 * 1024, 'remaining_bytes': 0,
             'over_limit': False, 'failed': 0}) as clean:
        panel.clean.click()
        qtbot.waitUntil(lambda: panel.clean.isEnabled(), timeout=5000)
    assert '2 份' in panel.status.text()
    assert clean.call_args.args[0]['ai_run_log_retention_days'] == 7
