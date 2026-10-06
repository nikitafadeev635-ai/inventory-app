# -*- mode: python ; coding: utf-8 -*-
# Скрипт сборки activate_point.exe (мастер-ключ)

block_cipher = None

a = Analysis(
    ['activate_point.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'httpx',
        'dotenv',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'scipy', 'pandas',
        'tkinter', 'pytest', 'PyQt6',
        'fastapi', 'uvicorn', 'qrcode', 'reportlab',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='activate_point',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,    # 🔧 С консолью (для интерактива)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)