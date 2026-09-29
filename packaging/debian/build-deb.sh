#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build-deb.sh — Steam Grunge Editor .deb (amd64)
#
#   bash packaging/debian/build-deb.sh
#   → packaging/debian/steam-grunge-editor_<VERSION>_amd64.deb
#
# Ships the self-contained PyInstaller folder from packaging/linux/build-bundle.sh
# in /usr/lib/steam-grunge-editor — no Python, venv or pip at install time
# (the old package ran `pip install` in postinst and needed internet).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$REPO_ROOT/VERSION")"
PKG="steam-grunge-editor"
PKGDIR="$SCRIPT_DIR/${PKG}_${VERSION}"
DEBFILE="$SCRIPT_DIR/${PKG}_${VERSION}_amd64.deb"

command -v dpkg-deb >/dev/null || { echo "ERROR: dpkg-deb not found (sudo apt-get install dpkg-dev)"; exit 1; }

echo "━━ Steam Grunge Editor .deb v${VERSION} ━━"
bash "$REPO_ROOT/packaging/linux/build-bundle.sh"
BUNDLE="$REPO_ROOT/dist/linux/steam-grunge-editor"

rm -rf "$PKGDIR"
mkdir -p "$PKGDIR/DEBIAN" "$PKGDIR/usr/bin" "$PKGDIR/usr/lib" \
         "$PKGDIR/usr/share/applications" "$PKGDIR/usr/share/icons/hicolor/256x256/apps" \
         "$PKGDIR/usr/share/doc/$PKG"

cp -a "$BUNDLE" "$PKGDIR/usr/lib/$PKG"
ln -s "/usr/lib/$PKG/$PKG" "$PKGDIR/usr/bin/$PKG"
cp "$REPO_ROOT/packaging/desktop/$PKG.desktop" "$PKGDIR/usr/share/applications/"
cp "$REPO_ROOT/app/assets/icon.png" "$PKGDIR/usr/share/icons/hicolor/256x256/apps/$PKG.png"

SIZE_KB="$(du -sk "$PKGDIR/usr" | cut -f1)"
cat > "$PKGDIR/DEBIAN/control" <<CONTROL
Package: $PKG
Version: ${VERSION}
Section: graphics
Priority: optional
Architecture: amd64
Installed-Size: ${SIZE_KB}
Depends: libgl1, libegl1, libfontconfig1, libxkbcommon0, libxkbcommon-x11-0, libdbus-1-3,
 libxcb-cursor0, libxcb-icccm4, libxcb-keysyms1, libxcb-randr0, libxcb-render-util0,
 libxcb-shape0, libxcb-xinerama0, libxcb-xkb1
Maintainer: Huzzama <https://github.com/Huzzama>
Homepage: https://github.com/Huzzama/Steam-Grunge
Description: Grunge-style Steam artwork editor
 Create distressed, grunge-style custom artwork for your Steam library:
 search SteamGridDB, add layers, film grain and VHS effects, and apply
 covers, heroes, logos and icons straight to Steam.
CONTROL

cat > "$PKGDIR/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
update-desktop-database -q /usr/share/applications 2>/dev/null || true
gtk-update-icon-cache -q -f -t /usr/share/icons/hicolor 2>/dev/null || true
POSTINST
cp "$PKGDIR/DEBIAN/postinst" "$PKGDIR/DEBIAN/postrm"
chmod 755 "$PKGDIR/DEBIAN/postinst" "$PKGDIR/DEBIAN/postrm"

cat > "$PKGDIR/usr/share/doc/$PKG/copyright" <<COPYRIGHT
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: $PKG
Source: https://github.com/Huzzama/Steam-Grunge
License: MIT
COPYRIGHT

rm -f "$DEBFILE"
dpkg-deb --root-owner-group --build "$PKGDIR" "$DEBFILE" >/dev/null
dpkg-deb --info "$DEBFILE" | sed -n '1,12p'
rm -rf "$PKGDIR"
echo "✓ $(basename "$DEBFILE")  $(du -h "$DEBFILE" | cut -f1)"
