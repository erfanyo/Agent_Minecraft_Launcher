"""Create the Windows portable archive with the verified built-in AI model."""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import model_registry


SHORTCUT_BAT = r'''@echo off
setlocal
set "AMCL_BUNDLE_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$desktop=[Environment]::GetFolderPath('Desktop'); $shell=New-Object -ComObject WScript.Shell; $shortcut=$shell.CreateShortcut((Join-Path $desktop 'Agent Minecraft Launcher (Local AI).lnk')); $shortcut.TargetPath=(Join-Path $env:AMCL_BUNDLE_DIR 'AgentMinecraftLauncher.exe'); $shortcut.WorkingDirectory=$env:AMCL_BUNDLE_DIR; $shortcut.Save()"
if errorlevel 1 (
  echo Could not create the desktop shortcut. Run this file again after extracting the bundle.
  pause
  exit /b 1
)
echo Desktop shortcut created. Keep this extracted folder in its current location.
echo If you move the folder later, run this file again to update the shortcut.
pause
'''


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, help="Path to the built launcher exe")
    parser.add_argument("--output", required=True, help="Destination ZIP path")
    args = parser.parse_args()

    exe = os.path.abspath(args.exe)
    if not os.path.isfile(exe):
        raise SystemExit(f"Launcher executable not found: {exe}")
    resource_id = "qwen3.5-0.8b-xlam-q4km"
    resource = model_registry.RESOURCES[resource_id]
    model_path = model_registry.local_path(resource_id)
    if not model_registry.is_downloaded(resource_id):
        model_registry.download(resource_id)
    actual = sha256(model_path)
    if actual != resource["sha256"]:
        raise SystemExit(f"Model SHA256 mismatch: {actual}")

    output = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as bundle:
        bundle.write(exe, "AgentMinecraftLauncher.exe")
        bundle.write(model_path, f"AMCL/models/{resource['file']}")
        bundle.writestr("CreateDesktopShortcut.bat", SHORTCUT_BAT)
    print(f"Created {output}")


if __name__ == "__main__":
    main()
