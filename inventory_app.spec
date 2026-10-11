# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('image', 'image'),
        ('gui/styles.py', 'gui'),
    ],
    hiddenimports=[
        # === HTTP / API ===
        'httpx',
        'httpx._transports.default',
        'h2',
        'hpack',
        'hyperframe',
        
        # === 🆕 ЛОКАЛЬНЫЙ SYNC SERVER (FastAPI на клиенте!) ===
        'fastapi',
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'starlette',
        'starlette.middleware',
        'starlette.middleware.cors',
        'websockets',
        'pydantic',
        'anyio',
        'anyio._backends',
        'anyio._backends._asyncio',
        
        # === GUI ===
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtSvg',
        'PyQt6.QtNetwork',
        
        # === БД ===
        'pymysql',
        
        # === Отчёты ===
        'reportlab',
        'reportlab.lib',
        'reportlab.platypus',
        'reportlab.pdfgen',
        
        # === QR-коды ===
        'qrcode',
        'qrcode.image',
        'qrcode.image.pil',
        'PIL',
        'PIL.Image',
        
        # === Конфиги ===
        'dotenv',
        
        # === Криптография ===
        'jwt',
        'cryptography',
        'cryptography.hazmat',
        'cryptography.hazmat.primitives',
        
        # === 🆕 НОВЫЕ МОДУЛИ ===
        'core.google_sheets_client_sync',
        'gui.login_worker',
        
        # === Другие ===
        'sqlalchemy',
        'mysql.connector',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Тяжёлые зависимости которые ТОЧНО не используются
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'tkinter',
        'pytest',
        'IPython',
        'jupyter',
        'notebook',
        'sphinx',
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
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)