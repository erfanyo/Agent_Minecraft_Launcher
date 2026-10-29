import hashlib
from pathlib import Path
from launcher_app.resources import import_recovery as recovery
from launcher_app.instances.instance_metadata import atomic_json


def pending_instance(tmp_path):
    instance = tmp_path/'versions'/'Pack'
    instance.mkdir(parents=True)
    source = tmp_path/'original.zip'
    source.write_bytes(b'original archive bytes')
    atomic_json(str(instance.parent/'_imports'/'Pack.json'), {'archive': 'hash'})
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    recovery.remember(instance, source, digest)
    return instance, source, digest


def test_restart_restores_unfinished_import_and_ignore_is_persistent(tmp_path):
    instance, source, digest = pending_instance(tmp_path)
    assert recovery.pending(tmp_path) == []  # this process is still importing
    recovery._active.clear()  # simulate a fresh launcher process
    record = recovery.pending(tmp_path)[0]
    assert record['name'] == 'Pack'
    assert recovery.verify_source(record)
    recovery.ignore(instance)
    recovery._active.clear()
    assert recovery.pending(tmp_path) == []
    assert (instance.parent/'_imports'/'Pack.json').exists()  # NOT marked complete


def test_failed_temporary_source_survives_and_success_clears_attention(tmp_path):
    instance, source, digest = pending_instance(tmp_path)
    recovery.preserve_failed_source(instance, source, digest)
    source.unlink()  # smart-import temporary directory is gone
    record = recovery.pending(tmp_path)[0]
    assert recovery.verify_source(record)
    (instance.parent/'_imports'/'Pack.json').unlink()
    recovery.complete(instance)
    assert recovery.pending(tmp_path) == []


def test_changed_retained_archive_is_not_retried(tmp_path):
    instance, source, digest = pending_instance(tmp_path)
    recovery._active.clear()
    record = recovery.pending(tmp_path)[0]
    source.write_bytes(b'changed')
    assert not recovery.verify_source(record)


def test_corrupt_record_does_not_hide_unfinished_state(tmp_path):
    instance, source, digest = pending_instance(tmp_path)
    recovery._active.clear()
    (instance/recovery.RECORD).write_text('[]', encoding='utf-8')
    assert len(recovery.pending(tmp_path)) == 1
    recovery.ignore(instance)
    assert recovery.pending(tmp_path) == []
