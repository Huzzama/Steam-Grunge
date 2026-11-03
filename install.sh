#!/bin/sh
# Steam Grunge Editor — installer for any Linux distro (x86_64), no root needed.
#
#   curl -fsSL https://raw.githubusercontent.com/Huzzama/Steam-Grunge/main/install.sh | sh
#   curl -fsSL https://raw.githubusercontent.com/Huzzama/Steam-Grunge/main/install.sh | sh -s -- --uninstall
#
# Installs the latest release AppImage for the current user:
#   ~/.local/share/steam-grunge-editor/appimage/steam-grunge-editor.AppImage
#   ~/.local/bin/steam-grunge-editor                 (launcher)
#   ~/.local/share/applications/steam-grunge-editor.desktop
#   ~/.local/share/icons/hicolor/256x256/apps/steam-grunge-editor.png
# Run it again to update. Debian/Ubuntu, Fedora and Arch users can use the
# .deb / .rpm from the release page or the AUR package instead.
set -eu

REPO="Huzzama/Steam-Grunge"
BRANCH="${SGE_BRANCH:-main}"
APP="steam-grunge-editor"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN="$HOME/.local/bin"
DIR="$DATA/$APP/appimage"          # next to the app's own data folder, never inside it
RAW="https://raw.githubusercontent.com/$REPO/$BRANCH"

say()  { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;31m!!\033[0m %s\n' "$*" >&2; }
die()  { warn "$*"; exit 1; }

fetch() { # url dest
    if command -v curl >/dev/null 2>&1; then curl -fL --progress-bar -o "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then wget -q --show-progress -O "$2" "$1"
    else die "curl or wget is required"; fi
}
fetch_text() { # url
    if command -v curl >/dev/null 2>&1; then curl -fsSL "$1"; else wget -qO- "$1"; fi
}

uninstall() {
    say "Removing Steam Grunge Editor"
    pkill -f "$DIR/$APP.AppImage" 2>/dev/null || true
    rm -rf "$DIR"
    rm -f "$BIN/$APP" "$DATA/applications/$APP.desktop" "$DATA/icons/hicolor/256x256/apps/$APP.png"
    say "Done. Your projects, fonts and settings stay in $DATA/$APP (delete it to reset)."
    exit 0
}

[ "${1:-}" = "--uninstall" ] && uninstall

[ "$(uname -s)" = Linux ] || die "this installer is for Linux (Windows and macOS builds are on the release page)"
[ "$(uname -m)" = x86_64 ] || die "only x86_64 builds are published (you have $(uname -m))"

say "Looking up the latest release of $REPO"
JSON=$(fetch_text "https://api.github.com/repos/$REPO/releases/latest") || die "could not reach GitHub"
URL=$(printf '%s' "$JSON" | grep -o '"browser_download_url": *"[^"]*\.AppImage"' | head -n1 | sed 's/.*"\(https[^"]*\)"/\1/')
TAG=$(printf '%s' "$JSON" | grep -o '"tag_name": *"[^"]*"' | head -n1 | sed 's/.*"\([^"]*\)"$/\1/')
[ -n "$URL" ] || die "the latest release has no AppImage"

say "Downloading Steam Grunge Editor $TAG"
mkdir -p "$DIR" "$BIN" "$DATA/applications" "$DATA/icons/hicolor/256x256/apps"
fetch "$URL" "$DIR/$APP.AppImage.part"
mv "$DIR/$APP.AppImage.part" "$DIR/$APP.AppImage"
chmod +x "$DIR/$APP.AppImage"
printf '%s\n' "$TAG" > "$DIR/version"

# AppImages mount themselves with FUSE. Without libfuse they can still run by
# extracting to a temp dir first, so the launcher falls back to that.
cat > "$BIN/$APP" <<EOF
#!/bin/sh
APPIMAGE_FILE="$DIR/$APP.AppImage"
if ! ldconfig -p 2>/dev/null | grep -Eq 'libfuse\.so\.(2|3)' && [ ! -e /usr/lib/libfuse.so.2 ] && [ ! -e /usr/lib64/libfuse.so.2 ]; then
    export APPIMAGE_EXTRACT_AND_RUN=1
fi
exec "\$APPIMAGE_FILE" "\$@"
EOF
chmod +x "$BIN/$APP"

fetch "$RAW/app/assets/icon.png" "$DATA/icons/hicolor/256x256/apps/$APP.png" 2>/dev/null || warn "icon not downloaded"
cat > "$DATA/applications/$APP.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Steam Grunge Editor
GenericName=Steam artwork editor
Comment=Grunge and VHS covers for your Steam library, applied straight to Steam
Exec=$BIN/$APP
Icon=$APP
Terminal=false
Categories=Graphics;Game;
Keywords=steam;artwork;cover;grid;vhs;grunge;
StartupWMClass=steam-grunge-editor
EOF
if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database "$DATA/applications" >/dev/null 2>&1 || true; fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q "$DATA/icons/hicolor" >/dev/null 2>&1 || true; fi

case ":$PATH:" in *":$BIN:"*) ;; *) warn "$BIN is not in your PATH — start it from the app menu, or add $BIN to PATH";; esac
if ! ldconfig -p 2>/dev/null | grep -Eq 'libfuse\.so\.(2|3)'; then
    warn "libfuse not found: the app still runs (extract mode, slower start). Install fuse2 / libfuse2 for faster starts."
fi
say "Installed $TAG. Run: $APP   (or find \"Steam Grunge Editor\" in your app menu)"
say "Update: run this installer again.  Remove: … | sh -s -- --uninstall"
