# -*- mode: python ; coding: utf-8 -*-
# ─────────────────────────────────────────────────────────────────────────────
# steam_grunge_editor.spec — PyInstaller bundle spec  (Windows)
#
# Run from the repo root:
#   pyinstaller packaging\windows\steam_grunge_editor.spec --noconfirm --clean
#
# Output: dist\SteamGrungeEditor\SteamGrungeEditor.exe
#
# v2.1.0 changes:
#   - icon path corrected to .ico (was .png — silently ignored by PyInstaller
#     on Windows but produced an exe with no taskbar icon on some Win11 builds)
#   - Added logging.handlers to hidden_imports (required by the new rotating
#     file logger in steamSync.py; PyInstaller doesn't auto-detect it)
#   - Added PySide6.QtSvg to hidden_imports (needed by icon rendering path)
# ─────────────────────────────────────────────────────────────────────────────
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Repo root (two levels up from this spec file)
ROOT = os.path.abspath(os.path.join(SPECPATH, '..', '..'))

# Icon — must be .ico on Windows for correct taskbar / installer display
ICON = os.path.join(ROOT, 'app', 'assets', 'icon.ico')

# ── Collect all assets ────────────────────────────────────────────────────────
added_files = [
    # Assets folder — textures, brushes, fonts, templates, icons, ratings
    (os.path.join(ROOT, 'app', 'assets'),  'app/assets'),
    # VERSION file — read at runtime by mainWindow.py for APP_VERSION
    (os.path.join(ROOT, 'VERSION'),        '.'),
]

# Collect PySide6 data files (Qt translations, plugins, platform drivers)
added_files += collect_data_files('PySide6')

# ── Hidden imports ────────────────────────────────────────────────────────────
hidden_imports = [
    # Qt
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtNetwork',
    'PySide6.QtSvg',
    # Pillow
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'PIL.ImageFilter',
    'PIL.ImageEnhance',
    # Numerics / network
    'numpy',
    'requests',
    # stdlib — not always auto-detected by PyInstaller static analysis
    'logging.handlers',   # required by steamSync rotating file logger (v2.1.0)
    'zipfile',            # required by projectIO .sgeproj save/load
    'json',
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
        'IPython',
        'notebook',
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
    console=False,                  # no terminal window on launch
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=ICON,                      # .ico — required for correct Win taskbar icon
)

# ── COLLECT — folder-based distribution (required by Inno Setup) ──────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SteamGrungeEditor',
)
