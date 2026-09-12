"""Load Windows' ICU forwarders before Qt can see unrelated PATH copies."""
from __future__ import annotations

import ctypes
import os
import sys


if sys.platform == "win32" and getattr(sys, "frozen", False):
    windows = os.environ.get("SystemRoot", r"C:\Windows")
    system32 = os.path.join(windows, "System32")
    # Qt 6 imports the version-neutral ICU interface. Loading the Windows
    # forwarders by absolute path keeps a Poppler/Java ICU from PATH from being
    # selected, while preserving PATH for Java and other launcher tools.
    ctypes.WinDLL(os.path.join(system32, "icu.dll"))
    ctypes.WinDLL(os.path.join(system32, "icuuc.dll"))
