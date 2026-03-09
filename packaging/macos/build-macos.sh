#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build-macos.sh — Builds Steam Grunge Editor as a macOS .app + .dmg
#
# Requirements (all installable via Homebrew):
#   brew install create-dmg python@3.11
#   pip install pyinstaller
#
# Usage (run from anywhere):
#   chmod +x packaging/macos/build-macos.sh
#   ./packaging/macos/build-macos.sh
#
# Output:
#   packaging/macos/Steam_Grunge_Editor-1.0.0.dmg
# ─────────────────────────────────────────────────────────────────────────────
set -e

# ── Resolve repo root regardless of where the script is called from ───────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

VERSION=$(cat "$REPO_ROOT/VERSION" 2>/dev/null || echo "1.0.0")
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
echo "[1/6] Checking requirements..."
command -v python3    >/dev/null || { echo "ERROR: python3 not found"; exit 1; }
command -v pyinstaller>/dev/null || pip3 install pyinstaller --quiet
command -v create-dmg >/dev/null || { echo "ERROR: create-dmg not found. Run: brew install create-dmg"; exit 1; }

# ── 2. Install Python dependencies ───────────────────────────────────────────
echo "[2/6] Installing Python dependencies..."
cd "$REPO_ROOT"
pip3 install -r requirements.txt --quiet

# ── 3. Convert icon.png → icon.icns (required for macOS .app) ────────────────
echo "[3/6] Generating icon.icns..."
ICONSET="$SCRIPT_DIR/icon.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"

# Generate all required macOS icon sizes
for size in 16 32 64 128 256 512; do
    sips -z $size $size "$ASSETS_DIR/icon.png" \
        --out "$ICONSET/icon_${size}x${size}.png"     2>/dev/null
    sips -z $((size*2)) $((size*2)) "$ASSETS_DIR/icon.png" \
        --out "$ICONSET/icon_${size}x${size}@2x.png"  2>/dev/null
done

iconutil -c icns "$ICONSET" -o "$ASSETS_DIR/icon.icns"
rm -rf "$ICONSET"
echo "  icon.icns generated at $ASSETS_DIR/icon.icns"

# ── 4. PyInstaller — bundle into .app ────────────────────────────────────────
echo "[4/6] Bundling with PyInstaller..."
rm -rf "$DIST_DIR" "$BUILD_DIR"
pyinstaller "$SPEC" \
    --distpath "$DIST_DIR" \
    --workpath "$BUILD_DIR" \
    --noconfirm

APP_PATH="$DIST_DIR/$BUNDLE_NAME"
if [ ! -d "$APP_PATH" ]; then
    echo "ERROR: .app bundle not found at $APP_PATH"
    exit 1
fi
echo "  .app bundle: $APP_PATH"

# ── 5. Update version in Info.plist ──────────────────────────────────────────
echo "[5/6] Setting version $VERSION in Info.plist..."
/usr/libexec/PlistBuddy -c \
    "Set :CFBundleVersion $VERSION" \
    "$APP_PATH/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c \
    "Set :CFBundleShortVersionString $VERSION" \
    "$APP_PATH/Contents/Info.plist" 2>/dev/null || true

# ── 6. Create .dmg installer ─────────────────────────────────────────────────
echo "[6/6] Creating .dmg..."
rm -f "$SCRIPT_DIR/$DMG_NAME"

create-dmg \
    --volname "$APP_NAME $VERSION" \
    --volicon "$ASSETS_DIR/icon.icns" \
    --window-pos 200 120 \
    --window-size 600 400 \
    --icon-size 100 \
    --icon "$BUNDLE_NAME" 150 185 \
    --hide-extension "$BUNDLE_NAME" \
    --app-drop-link 450 185 \
    --background "$SCRIPT_DIR/dmg-background.png" \
    "$SCRIPT_DIR/$DMG_NAME" \
    "$DIST_DIR/" 2>/dev/null || \
create-dmg \
    --volname "$APP_NAME $VERSION" \
    --volicon "$ASSETS_DIR/icon.icns" \
    --window-pos 200 120 \
    --window-size 600 400 \
    --icon-size 100 \
    --icon "$BUNDLE_NAME" 150 185 \
    --hide-extension "$BUNDLE_NAME" \
    --app-drop-link 450 185 \
    "$SCRIPT_DIR/$DMG_NAME" \
    "$DIST_DIR/"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Done!"
echo "  Output: $SCRIPT_DIR/$DMG_NAME"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  To test: open \"$APP_PATH\""
echo "  To distribute: share $DMG_NAME"
echo ""
echo "  NOTE: For Mac App Store or Gatekeeper-signed distribution"
echo "  you need an Apple Developer account (\$99/year)."
echo "  Without signing, users must right-click → Open on first launch."
