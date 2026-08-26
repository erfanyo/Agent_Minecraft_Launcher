# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('AMCL/runtime/llama-cpp/*', 'runtime/llama-cpp'),
        ('bridge-mod/dist/*.jar', 'bridge-mod'),
        ('icons/*.svg', 'icons'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
