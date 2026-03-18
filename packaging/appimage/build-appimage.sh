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

# ── Build-time venv (used only on the build machine for PyInstaller) ──────────
BUILD_VENV="$SCRIPT_DIR/.build-venv"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Building Steam Grunge Editor AppImage v${VERSION}"
echo "  Repo root: $REPO_ROOT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Get appimagetool ───────────────────────────────────────────────────────
APPIMAGETOOL="$SCRIPT_DIR/appimagetool.AppImage"
if [ ! -f "$APPIMAGETOOL" ]; then
    echo "[1/7] Downloading appimagetool..."
    wget -q "$APPIMAGETOOL_URL" -O "$APPIMAGETOOL"
    chmod +x "$APPIMAGETOOL"
else
    echo "[1/7] appimagetool already present, skipping download."
fi

# ── 2. Prepare build-time venv with PyInstaller + app deps ───────────────────
echo "[2/7] Preparing build environment..."
if [ ! -d "$BUILD_VENV" ]; then
    python3 -m venv "$BUILD_VENV"
fi

"$BUILD_VENV/bin/pip" install --quiet --upgrade pip

# Install app requirements first, then PyInstaller on top
"$BUILD_VENV/bin/pip" install --quiet -r "$REPO_ROOT/requirements.txt"
"$BUILD_VENV/bin/pip" install --quiet pyinstaller

# ── 3. Run PyInstaller to produce a standalone binary ────────────────────────
echo "[3/7] Running PyInstaller..."
BUILD_OUT="$SCRIPT_DIR/pyinstaller-dist"
BUILD_WORK="$SCRIPT_DIR/pyinstaller-work"

rm -rf "$BUILD_OUT" "$BUILD_WORK"

"$BUILD_VENV/bin/pyinstaller" \
    --onefile \
    --windowed \
    --name "steam-grunge-editor" \
    --distpath "$BUILD_OUT" \
    --workpath "$BUILD_WORK" \
    --specpath "$SCRIPT_DIR" \
    --add-data "$REPO_ROOT/app/assets:assets" \
    --hidden-import "PySide6.QtCore" \
    --hidden-import "PySide6.QtGui" \
    --hidden-import "PySide6.QtWidgets" \
    --collect-all "PySide6" \
    "$REPO_ROOT/app/main.py"

BINARY="$BUILD_OUT/steam-grunge-editor"

# ── 4. Validate the binary BEFORE packaging ───────────────────────────────────
echo "[4/7] Validating binary..."
if [ ! -f "$BINARY" ]; then
    echo "ERROR: PyInstaller did not produce a binary at $BINARY"
    exit 1
fi

# Smoke-test: run the binary with --version or --help if supported,
# otherwise just check it loads without immediately crashing (0.5 s timeout).
if "$BINARY" --version &>/dev/null || "$BINARY" --help &>/dev/null; then
    echo "  ✓ Binary responds to --version / --help"
else
    # GUI apps exit non-zero without a display; treat timeout as success.
    if timeout 2s "$BINARY" &>/dev/null; then
        echo "  ✓ Binary exited cleanly"
    else
        EXIT_CODE=$?
        # exit code 124 = timeout (binary was running fine, killed by timeout)
        if [ "$EXIT_CODE" -eq 124 ]; then
            echo "  ✓ Binary ran successfully (timeout — expected for GUI app)"
        elif [ "$EXIT_CODE" -eq 1 ] && [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
            echo "  ✓ Binary reported no display (expected in headless CI)"
        else
            echo "ERROR: Binary exited with code $EXIT_CODE — check PyInstaller output."
            exit 1
        fi
    fi
fi

# ── 5. Create AppDir structure ────────────────────────────────────────────────
echo "[5/7] Creating AppDir structure..."
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# ── 6. Populate AppDir ────────────────────────────────────────────────────────
echo "[6/7] Populating AppDir..."

# The PyInstaller --onefile binary IS the entire application
cp "$BINARY" "$APPDIR/usr/bin/steam-grunge-editor"
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

# AppRun — simple wrapper that exec's the self-contained binary
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/steam-grunge-editor" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# ── 7. Build AppImage ─────────────────────────────────────────────────────────
echo "[7/7] Building AppImage..."
ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" \
    "$SCRIPT_DIR/Steam_Grunge_Editor-${VERSION}-${ARCH}.AppImage"

echo ""
echo "✓ Done! Output: Steam_Grunge_Editor-${VERSION}-${ARCH}.AppImage"