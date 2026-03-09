<div align="center">

<img src="app/assets/icon.png" alt="Steam Grunge Editor" width="120"/>

# Steam Grunge Editor

**Create distressed, grunge-style custom artwork for your Steam library.**  
Search SteamGridDB, apply film grain and VHS effects, export with correct Steam filenames, and sync directly to Steam — all from one desktop app.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/UI-PySide6-green)](https://doc.qt.io/qtforpython/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows-lightgrey)]()
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

</div>

---

## Screenshots

> *Coming soon*

---

## Features

- 🔍 **SteamGridDB Integration** — search and download game artwork directly inside the editor
- 🎨 **Layer-based canvas** — drag, resize, rotate, and blend multiple image layers
- 📼 **VHS & grunge effects** — film grain, chromatic aberration, scanlines, color grading
- 🖼️ **All Steam artwork types** — Cover, Wide Cover, VHS Cover, VHS Pile, VHS Cassette, Hero, Logo, Icon
- ✅ **Smart AppID detection** — auto-looks up the Steam AppID and confirms once per session
- 💾 **Correct filenames on export** — outputs `2050650.png`, `2050650p.png`, `2050650_hero.png`, etc.
- ⇪ **Sync to Steam** — copies exported files directly into your Steam `userdata/grid` folder
- 🖌️ **Custom brush engine** — import `.gbr`, `.png`, `.zip` brush packs with full pressure controls
- 🔤 **Font importer** — add `.ttf` / `.otf` fonts available in the text layer tool
- 🗂️ **Tab system** — work on multiple games at once, each tab has its own independent state
- 🌑 **Dark terminal aesthetic** — monospace UI designed for the Steam grunge look

---

## Artwork Templates

| Template | Size | Background |
|---|---|---|
| Cover | 600 × 900 | Solid |
| VHS Cover | 600 × 900 | Solid |
| Wide Cover | 920 × 430 | Solid |
| VHS Pile | 920 × 430 | Solid |
| VHS Cassette | 920 × 430 | Solid |
| Background / Hero | 3840 × 1240 | Solid |
| Logo | 1280 × 720 | **Transparent** |
| Icon | 512 × 512 | **Transparent** |

---

## Installation

### 🪟 Windows

Download `SteamGrungeEditor-Setup.exe` from [Releases](https://github.com/Huzzama/Steam-Grunge/releases) and run it.

- Next → Next → Install — standard Windows setup wizard
- Creates a Start Menu shortcut automatically
- Uninstall anytime from Programs & Features

> **Note:** Windows may show a SmartScreen warning on first run since the app is not yet code-signed. Click **More info → Run anyway** to proceed.

---

### 🐧 Linux

**Option A — AppImage** (any distro, no install needed)

```bash
chmod +x Steam_Grunge_Editor-x86_64.AppImage
./Steam_Grunge_Editor-x86_64.AppImage
```

**Option B — .deb** (Ubuntu / Linux Mint / Debian / Pop!_OS)

```bash
sudo dpkg -i steam-grunge-editor_1.0.0_all.deb
sudo apt-get install -f
```

**Option C — AUR** (Arch / Manjaro / EndeavourOS)

```bash
yay -S steam-grunge-editor
```

**Option D — Run from source** (any OS)

```bash
git clone https://github.com/Huzzama/Steam-Grunge.git
cd Steam-Grunge
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app/main.py
```

---

## Getting a SteamGridDB API Key

1. Go to [steamgriddb.com/profile/preferences/api](https://www.steamgriddb.com/profile/preferences/api)
2. Log in or create a free account
3. Click **Generate API Key** and copy it
4. In the app, open the search panel and paste your key when prompted

Your key is stored locally and never shared.

---

## Export & Sync Workflow

```
1. Search for a game in the left panel
2. Click any artwork thumbnail to add it as a canvas layer
3. Choose a template (Cover, Wide, Hero, Logo, Icon...)
4. Apply grunge effects using the right panel sliders
5. File → Export  (Ctrl+E)
      ├── Confirms Steam AppID once per session
      └── Saves file with correct Steam filename
6. Sync to Steam → Sync to Steam  (Ctrl+Shift+S)
      ├── Copies files into your Steam userdata/grid folder
      └── Restart Steam to see your new artwork
```

Exported files follow Steam's naming convention automatically:

| Template | Filename |
|---|---|
| Cover | `{appid}.png` |
| Wide / VHS variants | `{appid}p.png` |
| Hero | `{appid}_hero.png` |
| Logo | `{appid}_logo.png` |
| Icon | `{appid}_icon.png` |

---

## Project Structure

```
Steam-Grunge/
├── .github/
│   └── workflows/
│       ├── release.yml              <- builds AppImage + .deb on tag push
│       └── build-windows.yml        <- builds Windows installer on tag push
├── app/
│   ├── assets/
│   │   ├── brushes/                 <- brush library (.gbr, .png, .zip)
│   │   ├── fonts/                   <- custom fonts (.ttf, .otf)
│   │   ├── platformBars/            <- console bar overlays
│   │   ├── ratings/                 <- rating badge overlays
│   │   ├── templates/               <- template PNG overlays
│   │   ├── textures/                <- deterioration textures
│   │   ├── icon.png                 <- app icon
│   │   └── icon.ico                 <- Windows icon (auto-generated)
│   ├── editor/                      <- compositor, exports, templates
│   ├── filters/                     <- color, film grain, VHS, distress
│   ├── services/                    <- SteamGridDB API, Steam sync, export flow
│   ├── ui/
│   │   ├── canvas/                  <- canvas engine (layers, fx, tools, handles)
│   │   └── ...                      <- panels, dialogs, widgets
│   ├── config.py
│   ├── main.py                      <- entry point
│   └── state.py
├── packaging/
│   ├── appimage/build-appimage.sh   <- Linux AppImage builder
│   ├── arch/PKGBUILD                <- Arch / AUR package
│   ├── debian/build-deb.sh          <- .deb builder
│   ├── desktop/                     <- Linux .desktop file
│   ├── windows/
│   │   ├── steam_grunge_editor.spec <- PyInstaller config
│   │   ├── steam_grunge_editor.iss  <- Inno Setup script
│   │   └── build-windows.bat        <- local Windows build script
│   └── shared/icons/                <- multi-size icons for packaging
├── data/                            <- cache & presets (git-ignored)
├── exports/                         <- exported artwork (git-ignored)
├── VERSION
├── requirements.txt
└── .gitignore
```

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+O` | Open image |
| `Ctrl+Shift+O` | Import image as layer |
| `Ctrl+E` | Export artwork |
| `Ctrl+Shift+E` | Export all assets |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `Ctrl+D` | Duplicate layer |
| `Delete` | Delete layer |
| `Ctrl+Shift+C` | Crop layer |
| `B` | Toggle brush panel |
| `E` | Eraser tool |
| `Ctrl+Shift+S` | Sync to Steam |
| `Ctrl+T` | New tab |
| `Ctrl+W` | Close tab |

---

## Contributing

Pull requests are welcome. For major changes please open an issue first to discuss what you would like to change.

---

## License

[MIT](LICENSE)

---

<div align="center">
Made with ♥ for the Steam community
</div>