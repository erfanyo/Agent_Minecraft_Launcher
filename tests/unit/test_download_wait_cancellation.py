import hashlib
import os
import tempfile
import threading
import time
from unittest.mock import patch

import pytest

from launcher_app.resources.downloader import download_file
from launcher_app.core.task_context import TaskCancelled, cancel_event


@pytest.mark.parametrize('stall_at', ['connect', 'body'])
def test_cancel_does_not_wait_for_stalled_network_or_write_late(stall_at):
    event = threading.Event()
    stalled = threading.Event()
    release = threading.Event()
    closed = threading.Event()

    class Response:
        headers = {'content-length': '8'}

        def raise_for_status(self):
            pass

        def close(self):
            closed.set()

        def iter_content(self, **kwargs):
            yield b'abcd'
            stalled.set()
            release.wait(5)
            yield b'efgh'

    def get(*args, **kwargs):
        if stall_at == 'connect':
            stalled.set()
            release.wait(5)
        return Response()

    def cancel():
        if stalled.wait(3):
            event.set()

    canceller = threading.Thread(target=cancel)
    canceller.start()
    token = cancel_event.set(event)
    try:
        with tempfile.TemporaryDirectory() as root, patch('launcher_app.resources.downloader.requests.get', side_effect=get):
            target = os.path.join(root, 'mod.jar')
            try:
                started = time.monotonic()
                with pytest.raises(TaskCancelled):
                    download_file('https://example.org/mod.jar', target)
                assert time.monotonic() - started < 2
                assert not os.path.exists(target)
            finally:
                release.set()
                assert closed.wait(2)
            assert not os.path.exists(target)
    finally:
        release.set()
        cancel_event.reset(token)
        canceller.join(2)


def test_cancellable_download_preserves_bytes_hash_and_progress():
    class Response:
        headers = {'content-length': '8'}
        def raise_for_status(self): pass
        def close(self): pass
        def iter_content(self, **kwargs):
            yield b'abcd'
            yield b'efgh'

    token = cancel_event.set(threading.Event())
    try:
        with tempfile.TemporaryDirectory() as root, patch('launcher_app.resources.downloader.requests.get', return_value=Response()):
            target = os.path.join(root, 'mod.jar')
            reports = []
            download_file('https://example.org/mod.jar', target,
                          sha1=hashlib.sha1(b'abcdefgh').hexdigest(),
                          progress_callback=lambda d, t: reports.append((d, t)))
            with open(target, 'rb') as file:
                assert file.read() == b'abcdefgh'
            assert reports == [(4, 8), (8, 8)]
    finally:
        cancel_event.reset(token)
