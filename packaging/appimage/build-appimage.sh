#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build-appimage.sh — Builds Steam Grunge Editor as an AppImage
#
# Works when called from any directory — uses REPO_ROOT to find files.
# ─────────────────────────────────────────────────────────────────────────────
set -e

# ── Resolve repo root regardless of where the script is called from ───────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

APP="SteamGrungeEditor"
VERSION=$(cat "$REPO_ROOT/VERSION" 2>/dev/null || echo "1.0.0")
ARCH="x86_64"
APPDIR="$SCRIPT_DIR/${APP}.AppDir"
APPIMAGETOOL_URL="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Building Steam Grunge Editor AppImage v${VERSION}"
echo "  Repo root: $REPO_ROOT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Get appimagetool ───────────────────────────────────────────────────────
APPIMAGETOOL="$SCRIPT_DIR/appimagetool.AppImage"
if [ ! -f "$APPIMAGETOOL" ]; then
    echo "[1/6] Downloading appimagetool..."
    wget -q "$APPIMAGETOOL_URL" -O "$APPIMAGETOOL"
    chmod +x "$APPIMAGETOOL"
else
    echo "[1/6] appimagetool already present, skipping download."
fi

# ── 2. Create AppDir structure ────────────────────────────────────────────────
echo "[2/6] Creating AppDir structure..."
rm -rf "$APPDIR"
mkdir -p "$APPDIR"/usr/{bin,lib,share/{applications,icons/hicolor/256x256/apps}}
mkdir -p "$APPDIR/usr/lib/steam-grunge-editor"

# ── 3. Copy application source ────────────────────────────────────────────────
echo "[3/6] Copying application files..."
cp -r "$REPO_ROOT/app"              "$APPDIR/usr/lib/steam-grunge-editor/"
cp    "$REPO_ROOT/requirements.txt" "$APPDIR/usr/lib/steam-grunge-editor/"
cp    "$REPO_ROOT/VERSION"          "$APPDIR/usr/lib/steam-grunge-editor/" 2>/dev/null || true

# ── 4. Install Python deps into AppDir ───────────────────────────────────────
echo "[4/6] Installing Python dependencies..."
VENV="$APPDIR/usr/lib/steam-grunge-editor/venv"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$APPDIR/usr/lib/steam-grunge-editor/requirements.txt"

# ── 5. Create launcher and desktop integration ────────────────────────────────
echo "[5/6] Creating launcher..."
cat > "$APPDIR/usr/bin/steam-grunge-editor" << 'LAUNCHER'
#!/usr/bin/env bash
SELF_DIR="$(dirname "$(readlink -f "$0")")"
APP_LIB="$SELF_DIR/../lib/steam-grunge-editor"
exec "$APP_LIB/venv/bin/python" "$APP_LIB/app/main.py" "$@"
LAUNCHER
chmod +x "$APPDIR/usr/bin/steam-grunge-editor"

# Desktop file
cp "$REPO_ROOT/packaging/desktop/steam-grunge-editor.desktop" \
   "$APPDIR/usr/share/applications/"
cp "$REPO_ROOT/packaging/desktop/steam-grunge-editor.desktop" \
   "$APPDIR/"

# Icon
cp "$REPO_ROOT/app/assets/icon.png" \
   "$APPDIR/usr/share/icons/hicolor/256x256/apps/steam-grunge-editor.png"
cp "$REPO_ROOT/app/assets/icon.png" \
   "$APPDIR/steam-grunge-editor.png"

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
ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" \
    "$SCRIPT_DIR/Steam_Grunge_Editor-${VERSION}-${ARCH}.AppImage"

echo ""
echo "✓ Done! Output: Steam_Grunge_Editor-${VERSION}-${ARCH}.AppImage"
