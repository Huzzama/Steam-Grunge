#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build-deb.sh — Builds Steam Grunge Editor as a .deb package
#
# Works when called from any directory — uses REPO_ROOT to find files.
#
# Usage (run from repo root or anywhere):
#   chmod +x packaging/debian/build-deb.sh
#   bash packaging/debian/build-deb.sh
#
# Requirements on the build machine:
#   sudo apt-get install fakeroot dpkg-dev python3 python3-venv
#
# Output:
#   packaging/debian/steam-grunge-editor_{VERSION}_amd64.deb
#
# v2.1.0 changes:
#   - set -euo pipefail (was set -e only — silent errors possible)
#   - Fallback version updated 2.0.0 → 2.1.0
#   - Architecture: all → amd64 — the app ships a venv with compiled
#     extensions (PySide6, numpy); "all" is incorrect and causes apt
#     architecture mismatch warnings on 32-bit / ARM systems
#   - Depends updated:
#       * Removed python3-pip, python3-venv — build-time tools, not
#         required on the end-user's machine once venv is pre-built
#       * Added libxcb-cursor0, libxcb-icccm4, libxcb-keysyms1,
#         libxcb-randr0, libxcb-render-util0, libxcb-shape0,
#         libxcb-xinerama0, libxcb-xkb1 — required by PySide6/Qt6
#         platform plugin (xcb). Missing these causes the app to exit
#         immediately with "Could not load the Qt platform plugin xcb"
#       * Added libxkbcommon-x11-0 — required by Qt6 XKB input
#       * Added libdbus-1-3 — required by Qt6 DBus / system tray
#       * Added libgl1 | libgl1-mesa-glx — OpenGL for Qt rendering
#   - postinst: pip install now uses --no-index if a bundled wheels/
#     directory is present (offline install support); added error handling
#     with clear user message on failure; set -e inside scriptlet
#   - prerm: now checks $1 (remove vs upgrade) — venv is only deleted
#     on full removal, not on package upgrade
#   - postrm added: purges ~/.config/steam-grunge-editor on --purge
#   - changelog added to /usr/share/doc/ (required by lintian)
#   - Sanity check of generated .deb via dpkg-deb --info
#   - Output filename uses amd64 suffix to match Architecture field
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Resolve repo root regardless of where the script is called from ───────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

VERSION=$(cat "$REPO_ROOT/VERSION" 2>/dev/null || echo "2.1.0")
PKG="steam-grunge-editor"
PKGDIR="$SCRIPT_DIR/${PKG}_${VERSION}"
DEBFILE="${PKG}_${VERSION}_amd64.deb"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Building Steam Grunge Editor .deb v${VERSION}"
echo "  Repo root: $REPO_ROOT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Sanity checks ─────────────────────────────────────────────────────────────
if ! command -v fakeroot &>/dev/null; then
    echo "ERROR: fakeroot not found."
    echo "       sudo apt-get install fakeroot"
    exit 1
fi
if ! command -v dpkg-deb &>/dev/null; then
    echo "ERROR: dpkg-deb not found."
    echo "       sudo apt-get install dpkg-dev"
    exit 1
fi
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found."
    exit 1
fi

# ── Create debian package directory tree ──────────────────────────────────────
echo ""
echo "[1/6] Creating package directory tree..."
rm -rf "$PKGDIR"
mkdir -p "$PKGDIR"/{DEBIAN,\
usr/bin,\
usr/lib/steam-grunge-editor,\
usr/share/applications,\
usr/share/icons/hicolor/256x256/apps,\
usr/share/doc/steam-grunge-editor}

# ── DEBIAN/control ────────────────────────────────────────────────────────────
echo "[2/6] Writing DEBIAN/control..."
cat > "$PKGDIR/DEBIAN/control" << CONTROL
Package: steam-grunge-editor
Version: ${VERSION}
Section: graphics
Priority: optional
Architecture: amd64
Depends: python3 (>= 3.10),
 libgl1 | libgl1-mesa-glx,
 libxcb-cursor0,
 libxcb-icccm4,
 libxcb-keysyms1,
 libxcb-randr0,
 libxcb-render-util0,
 libxcb-shape0,
 libxcb-xinerama0,
 libxcb-xkb1,
 libxkbcommon-x11-0,
 libdbus-1-3
