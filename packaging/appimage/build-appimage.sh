#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build-appimage.sh — Builds Steam Grunge Editor as an AppImage
#
# Usage:
#   chmod +x build-appimage.sh
#   ./build-appimage.sh
#
# Output:
#   Steam_Grunge_Editor-x86_64.AppImage
# ─────────────────────────────────────────────────────────────────────────────
set -e

APP="SteamGrungeEditor"
VERSION=$(cat ../../VERSION 2>/dev/null || echo "1.0.0")
ARCH="x86_64"
APPDIR="${APP}.AppDir"
APPIMAGETOOL_URL="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Building Steam Grunge Editor AppImage v${VERSION}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Get appimagetool ───────────────────────────────────────────────────────
if [ ! -f "appimagetool.AppImage" ]; then
    echo "[1/6] Downloading appimagetool..."
    wget -q "$APPIMAGETOOL_URL" -O appimagetool.AppImage
    chmod +x appimagetool.AppImage
else
    echo "[1/6] appimagetool already present, skipping download."
fi

# ── 2. Create AppDir structure ────────────────────────────────────────────────
echo "[2/6] Creating AppDir structure..."
rm -rf "$APPDIR"
mkdir -p "$APPDIR"/usr/{bin,lib,share/{applications,icons/hicolor/256x256/apps}}

# ── 3. Copy application source ────────────────────────────────────────────────
echo "[3/6] Copying application files..."
cp -r ../../app       "$APPDIR/usr/lib/steam-grunge-editor/"
cp    ../../VERSION   "$APPDIR/usr/lib/steam-grunge-editor/" 2>/dev/null || true
cp    ../../requirements.txt "$APPDIR/usr/lib/steam-grunge-editor/"

# ── 4. Install Python deps into AppDir ───────────────────────────────────────
echo "[4/6] Installing Python dependencies..."
python3 -m venv "$APPDIR/usr/lib/steam-grunge-editor/venv"
"$APPDIR/usr/lib/steam-grunge-editor/venv/bin/pip" install \
    --quiet --upgrade pip
"$APPDIR/usr/lib/steam-grunge-editor/venv/bin/pip" install \
    --quiet -r "$APPDIR/usr/lib/steam-grunge-editor/requirements.txt"

# ── 5. Create launcher wrapper ────────────────────────────────────────────────
echo "[5/6] Creating launcher..."
cat > "$APPDIR/usr/bin/steam-grunge-editor" << 'LAUNCHER'
#!/usr/bin/env bash
SELF_DIR="$(dirname "$(readlink -f "$0")")"
APP_LIB="$SELF_DIR/../lib/steam-grunge-editor"
exec "$APP_LIB/venv/bin/python" "$APP_LIB/app/main.py" "$@"
LAUNCHER
chmod +x "$APPDIR/usr/bin/steam-grunge-editor"

# Desktop file
cp ../desktop/steam-grunge-editor.desktop "$APPDIR/usr/share/applications/"
cp ../desktop/steam-grunge-editor.desktop "$APPDIR/"

# Icon
cp ../../app/assets/icon.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/steam-grunge-editor.png"
cp ../../app/assets/icon.png "$APPDIR/steam-grunge-editor.png"

# AppRun entrypoint
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
export PATH="$HERE/usr/bin:$PATH"
exec "$HERE/usr/bin/steam-grunge-editor" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# ── 6. Build AppImage ─────────────────────────────────────────────────────────
echo "[6/6] Building AppImage..."
ARCH=x86_64 ./appimagetool.AppImage "$APPDIR" \
    "Steam_Grunge_Editor-${VERSION}-${ARCH}.AppImage"

echo ""
echo "✓ Done! Output: Steam_Grunge_Editor-${VERSION}-${ARCH}.AppImage"
