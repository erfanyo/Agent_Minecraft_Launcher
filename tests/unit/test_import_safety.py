import io
import json
import zipfile
from unittest.mock import patch

import pytest

from launcher_app.resources.import_safety import prepare_import


def pack(path, entries):
    with zipfile.ZipFile(path, 'w') as archive:
        for name, value in entries.items():
            archive.writestr(name, value)


def test_wrapper_keeps_original_and_checks_inner(tmp_path):
    content = io.BytesIO()
    pack(content, {'manifest.json': json.dumps({'manifestType': 'minecraftModpack',
        'minecraft': {'version': '1.12.2'}, 'files': []})})
    original = tmp_path / 'outer.zip'
    pack(original, {'actual.zip': content.getvalue()})
    before = original.read_bytes()
    result = prepare_import(original, scan_enabled=False)
    assert len(result['layers']) == 2
    assert original.read_bytes() == before
    assert result['path'] != str(original)
    assert result['antivirus']['status'] == 'not_requested'


def test_unsafe_inner_rejected(tmp_path):
    content = io.BytesIO()
    pack(content, {'../evil.exe': b'x'})
    original = tmp_path / 'outer.zip'
    pack(original, {'actual.zip': content.getvalue()})
    with pytest.raises(ValueError, match='unsafe'):
        prepare_import(original, scan_enabled=False)
    assert original.exists()


def test_alert_is_preserved(tmp_path):
    original = tmp_path / 'pack.zip'
    pack(original, {'manifest.json': '{}'})
    with patch('launcher_app.resources.antivirus.scan_available_archive', return_value={
            'status': 'attention_required', 'message': 'alert'}) as scan:
        result = prepare_import(original)
    scan.assert_called_once_with(str(original))
    assert result['antivirus']['status'] == 'attention_required'


def test_file_change_during_av_rejected(tmp_path):
    original = tmp_path / 'pack.zip'
    pack(original, {'manifest.json': '{}'})
    def change(_):
        original.write_bytes(b'changed')
        return {'status': 'no_detection_reported', 'message': 'clean'}
    with patch('launcher_app.resources.antivirus.scan_available_archive', side_effect=change):
        with pytest.raises(ValueError, match='发生变化'):
            prepare_import(original)


def test_curseforge_overrides_do_not_replace_manifest_root(tmp_path):
    from launcher_app.ui.smart_import import scan_import_source, materialize_component
    original = tmp_path / 'pack.zip'
    pack(original, {'manifest.json': json.dumps({'manifestType': 'minecraftModpack',
        'minecraft': {'version': '1.12.2', 'modLoaders': [
            {'id': 'forge-14.23.5.2860', 'primary': True}]},
        'files': [{'projectID': 1, 'fileID': 2}]}),
        'overrides/mods/example.jar': b'jar', 'overrides/options.txt': 'test',
        'overrides/resourcepacks/example.txt': 'test'})
    report = scan_import_source(original)
    client = next(c for c in report['components'] if c['type'] == 'client')
    assert client['root'] == ''
    assert client['minecraftVersion'] == '1.12.2'
    assert client['loaderVersion'] == '14.23.5.2860'
    sliced = tmp_path / 'client.zip'
    materialize_component(report, client, sliced)
    with zipfile.ZipFile(sliced) as z:
        assert 'manifest.json' in z.namelist()
        assert 'overrides/mods/example.jar' in z.namelist()
