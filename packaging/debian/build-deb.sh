#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build-deb.sh — Builds Steam Grunge Editor as a .deb package
#
# Usage:
#   chmod +x build-deb.sh
#   ./build-deb.sh
#
# Requirements:
#   sudo apt install python3-stdeb fakeroot dpkg-dev
#
# Output:
#   steam-grunge-editor_1.0.0_all.deb
# ─────────────────────────────────────────────────────────────────────────────
set -e

VERSION=$(cat ../../VERSION 2>/dev/null || echo "1.0.0")
PKG="steam-grunge-editor"
PKGDIR="${PKG}_${VERSION}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Building Steam Grunge Editor .deb v${VERSION}"
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
cat > "$PKGDIR/DEBIAN/control" << EOF
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
EOF

# ── DEBIAN/postinst — install Python deps after package install ───────────────
cat > "$PKGDIR/DEBIAN/postinst" << 'EOF'
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

# Register desktop file and icon
update-desktop-database /usr/share/applications/ 2>/dev/null || true
gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true
EOF
chmod 755 "$PKGDIR/DEBIAN/postinst"

# ── DEBIAN/prerm — cleanup venv on uninstall ──────────────────────────────────
cat > "$PKGDIR/DEBIAN/prerm" << 'EOF'
#!/bin/bash
rm -rf /usr/lib/steam-grunge-editor/venv
EOF
chmod 755 "$PKGDIR/DEBIAN/prerm"

# ── Copy application files ────────────────────────────────────────────────────
cp -r ../../app          "$PKGDIR/usr/lib/steam-grunge-editor/"
cp    ../../requirements.txt "$PKGDIR/usr/lib/steam-grunge-editor/"
cp    ../../VERSION       "$PKGDIR/usr/lib/steam-grunge-editor/" 2>/dev/null || true

# ── Launcher script ───────────────────────────────────────────────────────────
cat > "$PKGDIR/usr/bin/steam-grunge-editor" << 'EOF'
#!/usr/bin/env bash
exec /usr/lib/steam-grunge-editor/venv/bin/python \
     /usr/lib/steam-grunge-editor/app/main.py "$@"
EOF
chmod 755 "$PKGDIR/usr/bin/steam-grunge-editor"

# ── Desktop integration ───────────────────────────────────────────────────────
cp ../desktop/steam-grunge-editor.desktop \
   "$PKGDIR/usr/share/applications/"
cp ../../app/assets/icon.png \
   "$PKGDIR/usr/share/icons/hicolor/256x256/apps/steam-grunge-editor.png"

# ── Changelog / copyright ─────────────────────────────────────────────────────
cat > "$PKGDIR/usr/share/doc/steam-grunge-editor/copyright" << EOF
Upstream-Name: Steam Grunge Editor
Upstream-Contact: https://github.com/Huzzama/Steam-Grunge
Source: https://github.com/Huzzama/Steam-Grunge

License: MIT
EOF

# ── Build .deb ────────────────────────────────────────────────────────────────
fakeroot dpkg-deb --build "$PKGDIR"
mv "${PKGDIR}.deb" "${PKG}_${VERSION}_all.deb"

echo ""
echo "✓ Done! Output: ${PKG}_${VERSION}_all.deb"
echo ""
echo "To install locally:"
echo "  sudo dpkg -i ${PKG}_${VERSION}_all.deb"
echo "  sudo apt-get install -f   # fix any missing dependencies"
