import hashlib
import json
import zipfile
from unittest.mock import patch

import pytest

import launcher_app.resources.curseforge as curseforge
from launcher_app.resources.modpack import _download_cf_files


def test_api_redirect_does_not_forward_key():
    from unittest.mock import MagicMock
    response = MagicMock(status_code=302)
    with patch.object(curseforge, '_headers', return_value={'x-api-key': 'test'}), \
            patch.object(curseforge.requests, 'get', return_value=response) as get:
        with pytest.raises(curseforge.CurseForgeError, match='重定向'):
            curseforge._get_payload('/mods/10')
        assert get.call_args.kwargs['allow_redirects'] is False


def records(class_id=6, distribution=True):
    entry = {'projectID': 10, 'fileID': 20, 'required': True}
    file = {'id': 20, 'modId': 10, 'fileName': 'example.jar',
            'downloadUrl': 'https://edge.forgecdn.net/files/1/2/example.jar',
            'hashes': [{'algo': 1, 'value': hashlib.sha1(b'ok').hexdigest()}]}
    project = {'id': 10, 'classId': class_id, 'allowModDistribution': distribution}
    return entry, file, project


@pytest.mark.parametrize('class_id,folder', [(6, 'mods'), (12, 'resourcepacks'), (6552, 'shaderpacks')])
def test_exact_version_routing_and_cdn_auth(tmp_path, class_id, folder):
    entry, file, project = records(class_id)
    with patch('launcher_app.resources.curseforge._headers', return_value={'x-api-key': 'test'}), patch('launcher_app.resources.curseforge.download_file') as download:
        curseforge.download_pack_file(entry, file, project, str(tmp_path))
    assert download.call_args.args[1] == str(tmp_path / folder / 'example.jar')
    assert download.call_args.kwargs['headers'] == {}
    assert download.call_args.kwargs['sha1'] == file['hashes'][0]['value']


def test_restricted_file_tries_candidates_then_reuses_verified_local_file(tmp_path):
    entry, file, project = records(distribution=False)
    with patch('launcher_app.resources.curseforge._headers', return_value={'x-api-key': 'test'}), \
         patch('launcher_app.resources.curseforge.download_file', side_effect=__import__('requests').ConnectionError()) as download:
        with pytest.raises(curseforge.CurseForgeError, match='作者限制第三方分发'):
            curseforge.download_pack_file(entry, file, project, str(tmp_path))
        download.assert_not_called()
        download.reset_mock()
        target = tmp_path / 'mods' / 'example.jar'
        target.parent.mkdir()
        target.write_bytes(b'ok')
        assert curseforge.download_pack_file(entry, file, project, str(tmp_path)) == 'example.jar'
        download.assert_not_called()


@pytest.mark.parametrize('filename,url', [('../escape.jar', 'https://edge.forgecdn.net/f.jar'),
                                         ('safe.jar', 'https://untrusted.example/file')])
def test_api_paths_and_key_destination_are_validated(tmp_path, filename, url):
    entry, file, project = records()
    file.update(fileName=filename, downloadUrl=url)
    with patch('launcher_app.resources.curseforge.download_file') as download:
        with pytest.raises((ValueError, curseforge.CurseForgeError)):
            curseforge.download_pack_file(entry, file, project, str(tmp_path))
        download.assert_not_called()


def test_manifest_downloads_exact_ids_and_reports_incomplete(tmp_path):
    entry, file, project = records()
    with patch('launcher_app.resources.curseforge.configured', return_value=True), \
         patch('launcher_app.resources.curseforge.get_pack_metadata', return_value=({20: file}, {10: project})), \
         patch('launcher_app.resources.curseforge.download_pack_file', return_value='example.jar') as download:
        _download_cf_files({'files': [entry, entry]}, str(tmp_path))
        download.assert_called_once_with(entry, file, project, str(tmp_path))
        download.side_effect = RuntimeError('blocked')
        with pytest.raises(RuntimeError, match='1 个文件未装好'):
            _download_cf_files({'files': [entry]}, str(tmp_path))


