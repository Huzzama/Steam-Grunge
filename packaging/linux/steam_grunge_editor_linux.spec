# -*- mode: python ; coding: utf-8 -*-
# ─────────────────────────────────────────────────────────────────────────────
# steam_grunge_editor_linux.spec — PyInstaller bundle spec (Linux)
#
# Used by the AppImage and the RPM (release.yml). Run from the repo root:
#   pyinstaller packaging/linux/steam_grunge_editor_linux.spec --noconfirm --clean
#
# SGE_ONEFILE=1 → single file  dist/steam-grunge-editor          (RPM)
# default       → folder       dist/steam-grunge-editor/…        (AppImage —
#                 the AppImage is already a compressed image, so a folder
#                 starts much faster than a one-file binary that unpacks
#                 itself to /tmp on every launch)
#
# Assets go to app/assets inside the bundle: app/config.py resolves
# ASSETS_DIR relative to its own module, which PyInstaller puts in app/.
# ─────────────────────────────────────────────────────────────────────────────
import os
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
ONEFILE = os.environ.get("SGE_ONEFILE") == "1"

datas = [
    (os.path.join(ROOT, "app", "assets"), "app/assets"),
    (os.path.join(ROOT, "VERSION"), "."),
]

hiddenimports = collect_submodules("app") + [
    "PySide6.QtSvg",          # icons / theme indicators
    "PySide6.QtNetwork",
    "logging.handlers",       # steamSync rotating log
]

a = Analysis(
    [os.path.join(ROOT, "app", "main.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "IPython", "notebook",
              # PySide6 modules the app never uses — keeps the bundle small
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick",
              "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf"],
    noarchive=False,
)
# googleapiclient ships ~100 MB of discovery documents for every Google API;
# the app only talks to Drive v3.
def _keep(entry):
    dest = entry[0].replace("\\", "/")
    return "discovery_cache/documents/" not in dest or dest.endswith("/drive.v3.json")
a.datas = [d for d in a.datas if _keep(d)]

pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
              name="steam-grunge-editor", console=False, strip=False, upx=False)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
              name="steam-grunge-editor", console=False, strip=False, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
                   name="steam-grunge-editor")
