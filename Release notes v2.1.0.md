## Steam Grunge Editor v2.1.0

Create distressed, grunge-style custom artwork for your Steam library.

---

### What's new in v2.1.0

#### 🔄 Pro-level post-sync strategy system

Steam no longer needs to be manually restarted after syncing artwork.
A new configurable strategy engine handles invalidation automatically:

| Strategy | Behaviour |
|----------|-----------|
| `soft` | Touch folders + send `steam://reload/<appid>` *(default)* |
| `restart` | Full Steam restart — shutdown → settle → relaunch |
| `auto` | Smart: restarts if ≥ 5 files changed, otherwise soft |
| `none` | Write files only, no Steam signal |

#### 🎮 Game-running guard

Before any Steam restart, the app checks whether a game is currently running.

- **Silent mode** → falls back to `soft` automatically — no gameplay interruption, ever
- **Interactive mode** → prompts the user before proceeding

Detection covers native Linux games, Proton/Wine games (`pressure-vessel`, `reaper`),
and uses `SteamAppId` environment variable inspection as the definitive signal.

#### 🟦 Steam Deck & Flatpak support

Steam Deck ships with Flatpak Steam as the default install. v2.1.0 adds full support:

- Flatpak Steam root path auto-detected (`~/.var/app/com.valvesoftware.Steam/data/Steam`)
- Steam IPC pipe checked at both native (`~/.steam/steam.pipe`) and Flatpak XDG runtime paths
- `xdg-open` fallback for `steam://reload` when pipe is unavailable
- Restart uses `flatpak kill` / `flatpak run` instead of bare `steam` binary — fixes silent no-op on Deck

#### ⚡ Batch sync — single post-sync execution

Bulk sync no longer restarts Steam once per game file. All artwork is written first,
then a single post-sync signal fires at the end. `BulkSyncExecutor` logs a summary
line after each batch: `ok=N  errors=N  skipped=N`.

#### 📋 Rotating file logger

All sync operations are now logged to `~/.config/steam-grunge-editor/logs/steamSync.log`:

- Rotating file handler: 1 MB max per file, 3 backups kept
- Session-start marker on each run for easy log navigation
- Stdout output unchanged — all existing `[steamSync]` prints preserved

---

### Downloads

| File | Platform |
|------|----------|
| `Steam_Grunge_Editor-*-x86_64.AppImage` | 🐧 Any Linux distro (universal) |
| `steam-grunge-editor_*_all.deb` | 🐧 Ubuntu, Mint, Debian, Pop!\_OS |
| `steam-grunge-editor-*.fc41.x86_64.rpm` | 🐧 Fedora, Bazzite, rpm-ostree |
| `SteamGrungeEditor-*-Setup.exe` | 🪟 Windows 10/11 |
| `Steam_Grunge_Editor-*.dmg` | 🍎 macOS Big Sur 11.0+ |

---

### Install

**🐧 AppImage:**
```bash
chmod +x Steam_Grunge_Editor-*-x86_64.AppImage
./Steam_Grunge_Editor-*-x86_64.AppImage
```

**🐧 Debian / Ubuntu / Linux Mint:**
```bash
sudo dpkg -i steam-grunge-editor_*_all.deb
sudo apt-get install -f
```

**🐧 Fedora Workstation:**
```bash
sudo dnf install ./steam-grunge-editor-*.rpm
```

**🐧 Fedora Atomic / Bazzite / Silverblue (rpm-ostree):**
```bash
rpm-ostree install ./steam-grunge-editor-*.rpm
```

**🐧 Arch Linux (AUR):**
```bash
yay -S steam-grunge-editor
```

**🪟 Windows:** Run the `.exe` installer and follow the wizard.

**🍎 macOS:** Open the `.dmg`, drag to Applications.
First launch: right-click → Open (bypasses Gatekeeper warning).

---

### Verify checksums
```bash
sha256sum -c SHA256SUMS.txt
```

---

See [CHANGELOG.md](https://github.com/Huzzama/Steam-Grunge/blob/main/CHANGELOG.md) for full technical details.