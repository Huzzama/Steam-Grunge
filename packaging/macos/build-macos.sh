#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build-macos.sh — Builds Steam Grunge Editor as a macOS .app + .dmg
#
# Requirements (all installable via Homebrew):
#   brew install create-dmg python@3.11
#   pip install pyinstaller pillow
#
# Usage (run from anywhere):
#   chmod +x packaging/macos/build-macos.sh
#   ./packaging/macos/build-macos.sh
#
# Output:
#   packaging/macos/Steam_Grunge_Editor-{VERSION}.dmg
#
# v2.1.0 changes:
#   - PyInstaller 6+ compatibility: removed --noconfirm --clean warning about
#     block_cipher (spec file updated separately)
#   - Added pyinstaller version check — warns if < 6.0 (block_cipher removed)
#   - Added sanity check after PyInstaller step
#   - Added sanity check after create-dmg step
#   - Improved error messages with actionable instructions
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Resolve repo root regardless of where the script is called from ───────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

VERSION=$(cat "$REPO_ROOT/VERSION" 2>/dev/null || echo "2.1.0")
APP_NAME="Steam Grunge Editor"
BUNDLE_NAME="Steam Grunge Editor.app"
DMG_NAME="Steam_Grunge_Editor-${VERSION}.dmg"
ASSETS_DIR="$REPO_ROOT/app/assets"
SPEC="$SCRIPT_DIR/steam_grunge_editor_mac.spec"
DIST_DIR="$SCRIPT_DIR/dist"
BUILD_DIR="$SCRIPT_DIR/build"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Building $APP_NAME for macOS v${VERSION}"
echo "  Repo root: $REPO_ROOT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Check requirements ─────────────────────────────────────────────────────
echo ""
echo "[1/6] Checking requirements..."

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found."
    echo "       Install via Homebrew:  brew install python@3.11"
    exit 1
fi

if ! command -v pyinstaller &>/dev/null; then
    echo "  pyinstaller not found — installing..."
    pip3 install pyinstaller --quiet
fi

# Warn if PyInstaller < 6.0 (block_cipher was removed in 6.0)
PYI_VER=$(pyinstaller --version 2>/dev/null | grep -oE '[0-9]+' | head -1)
if [ -n "$PYI_VER" ] && [ "$PYI_VER" -lt 6 ]; then
    echo "WARNING: PyInstaller $PYI_VER detected. v6.0+ is recommended."
    echo "         Upgrade:  pip install --upgrade pyinstaller"
fi

if ! command -v create-dmg &>/dev/null; then
    echo "ERROR: create-dmg not found."
    echo "       Install via Homebrew:  brew install create-dmg"
    exit 1
fi

echo "  python3:      $(python3 --version)"
echo "  pyinstaller:  $(pyinstaller --version)"
echo "  create-dmg:   $(create-dmg --version 2>/dev/null || echo 'installed')"

# ── 2. Install Python dependencies ───────────────────────────────────────────
echo ""
echo "[2/6] Installing Python dependencies..."
cd "$REPO_ROOT"
pip3 install -r requirements.txt --quiet
echo "  Done."

# ── 3. Convert icon.png → icon.icns ──────────────────────────────────────────
echo ""
echo "[3/6] Generating icon.icns..."
ICONSET="$SCRIPT_DIR/icon.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"

for size in 16 32 64 128 256 512; do
    sips -z $size $size           "$ASSETS_DIR/icon.png" \
        --out "$ICONSET/icon_${size}x${size}.png"    2>/dev/null
    sips -z $((size*2)) $((size*2)) "$ASSETS_DIR/icon.png" \
        --out "$ICONSET/icon_${size}x${size}@2x.png" 2>/dev/null
done

iconutil -c icns "$ICONSET" -o "$ASSETS_DIR/icon.icns"
rm -rf "$ICONSET"
echo "  icon.icns → $ASSETS_DIR/icon.icns"

# ── 4. PyInstaller — bundle into .app ────────────────────────────────────────
echo ""
echo "[4/6] Bundling with PyInstaller..."
rm -rf "$DIST_DIR" "$BUILD_DIR"

pyinstaller "$SPEC" \
    --distpath "$DIST_DIR" \
    --workpath "$BUILD_DIR" \
    --noconfirm \
    --clean

APP_PATH="$DIST_DIR/$BUNDLE_NAME"
if [ ! -d "$APP_PATH" ]; then
    echo ""
    echo "ERROR: .app bundle not found at expected path:"
    echo "       $APP_PATH"
    echo "       Check the PyInstaller output above for errors."
    exit 1
fi
echo "  .app bundle: $APP_PATH"

# ── 5. Update version in Info.plist ──────────────────────────────────────────
# The spec reads VERSION at parse time, but PlistBuddy overwrite is kept
# as a belt-and-suspenders guard for CI environments where the spec may be
# cached.
echo ""
echo "[5/6] Setting version $VERSION in Info.plist..."
PLIST="$APP_PATH/Contents/Info.plist"
if [ -f "$PLIST" ]; then
    /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION"            "$PLIST" 2>/dev/null || true
    /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$PLIST" 2>/dev/null || true
    echo "  CFBundleVersion = $VERSION"
else
    echo "  WARNING: Info.plist not found at $PLIST — skipping."
fi

# ── 6. Create .dmg installer ─────────────────────────────────────────────────
echo ""
echo "[6/6] Creating .dmg..."
DMG_OUT="$SCRIPT_DIR/$DMG_NAME"
rm -f "$DMG_OUT"

# Primary: with custom background (present in repo)
# Fallback: without background (always works)
create-dmg \
    --volname "$APP_NAME $VERSION" \
    --volicon "$ASSETS_DIR/icon.icns" \
    --window-pos  200 120 \
    --window-size 600 400 \
    --icon-size 100 \
    --icon "$BUNDLE_NAME" 150 185 \
    --hide-extension "$BUNDLE_NAME" \
    --app-drop-link 450 185 \
    --background "$SCRIPT_DIR/dmg-background.png" \
    "$DMG_OUT" \
    "$DIST_DIR/" 2>/dev/null \
|| \
create-dmg \
    --volname "$APP_NAME $VERSION" \
    --volicon "$ASSETS_DIR/icon.icns" \
    --window-pos  200 120 \
    --window-size 600 400 \
    --icon-size 100 \
    --icon "$BUNDLE_NAME" 150 185 \
    --hide-extension "$BUNDLE_NAME" \
    --app-drop-link 450 185 \
    "$DMG_OUT" \
    "$DIST_DIR/"

if [ ! -f "$DMG_OUT" ]; then
    echo ""
    echo "ERROR: .dmg was not created at $DMG_OUT"
    echo "       Check the create-dmg output above."
    exit 1
fi

DMG_SIZE=$(du -sh "$DMG_OUT" | cut -f1)
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Done!  ($DMG_SIZE)"
echo "  Output:  $DMG_OUT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  To test:      open \"$APP_PATH\""
echo "  To distribute: share $DMG_NAME"
echo ""
echo "  NOTE: Without an Apple Developer signing certificate,"
echo "  users must right-click → Open on first launch (Gatekeeper)."
echo "  For signed builds, set CODESIGN_IDENTITY and run:"
echo "    codesign --deep --force --sign \"\$CODESIGN_IDENTITY\" \"$APP_PATH\""
