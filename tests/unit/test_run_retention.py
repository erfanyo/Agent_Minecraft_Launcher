import json
import os
from pathlib import Path
from unittest.mock import patch

from launcher_app.ai.run_retention import auto_cleanup, cleanup_run_logs

NOW = 2_000_000_000


def log(root, number, age, finished=True, size=0):
    path = root / (f'{number:032x}' + '.jsonl')
    row = {'schema': 'amcl.agent-run.v1', 'run_id': path.stem,
           'event': 'finish' if finished else 'start'}
    path.write_text((' ' * size) + json.dumps(row) + '\n', encoding='utf-8')
    stamp = NOW - age * 86400
    os.utime(path, (stamp, stamp))
    return path


def test_age_prunes_only_completed_runs(tmp_path):
    expired = log(tmp_path, 1, 31)
    recent = log(tmp_path, 2, 1)
    unfinished = log(tmp_path, 3, 60, finished=False)
    protected = log(tmp_path, 4, 60)
    unknown = tmp_path / 'notes.jsonl'
    unknown.write_text('private note')
    result = cleanup_run_logs({}, tmp_path, now=NOW, protected={protected.stem})
    assert result['deleted'] == 1
    assert not expired.exists()
    assert all(p.exists() for p in (recent, unfinished, protected, unknown))


def test_capacity_removes_oldest_first_even_within_retention(tmp_path):
    oldest = log(tmp_path, 1, 2, size=600_000)
    newest = log(tmp_path, 2, 1, size=600_000)
    result = cleanup_run_logs({'ai_run_log_max_mb': 1}, tmp_path, now=NOW)
    assert result['deleted'] == 1 and not result['over_limit']
    assert not oldest.exists() and newest.exists()


def test_unfinished_files_can_exceed_quota_without_being_deleted(tmp_path):
    active = log(tmp_path, 1, 90, finished=False, size=1_100_000)
    old = log(tmp_path, 2, 1)
    result = cleanup_run_logs({'ai_run_log_max_mb': 1}, tmp_path, now=NOW)
    assert active.exists() and not old.exists()
    assert result['over_limit'] and result['protected'] == 1


def test_bad_record_and_dry_run_are_non_destructive(tmp_path):
    old = log(tmp_path, 1, 90)
    broken = tmp_path / ('f' * 32 + '.jsonl')
    broken.write_text('partial{')
    result = cleanup_run_logs({}, tmp_path, now=NOW, dry_run=True)
    assert result['deleted'] == 1 and old.exists() and broken.exists()


def test_disabled_automatic_cleanup_and_failed_deletion(tmp_path):
    old = log(tmp_path, 1, 90)
    assert auto_cleanup({'ai_run_log_auto_cleanup': False}, tmp_path, force=True) is None
    with patch.object(Path, 'unlink', side_effect=PermissionError):
        result = cleanup_run_logs({}, tmp_path, now=NOW)
    assert old.exists() and result['deleted'] == 0 and result['failed'] == 1


def test_changed_file_is_not_deleted(tmp_path):
    old = log(tmp_path, 1, 90)
    from launcher_app.ai import run_retention
    original = run_retention._completed
    def inspect(path, info):
        result = original(path, info)
        path.write_text('new active contents')
        return result
    with patch.object(run_retention, '_completed', side_effect=inspect):
        result = cleanup_run_logs({}, tmp_path, now=NOW)
    assert old.exists() and result['deleted'] == 0


def test_run_lifecycle_reclaims_expired_logs_and_preserves_current(tmp_path):
    from launcher_app.ai.ai_run import RunLog
    import time
    old = log(tmp_path, 1, 90)
    stamp = time.time() - 90 * 86400
    os.utime(old, (stamp, stamp))
    with patch('launcher_app.ai.ai_run.data_dir', return_value=str(tmp_path)):
        current = RunLog({}, [{'role': 'user', 'content': 'test'}])
        current.write('finish', reason='model_finished')
    assert not old.exists()
    assert Path(current.path).exists()


def test_linked_directory_is_rejected_before_deletion(tmp_path):
    import pytest
    old = log(tmp_path, 1, 90)
    with patch('launcher_app.ai.run_retention._linked', return_value=True):
        with pytest.raises(ValueError):
            cleanup_run_logs({}, tmp_path, now=NOW)
    assert old.exists()
