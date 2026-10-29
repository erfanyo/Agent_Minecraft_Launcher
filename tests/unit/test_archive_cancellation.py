import threading
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from launcher_app.resources.archive_inspection import inspect_archive, sha256
from launcher_app.core.task_context import TaskCancelled, cancel_event


def test_cancel_while_validating_zip_member(tmp_path):
    archive = tmp_path / 'pack.zip'
    with zipfile.ZipFile(archive, 'w') as package:
        package.writestr('mods/example.jar', b'a' * (3 * 1024 * 1024))
    event = threading.Event()
    token = cancel_event.set(event)
    try:
        def progress(done, total):
            event.set()
        with pytest.raises(TaskCancelled):
            inspect_archive(archive, progress_callback=progress)
    finally:
        cancel_event.reset(token)


def test_cancel_whole_archive_fingerprint(tmp_path):
    archive = tmp_path / 'pack.zip'
    archive.write_bytes(b'a' * (3 * 1024 * 1024))
    event = threading.Event()
    token = cancel_event.set(event)
    try:
        with pytest.raises(TaskCancelled):
            sha256(archive, progress_callback=lambda *_: event.set())
    finally:
        cancel_event.reset(token)


def test_import_exposes_scan_progress_and_stops_before_install(tmp_path):
    from launcher_app.resources.modpack import import_modpack
    archive = tmp_path / 'pack.zip'
    with zipfile.ZipFile(archive, 'w') as package:
        package.writestr('mods/example.jar', b'a' * (3 * 1024 * 1024))
    event = threading.Event()
    messages = []
    token = cancel_event.set(event)
    try:
        with patch('launcher_app.resources.modpack._ensure_base') as install:
            with pytest.raises(TaskCancelled):
                import_modpack(str(archive), str(tmp_path / 'game'),
                               mc_version='1.20.1', status_callback=messages.append,
                               progress_callback=lambda *_: event.set())
            install.assert_not_called()
        assert any('完整性' in message for message in messages)
    finally:
        cancel_event.reset(token)
