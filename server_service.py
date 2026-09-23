# -*- coding: utf-8 -*-
"""Qt-free server management domain layer.

Both the GUI (``ServerCenter``), the future headless CLI, MCP tools,
and any MCSManager integration adapter should call this module instead
of importing the leaf modules directly.  Every symbol here is safe to
use from a pure-Python process with no PySide6 / GUI dependency.
"""
from __future__ import annotations

import os
from pathlib import Path


# ========================= Java selection =========================

def select_server_java(
    plan: dict,
    report: dict,
    settings: dict,
    runtime_dir: str,
    status_callback=None,
    progress_callback=None,
):
    """Choose or download a compatible Java runtime for a server launch plan.

    Same policy as the client-side Java management: prefer a user-configured
    Java of the right major, fall back to ``java_manager.ensure_java``.

    Returns ``(java_path, (major, error_string))``.
    Raises ``RuntimeError`` on unrecoverable conflicts.
    """
    from java_manager import ensure_java, java_version_probe, minecraft_java_range

    status = status_callback or (lambda _: None)
    mc = plan.get('minecraftVersion') or (report or {}).get('minecraftVersion') or ''
    declared = plan.get('requiredJava') or (report or {}).get('requiredJava')
    if mc:
        minimum, maximum = minecraft_java_range(mc)
    else:
        minimum, maximum = int(declared or 17), None
        status('无法确认 Minecraft 版本，暂按 Java 17 选择运行时。')
    required = max(minimum, int(declared or minimum))
    if maximum is not None and required > maximum:
        raise RuntimeError(
            f'服务端声明的 Java {required} 与 Minecraft {mc} 的兼容范围冲突。')
    preferred = str((settings.get('java_paths') or {}).get(str(required)) or '').strip()
    if preferred and Path(preferred).is_file():
        major, error = java_version_probe(preferred)
        if not error and major >= required and (maximum is None or major <= maximum):
            status(f'使用 Java 管理中设置的 Java {major}。')
            return preferred, (major, '')
        status('设置中的 Java 不可用或与该服务端不兼容，改用自动选择。')
    java = ensure_java(
        runtime_dir, required,
        progress_callback=progress_callback,
        status_callback=status,
        max_major=maximum,
        prefer_managed=(maximum == 8),
    )
    result = java_version_probe(java)
    if result[1] or not result[0]:
        raise RuntimeError(result[1] or '自动选择的 Java 无法运行')
    return java, result


# ========================= Start-command export =========================

def export_start_command(plan: dict, java_path: str) -> str:
    """Render a launch plan into a plain, copy-pasteable command line.

    ``java_path`` is the absolute path to a ``java`` executable (or just
    ``"java"`` if the caller trusts ``PATH``).  The result can be pasted
    into ``start.bat`` / ``start.sh``, or fed to MCSManager's "启动命令"
    field.

    Example::

        C:\\...\\jdk-21\\bin\\java.exe -Xmx2G -jar forge-1.20.1.jar nogui
    """
    args = list(plan.get('arguments') or [])
    return ' '.join([f'"{java_path}"' if ' ' in java_path else java_path] + args)


def export_start_script(
    plan: dict,
    java_path: str,
    dest: str,
    *,
    encoding: str = 'utf-8',
) -> str:
    """Write a ``start.bat`` (Windows) or ``start.sh`` (Unix) to *dest*.

    Returns the path written.  The script is a simple one-liner that calls
    :func:`export_start_command` with ``cd /d %~dp0`` (bat) or ``cd "$(dirname "$0")"``
    (sh) so relative paths resolve correctly.
    """
    cmd = export_start_command(plan, java_path)
    dest_path = Path(dest)
    if os.name == 'nt' or dest_path.suffix.lower() == '.bat':
        lines = ['@echo off', f'cd /d "%~dp0"', cmd, 'pause']
        text = '\r\n'.join(lines) + '\r\n'
    else:
        lines = ['#!/bin/sh', 'cd "$(dirname "$0")"', 'exec ' + cmd]
        text = '\n'.join(lines) + '\n'
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, 'w', encoding=encoding, newline='') as f:
        f.write(text)
    try:
        os.chmod(dest_path, 0o755)
    except OSError:
        pass
    return str(dest_path)


# ========================= Thin wrappers (headless façade) ==========
# These re-export the canonical entry points from the leaf modules so
# that a headless consumer (CLI / MCP / adapter) can import *one* module.

def list_servers(game_dir: str) -> list[dict]:
    """Return the list of known server packs under *game_dir*."""
    from server_packs import list_servers as _ls
    return _ls(game_dir)


def server_status(root: str, *, probe: bool = True):
    """Probe the running state of a managed server.  ``None`` = not managed."""
    from server_host_client import managed_status
    return managed_status(root, probe=probe)


def send_server_command(root: str, command: str):
    """Send a command to a running managed server via its host process."""
    from server_host_client import send_server_command as _send
    return _send(root, command)


def stop_server(root: str):
    """Gracefully stop a running managed server (sends ``stop`` via stdin)."""
    from server_host_client import send_server_command as _send
    return _send(root, 'stop')


def start_server(root: str, java: str, arguments: list[str]):
    """Launch a server in a detached host process.  Returns host state dict."""
    from server_host_client import start_managed_server
    return start_managed_server(root, java, arguments)


def inspect_pack(path: str) -> dict:
    """Scan a ZIP / MRPACK and return a report (headless, no GUI)."""
    from archive_inspection import inspect_archive
    return inspect_archive(path)


def import_server(path: str, game_dir: str, sha256: str, **kwargs):
    """Import a scanned pack into the server directory."""
    from server_packs import import_server_pack
    return import_server_pack(path, game_dir, sha256, **kwargs)


def install_runtime(root: str, loader: str, mc: str, version: str,
                    java: str, **kwargs):
    """Run the official installer to fill in missing server libraries."""
    from server_install import install_server_runtime
    return install_server_runtime(root, loader, mc, version, java, **kwargs)


def diagnose_server_log(log_text: str, mods_dir: str = ''):
    """Parse a server log / crash report and suggest fixes (pure function)."""
    from server_log_diagnosis import build_diagnosis, suggestions_to_markdown
    diagnosis = build_diagnosis(log_text, mods_dir)
    return suggestions_to_markdown(diagnosis)


def read_server_properties(server_root: str) -> dict:
    """Read current server.properties key-value mapping (headless)."""
    from server_properties_io import read_values
    return read_values(server_root)


def apply_server_properties(server_root: str, changes: dict, *,
                            allow_running: bool = False) -> dict:
    """Atomically update server.properties.  Returns ``{ok, message, backup, path}``."""
    from server_properties_io import apply_update
    return apply_update(server_root, changes, allow_running=allow_running)
