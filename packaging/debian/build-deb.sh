#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build-deb.sh — Builds Steam Grunge Editor as a .deb package
#
# Works when called from any directory — uses REPO_ROOT to find files.
# ─────────────────────────────────────────────────────────────────────────────
set -e

# ── Resolve repo root regardless of where the script is called from ───────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

VERSION=$(cat "$REPO_ROOT/VERSION" 2>/dev/null || echo "1.0.0")
PKG="steam-grunge-editor"
PKGDIR="$SCRIPT_DIR/${PKG}_${VERSION}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Building Steam Grunge Editor .deb v${VERSION}"
echo "  Repo root: $REPO_ROOT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Create debian package directory tree ──────────────────────────────────────
rm -rf "$PKGDIR"
mkdir -p "$PKGDIR"/{DEBIAN,\
usr/bin,\
usr/lib/steam-grunge-editor,\
usr/share/applications,\
usr/share/icons/hicolor/256x256/apps,\
usr/share/doc/steam-grunge-editor}

# ── DEBIAN/control ────────────────────────────────────────────────────────────
cat > "$PKGDIR/DEBIAN/control" << CONTROL
Package: steam-grunge-editor
Version: ${VERSION}
Section: graphics
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-pip, python3-venv, libgl1
Maintainer: Huzzama <https://github.com/Huzzama>
Homepage: https://github.com/Huzzama/Steam-Grunge
Description: Grunge-style Steam artwork editor
 Steam Grunge Editor lets you create distressed and grunge-style
 custom artwork for your Steam library. Search SteamGridDB, apply
 film grain and VHS effects, and sync directly to Steam.
CONTROL

# ── DEBIAN/postinst ───────────────────────────────────────────────────────────
cat > "$PKGDIR/DEBIAN/postinst" << 'POSTINST'
#!/bin/bash
set -e
APP_DIR="/usr/lib/steam-grunge-editor"
VENV_DIR="$APP_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Setting up Steam Grunge Editor Python environment..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip
    "$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
fi
update-desktop-database /usr/share/applications/ 2>/dev/null || true
gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true
POSTINST
chmod 755 "$PKGDIR/DEBIAN/postinst"

# ── DEBIAN/prerm ──────────────────────────────────────────────────────────────
cat > "$PKGDIR/DEBIAN/prerm" << 'PRERM'
#!/bin/bash
rm -rf /usr/lib/steam-grunge-editor/venv
PRERM
chmod 755 "$PKGDIR/DEBIAN/prerm"

# ── Copy application files ────────────────────────────────────────────────────
cp -r "$REPO_ROOT/app"              "$PKGDIR/usr/lib/steam-grunge-editor/"
cp    "$REPO_ROOT/requirements.txt" "$PKGDIR/usr/lib/steam-grunge-editor/"
cp    "$REPO_ROOT/VERSION"          "$PKGDIR/usr/lib/steam-grunge-editor/" 2>/dev/null || true

# ── Launcher script ───────────────────────────────────────────────────────────
cat > "$PKGDIR/usr/bin/steam-grunge-editor" << 'LAUNCHER'
#!/usr/bin/env bash
exec /usr/lib/steam-grunge-editor/venv/bin/python \
     /usr/lib/steam-grunge-editor/app/main.py "$@"
LAUNCHER
chmod 755 "$PKGDIR/usr/bin/steam-grunge-editor"

# ── Desktop integration ───────────────────────────────────────────────────────
cp "$REPO_ROOT/packaging/desktop/steam-grunge-editor.desktop" \
   "$PKGDIR/usr/share/applications/"
cp "$REPO_ROOT/app/assets/icon.png" \
   "$PKGDIR/usr/share/icons/hicolor/256x256/apps/steam-grunge-editor.png"

# ── Copyright ─────────────────────────────────────────────────────────────────
cat > "$PKGDIR/usr/share/doc/steam-grunge-editor/copyright" << COPYRIGHT
Upstream-Name: Steam Grunge Editor
Upstream-Contact: https://github.com/Huzzama/Steam-Grunge
Source: https://github.com/Huzzama/Steam-Grunge
License: MIT
COPYRIGHT

# ── Build .deb ────────────────────────────────────────────────────────────────
fakeroot dpkg-deb --build "$PKGDIR"
mv "${PKGDIR}.deb" "$SCRIPT_DIR/${PKG}_${VERSION}_all.deb"

echo ""
echo "✓ Done! Output: ${PKG}_${VERSION}_all.deb"
echo ""
echo "To install: sudo dpkg -i ${PKG}_${VERSION}_all.deb"
