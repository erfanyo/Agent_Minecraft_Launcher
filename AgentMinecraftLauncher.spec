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

# PySide6 的 QtCore 依赖同目录中的 MSVC/Qt 运行库；仅靠自动分析时，某些
# 机器会漏收它们并在启动期报“DLL load failed”。显式收集保证单文件 exe
# 解压后具备完整 Qt 运行环境。
PYSIDE6_DIR = Path(PySide6.__file__).parent
PYSIDE6_BINARIES = [
    (str(PYSIDE6_DIR / name), 'PySide6')
    for name in (
        'msvcp140.dll',
        'msvcp140_1.dll',
        'msvcp140_2.dll',
        'msvcp140_codecvt_ids.dll',
        'vcruntime140.dll',
        'vcruntime140_1.dll',
    )
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=PYSIDE6_BINARIES + WEB_BINARIES,
    datas=[
        ('AMCL/runtime/llama-cpp/*', 'runtime/llama-cpp'),
        ('bridge-mod/dist/*.jar', 'bridge-mod'),
        ('icons/*.svg', 'icons'),
        ('icons/grass_block.png', 'icons'),
        (str(PYSIDE6_DIR / 'resources' / 'icudtl.dat'), 'PySide6/resources'),
    ] + WEB_DATA,
    hiddenimports=WEB_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['webview.platforms.qt', 'webview.platforms.cef', 'PySide6.QtWebEngineCore',
              'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick', 'cefpython3'],
    noarchive=False,
    optimize=0,
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