def test_full_cf_import_completes_only_after_manifest_files(tmp_path):
    from launcher_app.resources.modpack import import_modpack
    entry, file, project = records()
    archive = tmp_path / 'pack.zip'
    with zipfile.ZipFile(archive, 'w') as package:
        package.writestr('manifest.json', json.dumps({'name': 'Pack', 'minecraft': {
            'version': '1.20.1', 'modLoaders': [{'id': 'forge-47.3.22', 'primary': True}]},
            'files': [entry]}))
        package.writestr('overrides/config/test.txt', 'configuration')
    root = tmp_path / 'game'
    def download(entry, file, project, folder):
        target = __import__('pathlib').Path(folder, 'mods', file['fileName'])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'ok')
        return target.name
    with patch('launcher_app.resources.modpack._ensure_base'), patch('launcher_app.resources.modpack.install_loader', return_value=None), \
         patch('launcher_app.resources.curseforge.configured', return_value=True), \
         patch('launcher_app.resources.curseforge.get_pack_metadata', return_value=({20: file}, {10: project})), \
         patch('launcher_app.resources.curseforge.download_pack_file', side_effect=download):
        assert import_modpack(str(archive), str(root)) == 'Pack'
    folder = root / 'versions' / 'Pack'
    assert (folder / 'mods' / 'example.jar').read_bytes() == b'ok'
    assert (folder / 'config' / 'test.txt').read_text() == 'configuration'
    assert not (root / 'versions' / '_imports' / 'Pack.json').exists()


def test_null_url_builds_exact_cdn_path_and_mirror_has_no_key(tmp_path):
    import requests
    entry, file, project = records(distribution=True)
    entry['fileID'] = file['id'] = 5765892
    file.update(fileName='file with spaces.jar', downloadUrl=None)
    def download(url, *args, **kwargs):
        if 'mcimirror.top' not in url:
            raise requests.ConnectionError('offline')
        assert kwargs['headers'] == {}
    with patch('launcher_app.resources.curseforge._headers', return_value={'x-api-key': 'private'}), \
         patch('launcher_app.resources.curseforge._get', return_value=None), \
         patch('launcher_app.resources.curseforge.download_file', side_effect=download) as fetch:
        assert curseforge.download_pack_file(entry, file, project, str(tmp_path)) == 'file with spaces.jar'
    assert fetch.call_args_list[0].args[0] == 'https://edge.forgecdn.net/files/5765/892/file%20with%20spaces.jar'
    assert fetch.call_count == 3


def test_cancel_does_not_start_next_candidate(tmp_path):
    from launcher_app.core.task_context import TaskCancelled
    entry, file, project = records()
    with patch('launcher_app.resources.curseforge._headers', return_value={}), \
         patch('launcher_app.resources.curseforge.download_file', side_effect=TaskCancelled) as download:
        with pytest.raises(TaskCancelled):
            curseforge.download_pack_file(entry, file, project, str(tmp_path))
    assert download.call_count == 1


def test_manual_reception_rejects_wrong_bytes_then_copies_correct_file(tmp_path):
    from launcher_app.resources.cf_manual import receive_downloads
    source, instance = tmp_path / 'downloads', tmp_path / 'instance'
    source.mkdir()
    item = {'filename': 'example.jar', 'folder': 'mods', 'sha1': hashlib.sha1(b'ok').hexdigest()}
    target = source / 'example.jar'
    target.write_bytes(b'wrong version')
    assert receive_downloads(str(instance), [item], [str(source)]) == [item]
    assert not (instance / 'mods' / 'example.jar').exists()
    target.write_bytes(b'ok')
    assert receive_downloads(str(instance), [item], [str(source)]) == []
    assert target.read_bytes() == b'ok'
    assert (instance / 'mods' / 'example.jar').read_bytes() == b'ok'


def test_missing_report_contains_names_links_and_clears_after_retry(tmp_path):
    from launcher_app.resources.cf_manual import REPORT_NAME
    entry, file, project = records()
    with patch('launcher_app.resources.curseforge.configured', return_value=True), \
         patch('launcher_app.resources.curseforge.get_pack_metadata', return_value=({20: file}, {10: project})), \
         patch('launcher_app.resources.curseforge.download_pack_file', side_effect=RuntimeError('offline')) as download:
        with pytest.raises(RuntimeError, match='CF_MISSING_REPORT'):
            _download_cf_files({'files': [entry]}, str(tmp_path))
        report = json.loads((tmp_path / REPORT_NAME).read_text(encoding='utf-8'))
        assert report[0]['filename'] == 'example.jar'
        assert report[0]['url'] == 'https://www.curseforge.com/projects/10/files/20'
        download.side_effect = None
        download.return_value = 'example.jar'
        _download_cf_files({'files': [entry]}, str(tmp_path))
        assert not (tmp_path / REPORT_NAME).exists()


def test_manual_accepts_browser_duplicate_filename(tmp_path):
    from launcher_app.resources.cf_manual import receive_downloads
    source = tmp_path / 'downloads'
    source.mkdir()
    (source / 'example (1).jar').write_bytes(b'ok')
    item = {'filename': 'example.jar', 'folder': 'mods', 'sha1': hashlib.sha1(b'ok').hexdigest()}
    assert receive_downloads(str(tmp_path / 'instance'), [item], [str(source)]) == []
