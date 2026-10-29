# -*- mode: python ; coding: utf-8 -*-
"""Linux onedir package used by CI and WSL acceptance testing."""

from pathlib import Path
import importlib.util

import PySide6
from PyInstaller.utils.hooks import collect_all, collect_submodules


WEB_DATA, WEB_BINARIES, WEB_IMPORTS = [], [], []
if importlib.util.find_spec("webview"):
    WEB_DATA, WEB_BINARIES, WEB_IMPORTS = collect_all("webview")
    WEB_IMPORTS = [
        name for name in WEB_IMPORTS
        if name not in ("webview.platforms.qt", "webview.platforms.cef")
    ]

SMOKE_IMPORTS = [
    "paths", "settings",
    "os_platform.system", "os_platform.openpath", "os_platform.temperature",
    "os_platform.notify", 'launcher_app.instances.game_command', 'launcher_app.ui.lan_tools', 'launcher_app.ui.instance_manager',
    'launcher_app.ui.version_home', 'launcher_app.ui.online_center', 'launcher_app.ai.assistant_ui', 'launcher_app.ai.local_ai', "ci_smoke",
]

PYSIDE6_DIR = Path(PySide6.__file__).parent
datas = [
    ("AMCL/runtime/llama-cpp/*", "runtime/llama-cpp"),
    ("bridge-mod/dist/*.jar", "bridge-mod"),
    ("icons/*.svg", "icons"),
    ("icons/grass_block.png", "icons"),
    ("icons/server_cabinet_dark.png", "icons"),
    ("icons/server_cabinet_light.png", "icons"),
    ("assets/-7878592509531134518.png", "assets"),
    ("LICENSE", "."),
    ("THIRD_PARTY.md", "."),
    ("THIRD_PARTY_NOTICES.md", "."),
] + [(f'languages/{lang}.json', 'languages') for lang in ('en', 'ja', 'ko', 'fr', 'es', 'ru', 'ar')] + WEB_DATA

icu_data = PYSIDE6_DIR / "resources" / "icudtl.dat"
if icu_data.is_file():
    datas.append((str(icu_data), "PySide6/resources"))

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=WEB_BINARIES,
    datas=datas,
    hiddenimports=WEB_IMPORTS + SMOKE_IMPORTS + collect_submodules('launcher_app.features'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "webview.platforms.qt", "webview.platforms.cef",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick", "cefpython3",
    ],
    noarchive=False,
    optimize=0,
)
import sys
sys.path.insert(0, str(Path(SPECPATH) / 'tools'))
from bundle_credentials import inject_credentials
inject_credentials(a, SPECPATH)
from PyInstaller.config import CONF
from uuid import uuid4
pyz = PYZ(a.pure, name=str(Path(CONF['workpath']) / ('PYZ-' + uuid4().hex + '.pyz')))

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AgentMinecraftLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AgentMinecraftLauncher",
)
