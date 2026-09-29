#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build-appimage.sh — Steam Grunge Editor AppImage (x86_64)
#
#   bash packaging/appimage/build-appimage.sh
#   → packaging/appimage/Steam_Grunge_Editor-<VERSION>-x86_64.AppImage
#
# Wraps the self-contained PyInstaller folder from packaging/linux/build-bundle.sh
# (a folder starts much faster inside an AppImage than a one-file binary).
# Runs without FUSE (APPIMAGE_EXTRACT_AND_RUN), so it works in CI containers.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$REPO_ROOT/VERSION")"
ARCH="x86_64"
APPDIR="$SCRIPT_DIR/SteamGrungeEditor.AppDir"
OUTFILE="$SCRIPT_DIR/Steam_Grunge_Editor-${VERSION}-${ARCH}.AppImage"
APPIMAGETOOL="$SCRIPT_DIR/appimagetool-${ARCH}.AppImage"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"

echo "━━ Steam Grunge Editor AppImage v${VERSION} ━━"

# 1. self-contained bundle (built + self-tested)
bash "$REPO_ROOT/packaging/linux/build-bundle.sh"
BUNDLE="$REPO_ROOT/dist/linux/steam-grunge-editor"

# 2. appimagetool
if [ ! -x "$APPIMAGETOOL" ]; then
    echo "[appimage] downloading appimagetool"
    wget -q "$APPIMAGETOOL_URL" -O "$APPIMAGETOOL"
    chmod +x "$APPIMAGETOOL"
fi

# 3. AppDir
echo "[appimage] AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$BUNDLE" "$APPDIR/usr/lib/steam-grunge-editor"
cp "$REPO_ROOT/packaging/desktop/steam-grunge-editor.desktop" "$APPDIR/"
cp "$REPO_ROOT/packaging/desktop/steam-grunge-editor.desktop" "$APPDIR/usr/share/applications/"
cp "$REPO_ROOT/app/assets/icon.png" "$APPDIR/steam-grunge-editor.png"
cp "$REPO_ROOT/app/assets/icon.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/steam-grunge-editor.png"
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/steam-grunge-editor/steam-grunge-editor" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# 4. AppImage
echo "[appimage] packing"
rm -f "$OUTFILE"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$ARCH" "$APPIMAGETOOL" --no-appstream "$APPDIR" "$OUTFILE"

# 5. the packed AppImage itself must start
echo "[appimage] self-test of the AppImage"
OUT="$(APPIMAGE_EXTRACT_AND_RUN=1 QT_QPA_PLATFORM=offscreen LC_ALL=C.UTF-8 timeout 180 "$OUTFILE" --self-test 2>&1 || true)"
echo "$OUT" | tail -3
echo "$OUT" | grep -q "SELF-TEST OK" || { echo "ERROR: AppImage self-test failed"; exit 1; }
echo "✓ $(basename "$OUTFILE")  $(du -h "$OUTFILE" | cut -f1)"
