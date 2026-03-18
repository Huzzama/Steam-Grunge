#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build-rpm.sh — Prepares the rpmbuild tree and builds the RPM.
# Run this from the repository root.
# ─────────────────────────────────────────────────────────────────────────────
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION=$(cat "$REPO_ROOT/VERSION")
export APP_VERSION="$VERSION"

TARBALL_NAME="steam-grunge-editor-bin-${VERSION}"
RPMBUILD_ROOT="$HOME/rpmbuild"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Building RPM for Steam Grunge Editor v${VERSION}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Ensure rpmbuild dirs exist ─────────────────────────────────────────────
echo "[1/5] Setting up rpmbuild tree..."
rpmdev-setuptree   # creates ~/rpmbuild/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

# ── 2. Build the source tarball from the PyInstaller binary ──────────────────
echo "[2/5] Creating source tarball..."
STAGING="/tmp/${TARBALL_NAME}"
rm -rf "$STAGING"
mkdir -p "$STAGING"
cp "$REPO_ROOT/dist/steam-grunge-editor" "$STAGING/"

tar -czf "$RPMBUILD_ROOT/SOURCES/${TARBALL_NAME}.tar.gz" \
    -C /tmp "$TARBALL_NAME"
rm -rf "$STAGING"

# ── 3. Copy remaining sources ─────────────────────────────────────────────────
echo "[3/5] Copying sources..."
cp "$REPO_ROOT/packaging/desktop/steam-grunge-editor.desktop" \
   "$RPMBUILD_ROOT/SOURCES/"
cp "$REPO_ROOT/app/assets/icon.png" \
   "$RPMBUILD_ROOT/SOURCES/steam-grunge-editor.png"

# ── 4. Copy spec file ─────────────────────────────────────────────────────────
echo "[4/5] Installing spec file..."
cp "$REPO_ROOT/packaging/fedora/steam-grunge-editor.spec" \
   "$RPMBUILD_ROOT/SPECS/"

# ── 5. Build the RPM ──────────────────────────────────────────────────────────
echo "[5/5] Running rpmbuild..."
rpmbuild -bb \
    --define "APP_VERSION ${VERSION}" \
    "$RPMBUILD_ROOT/SPECS/steam-grunge-editor.spec"

echo ""
echo "✓ RPM built. Find it in:"
find "$RPMBUILD_ROOT/RPMS" -name "*.rpm" | sort