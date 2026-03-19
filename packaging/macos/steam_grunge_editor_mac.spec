# -*- mode: python ; coding: utf-8 -*-
# ─────────────────────────────────────────────────────────────────────────────
# steam_grunge_editor_mac.spec — PyInstaller bundle spec (macOS)
#
# Run from repo root:
#   pyinstaller packaging/macos/steam_grunge_editor_mac.spec \
#     --distpath packaging/macos/dist \
#     --workpath packaging/macos/build \
#     --noconfirm
#
# Output: packaging/macos/dist/Steam Grunge Editor.app
#
# v2.1.0 changes:
#   - Removed block_cipher / cipher= — deprecated and removed in PyInstaller 6+;
#     causes TypeError on any modern PyInstaller install
#   - Removed a.zipped_data from COLLECT — removed in PyInstaller 6+
#   - Removed requirements.txt from datas — serves no purpose inside a bundle
#     and wastes ~5 KB per build; all deps are already bundled
#   - Added missing hidden imports:
#       PySide6.QtNetwork   — used by SteamGridDB HTTP requests
#       PySide6.QtSvg       — needed for icon rendering on some macOS themes
#       PIL.ImageEnhance    — used by layer adjustment pipeline
#       PIL.ImageDraw       — used by compositor
#       PIL.ImageFont       — used by text layers
#       PIL.ImageFilter     — used by FX pipeline
#       logging.handlers    — required by steamSync RotatingFileHandler (v2.1.0)
#       zipfile / json      — used by projectIO .sgeproj save/load
#   - Bundled all assets via single (ASSETS_DIR, "app/assets") glob instead of
#     per-subfolder entries — simpler and avoids missing new asset subdirs
#   - CFBundleVersion / CFBundleShortVersionString read from VERSION file at
#     spec parse time — no more hardcoded version string
#   - Added NSAppTransportSecurity to allow outbound HTTP to SteamGridDB CDN
#   - Added CFBundleDocumentTypes for .sgeproj (new in v2.1.0 project format)
#   - collect_submodules('app') added to catch all internal app modules
# ─────────────────────────────────────────────────────────────────────────────
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

REPO_ROOT  = Path(SPECPATH).parent.parent
ASSETS_DIR = REPO_ROOT / "app" / "assets"

# Read version at spec-parse time so Info.plist is always in sync
_version_file = REPO_ROOT / "VERSION"
APP_VERSION = _version_file.read_text().strip() if _version_file.exists() else "2.1.0"

# ── Data files ────────────────────────────────────────────────────────────────
added_files = [
    # Entire assets tree in one entry — catches any new subdirs automatically
    (str(ASSETS_DIR),          "app/assets"),
    # VERSION — read at runtime by mainWindow.py for APP_VERSION + update checker
    (str(REPO_ROOT / "VERSION"), "."),
]
added_files += collect_data_files("PySide6")

# ── Hidden imports ────────────────────────────────────────────────────────────
hidden_imports = [
    # Qt
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtSvg",
    # Pillow
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "PIL.ImageFilter",
    "PIL.ImageEnhance",
    # Numerics / network
    "numpy",
    "requests",
    # stdlib — not always auto-detected
    "logging.handlers",   # steamSync RotatingFileHandler (v2.1.0)
    "zipfile",            # projectIO .sgeproj format
    "json",
]
hidden_imports += collect_submodules("app")

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(REPO_ROOT / "app" / "main.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "scipy",
        "pandas",
        "jupyter",
        "IPython",
        "notebook",
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
    name="SteamGrungeEditor",
    debug=False,
    strip=False,
    upx=True,
    console=False,           # no Terminal window on launch
    target_arch=None,        # None = match build machine; set "universal2" for fat binary
    codesign_identity=None,  # set to cert name for Gatekeeper-signed builds
    entitlements_file=None,
    icon=str(ASSETS_DIR / "icon.icns"),
)

# ── COLLECT ───────────────────────────────────────────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,                 # a.zipped_data removed — not present in PyInstaller 6+
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SteamGrungeEditor",
)

# ── BUNDLE — macOS .app ───────────────────────────────────────────────────────
app = BUNDLE(
    coll,
    name="Steam Grunge Editor.app",
    icon=str(ASSETS_DIR / "icon.icns"),
    bundle_identifier="com.huzzama.steamgrungeeditor",
    info_plist={
        # ── Identity ──────────────────────────────────────────────────────────
        "CFBundleName":               "Steam Grunge Editor",
        "CFBundleDisplayName":        "Steam Grunge Editor",
        "CFBundleIdentifier":         "com.huzzama.steamgrungeeditor",
        "CFBundleVersion":            APP_VERSION,
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleIconFile":           "icon.icns",
        "CFBundlePackageType":        "APPL",
        "CFBundleSignature":          "????",

        # ── Capabilities ──────────────────────────────────────────────────────
        "NSHighResolutionCapable":         True,
        "NSRequiresAquaSystemAppearance":  False,   # supports dark mode
        "LSMinimumSystemVersion":          "11.0",  # macOS Big Sur+

        # ── Network — allow outbound HTTP to SteamGridDB CDN ─────────────────
        # Without this, macOS App Transport Security may block CDN image URLs
        # on sandboxed builds. Not needed if not distributing via App Store.
        "NSAppTransportSecurity": {
            "NSAllowsArbitraryLoads": True,
        },

        # ── File associations ─────────────────────────────────────────────────
        "CFBundleDocumentTypes": [
            {
                # Standard images (open into editor)
                "CFBundleTypeName":   "Image",
                "CFBundleTypeRole":   "Editor",
                "LSItemContentTypes": [
                    "public.png",
                    "public.jpeg",
                    "public.image",
                ],
            },
            {
                # .sgeproj — Steam Grunge Editor project file (v2.1.0+)
                "CFBundleTypeName":       "Steam Grunge Editor Project",
                "CFBundleTypeRole":       "Editor",
                "CFBundleTypeExtensions": ["sgeproj"],
                "LSItemContentTypes":     ["com.huzzama.sgeproj"],
                "CFBundleTypeIconFile":   "icon.icns",
            },
        ],
    },
)
