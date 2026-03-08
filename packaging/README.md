# Steam Grunge Editor — Linux Packaging

Complete packaging system for building and distributing Steam Grunge Editor
across all major Linux distributions.

---

## Directory Structure

```
packaging/
├── appimage/
│   └── build-appimage.sh       ← builds universal AppImage
├── debian/
│   └── build-deb.sh            ← builds .deb for Ubuntu/Mint/Debian
├── arch/
│   ├── PKGBUILD                ← Arch Linux / AUR package definition
│   └── .SRCINFO                ← AUR metadata
├── desktop/
│   └── steam-grunge-editor.desktop  ← Linux desktop entry
├── test-packages.sh            ← local test runner
└── README.md                   ← this file

.github/
└── workflows/
    └── release.yml             ← GitHub Actions auto-build on tag push
```

---

## Quick Start

### Build all packages locally

```bash
cd packaging

# AppImage (universal)
cd appimage && chmod +x build-appimage.sh && ./build-appimage.sh && cd ..

# .deb (Ubuntu / Linux Mint / Debian)
sudo apt install fakeroot dpkg-dev python3-venv
cd debian && chmod +x build-deb.sh && ./build-deb.sh && cd ..

# Arch Linux
cd arch && makepkg -si && cd ..
```

---

## Package Formats

### 1. AppImage (Universal)

Works on any Linux distro with FUSE support. No installation required — just
make it executable and run.

**Build:**
```bash
cd packaging/appimage
./build-appimage.sh
```

**Output:** `Steam_Grunge_Editor-1.0.0-x86_64.AppImage`

**User install:**
```bash
chmod +x Steam_Grunge_Editor-1.0.0-x86_64.AppImage
./Steam_Grunge_Editor-1.0.0-x86_64.AppImage
```

**Optional — integrate into the system launcher:**
```bash
# Install appimagelauncher for automatic desktop integration
# https://github.com/TheAssassin/AppImageLauncher
```

---

### 2. .deb Package (Debian / Ubuntu / Linux Mint)

Standard Debian package. Installs system-wide with proper desktop integration.

**Build requirements:**
```bash
sudo apt install fakeroot dpkg-dev python3-venv
```

**Build:**
```bash
cd packaging/debian
./build-deb.sh
```

**Output:** `steam-grunge-editor_1.0.0_all.deb`

**User install:**
```bash
sudo dpkg -i steam-grunge-editor_1.0.0_all.deb
sudo apt-get install -f    # fix any missing deps if needed
```

**Uninstall:**
```bash
sudo dpkg -r steam-grunge-editor
```

**Install paths:**
```
/usr/bin/steam-grunge-editor          ← launcher script
/usr/lib/steam-grunge-editor/app/     ← application source
/usr/lib/steam-grunge-editor/venv/    ← Python virtual environment
/usr/share/applications/              ← .desktop file
/usr/share/icons/hicolor/256x256/     ← app icon
```

---

### 3. Arch Linux / AUR (PKGBUILD)

For Arch Linux, Manjaro, EndeavourOS, and other Arch-based distros.

**Build locally:**
```bash
cd packaging/arch
makepkg -si
```

**Submit to AUR (maintainer only):**
```bash
# 1. Create an AUR account at https://aur.archlinux.org
# 2. Add your SSH key to your AUR profile

# 3. Clone the AUR package repo (first time only)
git clone ssh://aur@aur.archlinux.org/steam-grunge-editor.git aur-repo

# 4. Copy files
cp packaging/arch/PKGBUILD aur-repo/
cp packaging/arch/.SRCINFO aur-repo/

# 5. Push
cd aur-repo
git add PKGBUILD .SRCINFO
git commit -m "Update to v1.0.0"
git push
```

**User AUR install (yay):**
```bash
yay -S steam-grunge-editor
```

---

## Desktop Integration

The `.desktop` file at `packaging/desktop/steam-grunge-editor.desktop`
registers the app with:
- Application launchers (GNOME, KDE, XFCE, etc.)
- File manager right-click (opens PNG/JPG/WebP files)
- Search results in GNOME/KDE search

**Validate the .desktop file:**
```bash
sudo apt install desktop-file-utils
desktop-file-validate packaging/desktop/steam-grunge-editor.desktop
```

**Install manually for testing:**
```bash
cp packaging/desktop/steam-grunge-editor.desktop ~/.local/share/applications/
cp app/assets/icon.png ~/.local/share/icons/steam-grunge-editor.png
update-desktop-database ~/.local/share/applications/
```

---

## Testing Locally

Use the test script to validate all packages before releasing:

```bash
cd packaging
chmod +x test-packages.sh

# Test everything
./test-packages.sh all

# Test individual formats
./test-packages.sh appimage
./test-packages.sh deb
./test-packages.sh arch

# Test .deb with full install/uninstall (requires sudo)
INSTALL_TEST=1 ./test-packages.sh deb
```

---

## Automated Releases (GitHub Actions)

The workflow at `.github/workflows/release.yml` automatically builds and
publishes packages whenever you push a version tag.

**How to trigger a release:**
```bash
# 1. Update VERSION file
echo "1.1.0" > VERSION
git add VERSION
git commit -m "Bump version to 1.1.0"

# 2. Tag the release
git tag v1.1.0
git push origin main --tags
```

GitHub Actions will then:
1. Build the AppImage on Ubuntu
2. Build the .deb on Ubuntu
3. Create a GitHub Release with both files attached
4. Generate a `SHA256SUMS.txt` checksum file

---

## GitHub Release Structure

Each release on GitHub will contain:

```
Steam Grunge Editor v1.0.0
├── Steam_Grunge_Editor-1.0.0-x86_64.AppImage   ← universal
├── steam-grunge-editor_1.0.0_all.deb            ← Debian/Ubuntu/Mint
└── SHA256SUMS.txt                                ← checksums
```

Arch Linux users install via AUR (`yay -S steam-grunge-editor`), which
automatically pulls the source from the GitHub release tag.

---

## VERSION File

Keep a `VERSION` file in the project root. All build scripts and the GitHub
Actions workflow read from this file.

```bash
cat VERSION
# 1.0.0
```

Update it before tagging:
```bash
echo "1.1.0" > VERSION
```

---

## Checklist Before Each Release

- [ ] Update `VERSION` file
- [ ] Test AppImage locally: `./packaging/appimage/build-appimage.sh`
- [ ] Test .deb locally: `./packaging/debian/build-deb.sh`
- [ ] Validate .desktop file: `desktop-file-validate packaging/desktop/steam-grunge-editor.desktop`
- [ ] Run test suite: `./packaging/test-packages.sh all`
- [ ] Update `PKGBUILD` pkgver and sha256sums
- [ ] Regenerate .SRCINFO: `cd packaging/arch && makepkg --printsrcinfo > .SRCINFO`
- [ ] Tag and push: `git tag vX.Y.Z && git push origin main --tags`
- [ ] Verify GitHub Actions run succeeds
- [ ] Update AUR repo with new PKGBUILD + .SRCINFO
