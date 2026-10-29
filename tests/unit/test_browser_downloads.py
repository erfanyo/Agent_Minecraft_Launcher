import zipfile
from pathlib import Path

from launcher_app.resources.browser_downloads import ArchiveInbox


def archive(path, name='manifest.json'):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr(name, '{}')


def test_only_new_complete_archives_once_and_original_preserved(tmp_path):
    archive(tmp_path/'old.zip')
    inbox = ArchiveInbox(tmp_path)
    (tmp_path/'pending.zip.crdownload').write_bytes(b'incomplete')
    assert inbox.poll() == []
    archive(tmp_path/'new.zip')
    before = (tmp_path/'new.zip').read_bytes()
    result = inbox.poll()
    assert [r['name'] for r in result] == ['new.zip']
    assert len(result[0]['sha256']) == 64
    assert inbox.poll() == []
    assert (tmp_path/'new.zip').read_bytes() == before


def test_partial_final_name_is_not_completion_then_recovers(tmp_path):
    inbox = ArchiveInbox(tmp_path)
    (tmp_path/'pack.zip').write_bytes(b'PK unfinished')
    assert inbox.poll() == []
    archive(tmp_path/'pack.zip')
    assert len(inbox.poll()) == 1


def test_unsafe_members_never_received(tmp_path):
    inbox = ArchiveInbox(tmp_path)
    archive(tmp_path/'unsafe.zip', '../escape.exe')
    assert inbox.poll() == []


def test_corrupt_crc_does_not_block_other_downloads(tmp_path):
    inbox = ArchiveInbox(tmp_path)
    bad = tmp_path/'bad.zip'
    archive(bad)
    bad.write_bytes(bad.read_bytes().replace(b'{}', b'[]', 1))
    archive(tmp_path/'good.zip')
    assert [item['name'] for item in inbox.poll()] == ['good.zip']


def test_existing_file_update_can_be_received(tmp_path):
    archive(tmp_path/'pack.zip')
    inbox = ArchiveInbox(tmp_path)
    archive(tmp_path/'pack.zip', 'updated.txt')
    assert len(inbox.poll()) == 1


def test_windows_writer_is_not_treated_as_complete(tmp_path):
    import os
    import pytest
    if os.name != 'nt':
        pytest.skip('Windows sharing semantics')
    inbox = ArchiveInbox(tmp_path)
    path = tmp_path/'pack.zip'
    archive(path)
    with path.open('r+b'):
        assert inbox.poll() == []
    assert len(inbox.poll()) == 1
