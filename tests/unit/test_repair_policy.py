"""Repair decisions must not touch stale sessions or guess at missing evidence."""
from launcher_app.servers.repair_policy import RepairAction, poll_action, client_only_candidates


def test_old_session_cannot_finish_or_repair_new_attempt():
    repair = {'id': 'server', 'session': 'new', 'processing': False, 'ready': True}
    for state in ({'sessionId': 'old', 'running': True},
                  {'sessionId': 'old', 'exitCode': 1}, None):
        assert poll_action(repair, 'server', state) is RepairAction.WAIT


def test_wait_for_preparation_and_real_process_exit():
    repair = {'id': 'server', 'session': 'current', 'processing': True}
    state = {'sessionId': 'current', 'exitCode': 1}
    assert poll_action(repair, 'server', state) is RepairAction.WAIT
    repair['processing'] = False
    assert poll_action(repair, 'server', state) is RepairAction.DIAGNOSE
    state.pop('exitCode')
    assert poll_action(repair, 'server', state) is RepairAction.WAIT


def test_running_process_is_not_automatically_ready():
    repair = {'id': 'server', 'session': 'current', 'processing': False}
    state = {'sessionId': 'current', 'running': True}
    assert poll_action(repair, 'server', state) is RepairAction.WAIT
    repair['startup_failed'] = True
    assert poll_action(repair, 'server', state) is RepairAction.ABORT_AND_DIAGNOSE
    repair['startup_failed'] = False
    repair['ready'] = True
    assert poll_action(repair, 'server', state) is RepairAction.READY


def test_dependency_failure_is_not_selected_for_client_mod_disabling():
    diagnosis = {'suggestions': [
        {'file': 'content.jar', 'level': 'high', 'reason': '缺少依赖'},
        {'file': 'old.jar', 'level': 'high', 'reason': '仅客户端'},
        {'file': 'guess.jar', 'level': 'low', 'reason': '可能引用客户端类'},
        {'file': 'next.jar', 'level': 'medium', 'reason': '日志指向客户端类'},
    ]}
    assert [r['file'] for r in client_only_candidates(diagnosis, {'old.jar'})] == ['next.jar']
