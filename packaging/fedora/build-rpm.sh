#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build-rpm.sh — Steam Grunge Editor .rpm (x86_64, Fedora / Bazzite)
#
#   bash packaging/fedora/build-rpm.sh      (needs rpm-build + rpmdevtools)
#   → ~/rpmbuild/RPMS/x86_64/steam-grunge-editor-<VERSION>-1.<dist>.x86_64.rpm
#
# Ships the self-contained PyInstaller folder from packaging/linux/build-bundle.sh
# in /usr/lib/steam-grunge-editor (no system Python needed).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$REPO_ROOT/VERSION")"
[ -n "$VERSION" ] || { echo "ERROR: VERSION is empty"; exit 1; }
NAME="steam-grunge-editor"
SRC="${NAME}-bin-${VERSION}"
RPMBUILD_ROOT="$HOME/rpmbuild"

echo "━━ Steam Grunge Editor .rpm v${VERSION} ━━"
bash "$REPO_ROOT/packaging/linux/build-bundle.sh"

mkdir -p "$RPMBUILD_ROOT"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
STAGING="$(mktemp -d)"
mkdir -p "$STAGING/$SRC"
cp -a "$REPO_ROOT/dist/linux/$NAME" "$STAGING/$SRC/bundle"
cp "$REPO_ROOT/packaging/desktop/$NAME.desktop" "$STAGING/$SRC/"
cp "$REPO_ROOT/app/assets/icon.png" "$STAGING/$SRC/$NAME.png"
tar -czf "$RPMBUILD_ROOT/SOURCES/$SRC.tar.gz" -C "$STAGING" "$SRC"
rm -rf "$STAGING"

cp "$REPO_ROOT/packaging/fedora/$NAME.spec" "$RPMBUILD_ROOT/SPECS/"
rpmbuild -bb --define "APP_VERSION ${VERSION}" "$RPMBUILD_ROOT/SPECS/$NAME.spec"
echo "✓ RPM:"; find "$RPMBUILD_ROOT/RPMS" -name "*.rpm" | sort
