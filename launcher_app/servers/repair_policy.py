"""Pure decisions for repair polling; no Qt, process control or file writes.

Startup readiness is not evidence of entering a world or gameplay correctness.
The caller owns confirmation, reversible changes and asynchronous execution.
"""
from enum import Enum


class RepairAction(Enum):
    WAIT = 'wait'
    READY = 'ready'
    ABORT_AND_DIAGNOSE = 'abort_and_diagnose'
    DIAGNOSE = 'diagnose'


def poll_action(repair, server_id, state):
    if not repair or repair['id'] != server_id or repair['processing']:
        return RepairAction.WAIT
    if not state or state.get('sessionId') != repair.get('session'):
        return RepairAction.WAIT
    if repair.get('ready') and state.get('running'):
        return RepairAction.READY
    if repair.get('startup_failed') and state.get('running'):
        return RepairAction.ABORT_AND_DIAGNOSE
    if state.get('running') or state.get('exitCode') is None:
        return RepairAction.WAIT
    return RepairAction.DIAGNOSE


def client_only_candidates(diagnosis, attempted):
    """Preserve the existing conservative evidence filter and candidate order."""
    return [row for row in diagnosis.get('suggestions', [])
            if row.get('level') in ('high', 'medium')
            and ('客户端类' in row.get('reason', '')
                 or '仅客户端' in row.get('reason', ''))
            and row.get('file') not in attempted]
