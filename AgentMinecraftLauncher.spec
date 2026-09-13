# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

import PySide6
import importlib.util
from PyInstaller.utils.hooks import collect_all

# Optional system-webview host; never collect QtWebEngine/CEF as a fallback.
WEB_DATA, WEB_BINARIES, WEB_IMPORTS = [], [], []
if importlib.util.find_spec('webview'):
    WEB_DATA, WEB_BINARIES, WEB_IMPORTS = collect_all('webview')
    WEB_IMPORTS = [name for name in WEB_IMPORTS
                   if name not in ('webview.platforms.qt', 'webview.platforms.cef')]

# ci_smoke 通过模块名逐个导入；PyInstaller 无法从字符串推断这些依赖。
# 显式保留也能覆盖插件/平台代码按需加载但主窗口启动路径未直接 import 的模块。
SMOKE_IMPORTS = [
    'paths', 'settings',
    'os_platform.system', 'os_platform.openpath', 'os_platform.temperature', 'os_platform.notify',
    'game_command', 'lan_tools', 'instance_manager', 'version_home', 'online_center',
    'assistant_ui', 'local_ai', 'ci_smoke',
]

# PySide6 的 QtCore 依赖同目录中的 MSVC/Qt 运行库；显式补齐运行库。
# 成品仍必须通过 build_release.ps1 的真实启动检查后才能发布。
PYSIDE6_DIR = Path(PySide6.__file__).parent
MSVC_RUNTIME_NAMES = (
    'msvcp140.dll',
    'msvcp140_1.dll',
    'msvcp140_2.dll',
    'msvcp140_codecvt_ids.dll',
    'vcruntime140.dll',
    'vcruntime140_1.dll',
)
PYSIDE6_BINARIES = [
    (str(PYSIDE6_DIR / name), 'PySide6')
    for name in MSVC_RUNTIME_NAMES
]
# External Java distributions expect the VC runtime from the operating system.
# Keep a collision-free copy for clean Windows VMs instead of exposing all Qt DLLs.
EXTERNAL_RUNTIME_BINARIES = [
    (str(PYSIDE6_DIR / name), 'external-runtime')
    for name in ('vcruntime140.dll', 'vcruntime140_1.dll')
]
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=PYSIDE6_BINARIES + EXTERNAL_RUNTIME_BINARIES + WEB_BINARIES,
    datas=[
        ('AMCL/runtime/llama-cpp/*', 'runtime/llama-cpp'),
        ('bridge-mod/dist/*.jar', 'bridge-mod'),
        ('icons/*.svg', 'icons'),
        ('icons/grass_block.png', 'icons'),
        ('LICENSE', '.'),
        ('THIRD_PARTY.md', '.'),
        ('THIRD_PARTY_NOTICES.md', '.'),
        (str(PYSIDE6_DIR / 'resources' / 'icudtl.dat'), 'PySide6/resources'),
    ] + WEB_DATA,
    hiddenimports=WEB_IMPORTS + SMOKE_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['tools/pyi_runtime_clean_dll_path.py'],
    excludes=['webview.platforms.qt', 'webview.platforms.cef', 'PySide6.QtWebEngineCore',
              'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick', 'cefpython3'],
    noarchive=False,
    optimize=0,
)

# Qt 6 uses Windows' ICU forwarding DLLs. A developer PATH may also contain an
# unrelated ICU build (for example Poppler's versioned ICU). PyInstaller can
# mistake that build for Qt's dependency and place it beside the executable,
# where it shadows the compatible Windows component and breaks QtCore import.
_FOREIGN_ICU = {'icuuc.dll', 'icudt78.dll'}
a.binaries = type(a.binaries)(
    item for item in a.binaries if item[0].lower() not in _FOREIGN_ICU
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AgentMinecraftLauncher',
    icon='icons/grass_block.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,   # 关闭 UPX:压缩壳特征易触发 SmartScreen/杀软误报(2026-08-26 改)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
