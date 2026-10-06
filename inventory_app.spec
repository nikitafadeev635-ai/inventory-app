# -*- mode: python ; coding: utf-8 -*-
# Скрипт сборки inventory_app.exe

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Встраиваем в .exe только внутренние ресурсы
        ('image', 'image'),           # Картинки (если используются внутри кода)
        ('gui/styles.py', 'gui'),     # Стили (импортируются)
    ],
    hiddenimports=[
        'httpx',
        'fastapi',
        'uvicorn',
        'qrcode',
        'reportlab',
        'dotenv',
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtSvg',
        'sqlalchemy',
        'mysql.connector',
        'pymysql',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',      # Не используется
        'numpy',           # Может не использоваться
        'scipy',
        'pandas',
        'tkinter',
        'pytest',
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
    name='inventory_app',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,   # 🚫 Без консольного окна (GUI-приложение)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,       # Можно добавить иконку: icon='icon.ico'
)