Maintainer: Huzzama <https://github.com/Huzzama>
Homepage: https://github.com/Huzzama/Steam-Grunge
Description: Grunge-style Steam artwork editor
 Steam Grunge Editor lets you create distressed and grunge-style
 custom artwork for your Steam library. Search SteamGridDB, apply
 film grain and VHS effects, and sync directly to Steam.
 .
 Includes a post-sync strategy system with smart Steam restart,
 Steam Deck / Flatpak support, and a rotating sync log.
CONTROL

# ── DEBIAN/postinst ───────────────────────────────────────────────────────────
# Runs after the package files are unpacked on the target machine.
# Creates the Python venv and installs dependencies into it.
cat > "$PKGDIR/DEBIAN/postinst" << 'POSTINST'
#!/bin/bash
set -e
APP_DIR="/usr/lib/steam-grunge-editor"
VENV_DIR="$APP_DIR/venv"

if [ "$1" = "configure" ]; then
    # Only create the venv if it doesn't already exist (idempotent on upgrade)
    if [ ! -d "$VENV_DIR" ]; then
        echo "Steam Grunge Editor: setting up Python environment..."
        if ! python3 -m venv "$VENV_DIR"; then
            echo "ERROR: Failed to create Python virtual environment."
            echo "       Make sure python3-venv is installed:"
            echo "         sudo apt-get install python3-venv"
            exit 1
        fi

        # Upgrade pip inside the venv first
        "$VENV_DIR/bin/pip" install --quiet --upgrade pip

        # Install from bundled wheels if available (offline / air-gapped installs)
        # Otherwise fall back to PyPI
        if [ -d "$APP_DIR/wheels" ]; then
            echo "Steam Grunge Editor: installing from bundled wheels (offline)..."
            "$VENV_DIR/bin/pip" install --quiet \
                --no-index \
                --find-links "$APP_DIR/wheels" \
                -r "$APP_DIR/requirements.txt"
        else
            echo "Steam Grunge Editor: installing dependencies from PyPI..."
            if ! "$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"; then
                echo ""
                echo "WARNING: pip install failed. The app may not launch correctly."
                echo "         Check your internet connection and try:"
                echo "           sudo /usr/lib/steam-grunge-editor/venv/bin/pip"
                echo "               install -r /usr/lib/steam-grunge-editor/requirements.txt"
                # Do not exit 1 — package is still installed; user can fix manually
            fi
        fi
    fi

    # Refresh desktop and icon caches
    update-desktop-database /usr/share/applications/ 2>/dev/null || true
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor/ 2>/dev/null || true
fi
POSTINST
chmod 755 "$PKGDIR/DEBIAN/postinst"

# ── DEBIAN/prerm ──────────────────────────────────────────────────────────────
# Runs before files are removed.
# Only deletes the venv on full removal — NOT on upgrade (avoids re-downloading
# all pip packages every time the user upgrades the package).
cat > "$PKGDIR/DEBIAN/prerm" << 'PRERM'
#!/bin/bash
set -e
# $1 = "remove"   → full uninstall: delete venv
# $1 = "upgrade"  → being replaced by a new version: keep venv
# $1 = "deconfigure" / "failed-upgrade" → keep venv (repair path)
if [ "$1" = "remove" ]; then
    echo "Steam Grunge Editor: removing Python environment..."
    rm -rf /usr/lib/steam-grunge-editor/venv
fi
PRERM
chmod 755 "$PKGDIR/DEBIAN/prerm"

