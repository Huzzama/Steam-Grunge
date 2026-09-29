#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build-bundle.sh — self-contained Linux build shared by the AppImage, .deb
# and .rpm: PyInstaller folder bundle in  dist/linux/steam-grunge-editor/
# (no system Python needed at runtime), then a headless self-test that builds
# the whole UI and checks the bundled assets.
#
#   bash packaging/linux/build-bundle.sh          # reuses an existing bundle
#   SGE_REBUILD=1 bash packaging/linux/build-bundle.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUT="$REPO_ROOT/dist/linux"
BUNDLE="$OUT/steam-grunge-editor"
BIN="$BUNDLE/steam-grunge-editor"
VENV="$REPO_ROOT/.build-venv"
PYTHON="${PYTHON:-python3}"

if [ -x "$BIN" ] && [ "${SGE_REBUILD:-0}" != "1" ]; then
    echo "[bundle] reusing $BUNDLE"
else
    echo "[bundle] build venv ($($PYTHON --version))"
    [ -d "$VENV" ] || "$PYTHON" -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r "$REPO_ROOT/requirements.txt" pyinstaller

    echo "[bundle] PyInstaller"
    rm -rf "$OUT" "$REPO_ROOT/build/linux"
    ( cd "$REPO_ROOT" && "$VENV/bin/pyinstaller" packaging/linux/steam_grunge_editor_linux.spec \
        --noconfirm --clean --distpath "$OUT" --workpath "$REPO_ROOT/build/linux" )
fi

[ -x "$BIN" ] || { echo "ERROR: $BIN not built"; exit 1; }

echo "[bundle] self-test"
OUTPUT="$(QT_QPA_PLATFORM=offscreen LC_ALL=C.UTF-8 timeout 120 "$BIN" --self-test 2>&1 || true)"
echo "$OUTPUT" | tail -5
echo "$OUTPUT" | grep -q "SELF-TEST OK" || { echo "ERROR: bundle self-test failed"; exit 1; }
echo "[bundle] OK — $(du -sh "$BUNDLE" | cut -f1)  $("$BIN" --version)"
