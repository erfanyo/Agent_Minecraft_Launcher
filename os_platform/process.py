"""Launch external programs without leaking PyInstaller's private library paths."""
from __future__ import annotations

from contextlib import contextmanager
import os
import sys
import threading


_DLL_SEARCH_LOCK = threading.RLock()


def sanitized_subprocess_environment(source=None) -> dict:
    """Return an environment suitable for Java and other non-bundled programs."""
    env = dict(os.environ if source is None else source)
    bundle = getattr(sys, "_MEIPASS", "") if getattr(sys, "frozen", False) else ""
    if bundle:
        bundle = os.path.normcase(os.path.realpath(bundle))
        entries = []
        for entry in env.get("PATH", "").split(os.pathsep):
            try:
                inside = os.path.commonpath(
                    [bundle, os.path.normcase(os.path.realpath(entry))]) == bundle
            except (OSError, ValueError):
                inside = False
            if entry and not inside:
                entries.append(entry)
        external_runtime = os.path.join(bundle, "external-runtime")
        if os.path.isdir(external_runtime):
            entries.insert(0, external_runtime)
        env["PATH"] = os.pathsep.join(entries)
    if os.name != "nt":
        original = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is None:
            env.pop("LD_LIBRARY_PATH", None)
        else:
            env["LD_LIBRARY_PATH"] = original
    return env


@contextmanager
def external_process_environment(source=None):
    """Temporarily restore the OS DLL search path while creating a child process."""
    env = sanitized_subprocess_environment(source)
    frozen_windows = os.name == "nt" and getattr(sys, "frozen", False)
    if not frozen_windows:
        yield env
        return

    import ctypes
    with _DLL_SEARCH_LOCK:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetDllDirectoryW(None)
        try:
            yield env
        finally:
            kernel32.SetDllDirectoryW(getattr(sys, "_MEIPASS", None))