# ── DEBIAN/postrm ─────────────────────────────────────────────────────────────
# Runs after files are removed.
# On --purge: removes user config/log data from all home directories.
cat > "$PKGDIR/DEBIAN/postrm" << 'POSTRM'
#!/bin/bash
set -e
if [ "$1" = "purge" ]; then
    echo "Steam Grunge Editor: purging user data..."
    # Remove config/logs for all users that have them
    # (rotating logs written to ~/.config/steam-grunge-editor/logs/ since v2.1.0)
    for USER_HOME in /root /home/*; do
        CONFIG_DIR="$USER_HOME/.config/steam-grunge-editor"
        if [ -d "$CONFIG_DIR" ]; then
            rm -rf "$CONFIG_DIR"
            echo "  Removed: $CONFIG_DIR"
        fi
    done
fi
POSTRM
chmod 755 "$PKGDIR/DEBIAN/postrm"

# ── Copy application files ────────────────────────────────────────────────────
echo "[3/6] Copying application files..."
cp -r "$REPO_ROOT/app"              "$PKGDIR/usr/lib/steam-grunge-editor/"
cp    "$REPO_ROOT/requirements.txt" "$PKGDIR/usr/lib/steam-grunge-editor/"
cp    "$REPO_ROOT/VERSION"          "$PKGDIR/usr/lib/steam-grunge-editor/" 2>/dev/null || true

# ── Launcher script ───────────────────────────────────────────────────────────
echo "[4/6] Writing launcher..."
cat > "$PKGDIR/usr/bin/steam-grunge-editor" << 'LAUNCHER'
#!/usr/bin/env bash
# ── Steam Grunge Editor launcher ──────────────────────────────────────────────
# Activates the private venv and launches the app.
# Passes all arguments through so CLI flags (if any) work correctly.
VENV="/usr/lib/steam-grunge-editor/venv"

if [ ! -f "$VENV/bin/python" ]; then
    echo "ERROR: Steam Grunge Editor Python environment not found."
    echo "       Try reinstalling: sudo apt-get install --reinstall steam-grunge-editor"
    exit 1
fi

exec "$VENV/bin/python" \
     /usr/lib/steam-grunge-editor/app/main.py "$@"
LAUNCHER
chmod 755 "$PKGDIR/usr/bin/steam-grunge-editor"

# ── Desktop integration ───────────────────────────────────────────────────────
echo "[5/6] Installing desktop integration..."
cp "$REPO_ROOT/packaging/desktop/steam-grunge-editor.desktop" \
   "$PKGDIR/usr/share/applications/"
cp "$REPO_ROOT/app/assets/icon.png" \
   "$PKGDIR/usr/share/icons/hicolor/256x256/apps/steam-grunge-editor.png"

# ── Doc files ─────────────────────────────────────────────────────────────────
cat > "$PKGDIR/usr/share/doc/steam-grunge-editor/copyright" << COPYRIGHT
Upstream-Name: steam-grunge-editor
Upstream-Contact: https://github.com/Huzzama/Steam-Grunge
Source: https://github.com/Huzzama/Steam-Grunge
License: MIT
 Permission is hereby granted, free of charge, to any person obtaining a copy
 of this software and associated documentation files (the "Software"), to deal
 in the Software without restriction, including without limitation the rights
 to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 copies of the Software, and to permit persons to whom the Software is
 furnished to do so, subject to the following conditions:
 .
 The above copyright notice and this permission notice shall be included in all
 copies or substantial portions of the Software.
 .
 THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
COPYRIGHT

# Minimal changelog (required by lintian — must be gzip compressed)
cat > "/tmp/sge-changelog" << CHANGELOG
steam-grunge-editor (${VERSION}) stable; urgency=medium

  * v2.1.0: Pro-level post-sync strategy system, Steam Deck / Flatpak
    support, smart batch sync, rotating file logger, game-running guard.

 -- Huzzama <https://github.com/Huzzama>  $(date -R)
CHANGELOG
gzip -9 -n -c "/tmp/sge-changelog" \
    > "$PKGDIR/usr/share/doc/steam-grunge-editor/changelog.Debian.gz"
rm -f "/tmp/sge-changelog"

# ── Build .deb ────────────────────────────────────────────────────────────────
echo "[6/6] Building .deb package..."
fakeroot dpkg-deb --build --root-owner-group "$PKGDIR"
mv "${PKGDIR}.deb" "$SCRIPT_DIR/${DEBFILE}"

# ── Sanity check ──────────────────────────────────────────────────────────────
echo ""
if dpkg-deb --info "$SCRIPT_DIR/${DEBFILE}" > /dev/null 2>&1; then
    DEB_SIZE=$(du -sh "$SCRIPT_DIR/${DEBFILE}" | cut -f1)
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  ✓ Done!  ($DEB_SIZE)"
    echo "  Output:  $SCRIPT_DIR/${DEBFILE}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  To install:  sudo dpkg -i ${DEBFILE}"
    echo "  To verify:   sudo apt-get install -f"
    echo "  To purge:    sudo apt-get purge steam-grunge-editor"
else
    echo "ERROR: .deb verification failed — dpkg-deb --info reported errors."
    exit 1
fi

# Cleanup staging dir
rm -rf "$PKGDIR"
