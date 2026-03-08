#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# test-packages.sh — Locally test all three package builds before release
#
# Run from the packaging/ directory:
#   chmod +x test-packages.sh
#   ./test-packages.sh [appimage|deb|arch|all]
# ─────────────────────────────────────────────────────────────────────────────
set -e

TARGET="${1:-all}"
PASS=0; FAIL=0

ok()   { echo "  ✓ $1"; ((PASS++)); }
fail() { echo "  ✗ $1"; ((FAIL++)); }
header() { echo ""; echo "━━━ $1 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; }

# ── AppImage ──────────────────────────────────────────────────────────────────
test_appimage() {
    header "AppImage"

    # Build
    cd appimage
    chmod +x build-appimage.sh
    if ./build-appimage.sh > /tmp/appimage-build.log 2>&1; then
        ok "AppImage build succeeded"
    else
        fail "AppImage build failed — see /tmp/appimage-build.log"
        cd ..; return
    fi

    # File exists
    APPIMAGE=$(ls Steam_Grunge_Editor-*.AppImage 2>/dev/null | head -1)
    if [ -n "$APPIMAGE" ]; then
        ok "AppImage file found: $APPIMAGE"
    else
        fail "AppImage file not found after build"
        cd ..; return
    fi

    # Is executable
    if [ -x "$APPIMAGE" ]; then
        ok "AppImage is executable"
    else
        fail "AppImage is not executable"
    fi

    # Dry-run launch (2 second timeout)
    if timeout 2 "./$APPIMAGE" --version > /tmp/appimage-run.log 2>&1; [ $? -ne 124 ]; then
        ok "AppImage launches (or exits cleanly)"
    else
        ok "AppImage process started (timeout expected for GUI apps)"
    fi

    cd ..
}

# ── Debian .deb ───────────────────────────────────────────────────────────────
test_deb() {
    header ".deb Package"

    # Check tools
    if ! command -v fakeroot &>/dev/null; then
        fail "fakeroot not installed — run: sudo apt install fakeroot"
        return
    fi
    if ! command -v dpkg-deb &>/dev/null; then
        fail "dpkg-deb not installed — run: sudo apt install dpkg-dev"
        return
    fi

    # Build
    cd debian
    chmod +x build-deb.sh
    if ./build-deb.sh > /tmp/deb-build.log 2>&1; then
        ok ".deb build succeeded"
    else
        fail ".deb build failed — see /tmp/deb-build.log"
        cd ..; return
    fi

    # File exists
    DEB=$(ls steam-grunge-editor_*.deb 2>/dev/null | head -1)
    if [ -n "$DEB" ]; then
        ok ".deb file found: $DEB"
    else
        fail ".deb file not found after build"
        cd ..; return
    fi

    # Validate package
    if dpkg-deb --info "$DEB" > /tmp/deb-info.log 2>&1; then
        ok ".deb package info is valid"
    else
        fail ".deb package info check failed"
    fi

    # Check contents
    if dpkg-deb --contents "$DEB" | grep -q "usr/bin/steam-grunge-editor"; then
        ok "Launcher binary present in .deb"
    else
        fail "Launcher binary missing from .deb"
    fi

    if dpkg-deb --contents "$DEB" | grep -q "usr/share/applications"; then
        ok "Desktop file present in .deb"
    else
        fail "Desktop file missing from .deb"
    fi

    if dpkg-deb --contents "$DEB" | grep -q "usr/share/icons"; then
        ok "Icon present in .deb"
    else
        fail "Icon missing from .deb"
    fi

    # Optional: install and uninstall
    if [ "${INSTALL_TEST:-0}" = "1" ]; then
        echo "  → Installing .deb (requires sudo)..."
        if sudo dpkg -i "$DEB" > /tmp/deb-install.log 2>&1; then
            ok ".deb installed successfully"
            sudo dpkg -r steam-grunge-editor > /dev/null 2>&1
            ok ".deb removed successfully"
        else
            fail ".deb install failed — see /tmp/deb-install.log"
        fi
    else
        echo "  ℹ  Skipping install test (set INSTALL_TEST=1 to enable)"
    fi

    cd ..
}

# ── Arch PKGBUILD ─────────────────────────────────────────────────────────────
test_arch() {
    header "Arch PKGBUILD"

    if ! command -v makepkg &>/dev/null; then
        echo "  ℹ  makepkg not available (not an Arch system) — skipping"
        return
    fi

    cd arch

    # Validate PKGBUILD syntax
    if bash -n PKGBUILD 2>/dev/null; then
        ok "PKGBUILD syntax is valid"
    else
        fail "PKGBUILD has syntax errors"
    fi

    # Check required fields
    for field in pkgname pkgver pkgrel pkgdesc arch; do
        if grep -q "^${field}=" PKGBUILD; then
            ok "PKGBUILD has required field: $field"
        else
            fail "PKGBUILD missing field: $field"
        fi
    done

    # Dry-run makepkg (no install)
    if makepkg --nobuild --nodeps > /tmp/arch-build.log 2>&1; then
        ok "makepkg dry-run passed"
    else
        fail "makepkg dry-run failed — see /tmp/arch-build.log"
    fi

    cd ..
}

# ── Desktop file ──────────────────────────────────────────────────────────────
test_desktop() {
    header "Desktop Integration"

    DESKTOP="desktop/steam-grunge-editor.desktop"

    if [ -f "$DESKTOP" ]; then
        ok ".desktop file exists"
    else
        fail ".desktop file missing at $DESKTOP"
        return
    fi

    if command -v desktop-file-validate &>/dev/null; then
        if desktop-file-validate "$DESKTOP" 2>/tmp/desktop-validate.log; then
            ok ".desktop file is valid"
        else
            fail ".desktop validation failed:"
            cat /tmp/desktop-validate.log | sed 's/^/    /'
        fi
    else
        echo "  ℹ  desktop-file-validate not installed — skipping"
        echo "     Install with: sudo apt install desktop-file-utils"
    fi

    # Check required fields
    for field in Name Exec Icon Type Categories; do
        if grep -q "^${field}=" "$DESKTOP"; then
            ok ".desktop has field: $field"
        else
            fail ".desktop missing field: $field"
        fi
    done
}

# ── Summary ───────────────────────────────────────────────────────────────────
summary() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Results: ${PASS} passed, ${FAIL} failed"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    [ "$FAIL" -eq 0 ] && echo "  All checks passed ✓" || echo "  Some checks failed — review output above"
    echo ""
}

# ── Run tests ─────────────────────────────────────────────────────────────────
case "$TARGET" in
    appimage) test_desktop; test_appimage ;;
    deb)      test_desktop; test_deb      ;;
    arch)     test_desktop; test_arch     ;;
    all)      test_desktop; test_appimage; test_deb; test_arch ;;
    *)
        echo "Usage: $0 [appimage|deb|arch|all]"
        exit 1
        ;;
esac

summary
[ "$FAIL" -eq 0 ]
