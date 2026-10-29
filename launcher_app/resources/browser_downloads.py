"""Opt-in, bounded reception of new archives; no browser secrets or file moves."""
from contextlib import contextmanager
import os
import zipfile
from pathlib import Path

from launcher_app.core.task_context import checkpoint
from launcher_app.resources.archive_inspection import inspect_archive, MAX_ARCHIVE


def fingerprint(path):
    value = path.stat()
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


@contextmanager
def read_guard(path):
    """On Windows deny concurrent writes/deletes during inspection."""
    handle = None
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        api.CreateFileW.restype = wintypes.HANDLE
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise PermissionError('Archive is still in use')
    try:
        yield
    finally:
        if handle is not None:
            api.CloseHandle(handle)


class ArchiveInbox:
    def __init__(self, directory):
        self.directory = Path(directory).resolve(strict=True)
        if not self.directory.is_dir():
            raise ValueError('Download location must be a directory')
        self.initial = self._entries()
        self.checked = {}

    def _entries(self):
        result = {}
        with os.scandir(self.directory) as entries:
            for index, entry in enumerate(entries):
                checkpoint()
                if index >= 10_000:
                    raise ValueError('Too many entries; select a smaller download folder')
                if Path(entry.name).suffix.casefold() not in ('.zip', '.mrpack'):
                    continue
                path = Path(entry.path)
                if entry.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                    continue
                try:
                    if entry.is_file(follow_symlinks=False):
                        result[entry.name] = fingerprint(path)
                except OSError:
                    continue
        return result

    def poll(self):
        received = []
        attempts = 0
        for name, signature in self._entries().items():
            checkpoint()
            if self.initial.get(name) == signature or self.checked.get(name) == signature:
                continue
            if signature[2] > MAX_ARCHIVE:
                self.checked[name] = signature
                continue
            if attempts >= 2:
                break
            attempts += 1
            path = self.directory / name
            try:
                if path.is_symlink() or path.resolve(strict=True).parent != self.directory:
                    continue
                # Filename / stable size is never sufficient. Read every member,
                # verify CRC and limits, and bind the result to unchanged bytes.
                with read_guard(path):
                    report = inspect_archive(path)
                    if fingerprint(path) != signature:
                        continue
                received.append({'path': str(path), 'name': name,
                    'size': report['archiveBytes'], 'sha256': report['sha256'],
                    'signature': signature})
                self.checked[name] = signature
            except PermissionError:
                # Browser still writing: retry even if its visible size is stable.
                continue
            except (OSError, ValueError, zipfile.BadZipFile, NotImplementedError):
                self.checked[name] = signature
        return received
