"""Only fresh evidence from the launched game directory belongs to this run."""
import os
from unittest.mock import patch
from launcher_app.instances.crash_diagnostics import GameRunEvidence, detect_crash, collect_crash_report


def write(path, content, stamp):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    os.utime(path, (stamp, stamp))


def report(path, started_at):
    with patch('settings.load_settings', return_value={}):
        return collect_crash_report(str(path), 0, started_at=started_at)


def test_old_crash_marker_does_not_belong_to_new_run(tmp_path):
    write(tmp_path / 'logs/latest.log', 'OutOfMemoryError old-run-sentinel', 100)
    assert not detect_crash(str(tmp_path), 200)
    assert 'old-run-sentinel' not in report(tmp_path, 200)
    # Existing callers without a run boundary retain the historical behavior.
    assert detect_crash(str(tmp_path))


def test_new_log_marker_detected_even_if_process_exited_zero(tmp_path):
    write(tmp_path / 'logs/latest.log', 'OutOfMemoryError new-run-sentinel', 300)
    assert detect_crash(str(tmp_path), 200)
    assert 'new-run-sentinel' in report(tmp_path, 200)


def test_latest_report_selected_by_time_not_filename(tmp_path):
    write(tmp_path / 'crash-reports/z-old.txt', 'older-report', 250)
    write(tmp_path / 'crash-reports/a-new.txt', 'newest-report', 300)
    result = report(tmp_path, 200)
    assert 'newest-report' in result
    assert 'older-report' not in result


def test_old_reports_do_not_trigger_crash_after_clean_run(tmp_path):
    write(tmp_path / 'crash-reports/old.txt', 'old-report', 100)
    write(tmp_path / 'logs/latest.log', 'Stopping game normally', 300)
    assert not detect_crash(str(tmp_path), 200)
    assert 'old-report' not in report(tmp_path, 200)


def test_run_context_keeps_launched_directory(tmp_path):
    launched, other = tmp_path / 'launched', tmp_path / 'other'
    write(launched / 'logs/latest.log', 'OutOfMemoryError launched-sentinel', 300)
    write(other / 'logs/latest.log', 'wrong-directory-sentinel', 400)
    context = GameRunEvidence(str(launched), 200)
    assert context.has_crash()
    with patch('settings.load_settings', return_value={}):
        result = context.report(0)
    assert 'launched-sentinel' in result
    assert 'wrong-directory-sentinel' not in result


def test_missing_directory_and_log_are_not_crash_evidence(tmp_path):
    assert not detect_crash(str(tmp_path / 'missing'), 200)
    assert '最新日志' not in report(tmp_path / 'missing', 200)
