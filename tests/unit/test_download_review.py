import json
import pytest
from unittest.mock import Mock

from launcher_app.resources import antivirus
from launcher_app.resources.download_review import review_inspection


def test_software_package_is_not_declared_modpack_or_malware_free():
    review = review_inspection({'files': {'AMCL/Launcher.exe': 'hash', 'AMCL/start.cmd': 'hash'}})
    assert review['kind'] == 'unknown-archive'
    assert review['executable_or_script_count'] == 2
    assert review['malware_free_verified'] is False


def test_pack_markers_are_only_candidates():
    review = review_inspection({'files': {'pack/modrinth.index.json': 'hash', 'mods/example.jar': 'hash'}})
    assert review['kind'] == 'modpack-candidate'
    assert review['malware_free_verified'] is False


def test_defender_unavailable_is_not_a_clean_result(tmp_path, monkeypatch):
    path = tmp_path / 'pack.zip'
    path.write_bytes(b'placeholder')
    monkeypatch.setattr(antivirus, 'find_defender', lambda: None)
    assert antivirus.scan_archive(path)['status'] == 'unavailable'


def test_nonzero_defender_code_never_reports_clean_and_no_remediation(tmp_path, monkeypatch):
    path = tmp_path / 'pack.zip'
    path.write_bytes(b'placeholder')
    monkeypatch.setattr(antivirus, 'find_defender', lambda: 'C:/Windows/Trusted/MpCmdRun.exe')
    monkeypatch.setattr('launcher_app.runtime.windows_runtime_support._trusted_signature', lambda p: (True, ''))
    process = Mock(returncode=2)
    process.poll.return_value = 2
    start = Mock(return_value=process)
    monkeypatch.setattr(antivirus.subprocess, 'Popen', start)
    result = antivirus.scan_archive(path)
    assert result['status'] == 'attention_required'
    argv = start.call_args.args[0]
    assert '-DisableRemediation' in argv
    assert argv[argv.index('-ScanType') + 1] == '3'
    assert str(path.resolve()) in argv
    assert not start.call_args.kwargs.get('shell')


def test_unsigned_scanner_is_not_executed(tmp_path, monkeypatch):
    path = tmp_path / 'pack.zip'
    path.write_bytes(b'placeholder')
    monkeypatch.setattr(antivirus, 'find_defender', lambda: 'untrusted.exe')
    monkeypatch.setattr('launcher_app.runtime.windows_runtime_support._trusted_signature', lambda p: (False, ''))
    start = Mock()
    monkeypatch.setattr(antivirus.subprocess, 'Popen', start)
    assert antivirus.scan_archive(path)['status'] == 'unavailable'
    start.assert_not_called()


def test_alert_is_not_overridden_by_fallback(monkeypatch):
    scanner = Mock(return_value={'status': 'attention_required'})
    monkeypatch.setattr(antivirus, 'scan_archive', scanner)
    monkeypatch.setattr(antivirus, 'find_eset', lambda: 'eset.exe')
    assert antivirus.scan_available_archive('pack.zip')['status'] == 'attention_required'
    assert scanner.call_count == 1


def test_unavailable_defender_falls_back_and_preserves_attempt(monkeypatch):
    scanner = Mock(side_effect=[{'status': 'unavailable'}, {'status': 'no_detection_reported'}])
    monkeypatch.setattr(antivirus, 'scan_archive', scanner)
    monkeypatch.setattr(antivirus, 'find_eset', lambda: 'eset.exe')
    result = antivirus.scan_available_archive('pack.zip')
    assert result['previous_attempt']['status'] == 'unavailable'
    assert scanner.call_args.kwargs == {'engine': 'eset'}


@pytest.mark.parametrize('code,state', [(0, 'no_detection_reported'), (1, 'attention_required'),
    (50, 'attention_required'), (10, 'incomplete'), (100, 'incomplete'), (101, 'incomplete')])
def test_eset_results_and_read_only_arguments(tmp_path, monkeypatch, code, state):
    path = tmp_path / 'pack.zip'
    path.write_bytes(b'placeholder')
    monkeypatch.setattr(antivirus, 'find_eset', lambda: 'C:/Trusted/ecls.exe')
    monkeypatch.setattr('launcher_app.runtime.windows_runtime_support._trusted_signature', lambda p: (True, ''))
    process = Mock(returncode=code)
    process.poll.return_value = code
    start = Mock(return_value=process)
    monkeypatch.setattr(antivirus.subprocess, 'Popen', start)
    assert antivirus.scan_archive(path, engine='eset')['status'] == state
    assert '/clean-mode=none' in start.call_args.args[0]
    assert '/arch' in start.call_args.args[0]
