# -*- mode: python ; coding: utf-8 -*-
# ─────────────────────────────────────────────────────────────────────────────
# steam_grunge_editor.spec — PyInstaller bundle spec
#
# Run from the repo root:
#   pyinstaller packaging/windows/steam_grunge_editor.spec
#
# Output: dist/SteamGrungeEditor/SteamGrungeEditor.exe
# ─────────────────────────────────────────────────────────────────────────────
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Repo root (two levels up from this spec file)
ROOT = os.path.abspath(os.path.join(SPECPATH, '..', '..'))

# ── Collect all assets ────────────────────────────────────────────────────────
added_files = [
    # Assets folder — textures, brushes, fonts, templates, icons, ratings
    (os.path.join(ROOT, 'app', 'assets'),       'app/assets'),
    # VERSION file — read at runtime by mainWindow.py for APP_VERSION
    (os.path.join(ROOT, 'VERSION'),             '.'),
]

# Collect PySide6 data files (translations, plugins)
added_files += collect_data_files('PySide6')

# ── Hidden imports ────────────────────────────────────────────────────────────
hidden_imports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtNetwork',
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'PIL.ImageFilter',
    'numpy',
    'requests',
]
hidden_imports += collect_submodules('app')

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [os.path.join(ROOT, 'app', 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'pandas',
        'jupyter',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

# ── EXE ───────────────────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SteamGrungeEditor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                          # no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=os.path.join(ROOT, 'app', 'assets', 'icon.png'),
)

# ── COLLECT — folder-based distribution (needed for Inno Setup) ───────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SteamGrungeEditor',
)
