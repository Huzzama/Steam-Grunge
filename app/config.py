import os
from pathlib import Path

# ── Canvas sizes ──────────────────────────────────────────────────────────────
COVER_SIZE      = (600, 900)
WIDE_SIZE       = (920, 430)
VHS_COVER_SIZE  = (600, 900)   
HERO_SIZE       = (3840, 1240) 
LOGO_SIZE       = (1280, 720)  
ICON_SIZE       = (512, 512)   

# Templates that export with a transparent background (no solid fill)
TRANSPARENT_TEMPLATES = {"logo", "icon"}

# Wide-format template variants (all share WIDE_SIZE = 920x430)
WIDE_TEMPLATE_VARIANTS = ["wide", "vhs_pile", "vhs_cassette"]

# Steam custom-artwork filenames inside userdata/<id>/config/grid/
# Single source of truth — export, sync, drive sync and the sync dialog all use it.
#   {appid}p.png  → PORTRAIT capsule (600x900)  ← "p" = portrait
#   {appid}.png   → WIDE capsule (920x430 / header)
GRID_FILENAMES = {
    "cover":        "{appid}p.png",
    "vhs_cover":    "{appid}p.png",
    "wide":         "{appid}.png",
    "vhs_pile":     "{appid}.png",
    "vhs_cassette": "{appid}.png",
    "hero":         "{appid}_hero.png",
    "logo":         "{appid}_logo.png",
    "icon":         "{appid}_icon.png",
}


def grid_filename(app_id, template: str) -> str:
    """Return the Steam grid filename for a template (unknown → {appid}_{template}.png)."""
    return GRID_FILENAMES.get(template, "{appid}_" + template + ".png").format(appid=app_id)


# Layout zones
COVER_SPINE_WIDTH          = 40
COVER_PLATFORM_BAR_HEIGHT  = 70

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent
ASSETS_DIR = BASE_DIR / "app" / "assets"

_USER_DATA_DIR = Path(
    os.environ.get("XDG_DATA_HOME",
                   Path.home() / ".local" / "share")
) / "steam-grunge-editor"

DATA_DIR       = _USER_DATA_DIR / "data"
CACHE_FOLDER   = DATA_DIR / "cache"
PRESETS_FOLDER = DATA_DIR / "presets"
EXPORT_FOLDER  = _USER_DATA_DIR / "exports"
EXPORT_COVER   = EXPORT_FOLDER / "cover"
EXPORT_WIDE    = EXPORT_FOLDER / "wide"
EXPORT_HERO    = EXPORT_FOLDER / "hero"
EXPORT_LOGO    = EXPORT_FOLDER / "logo"
EXPORT_ICON    = EXPORT_FOLDER / "icon"

# Read-only asset dirs (installed alongside the app)
PLATFORM_BARS_DIR = ASSETS_DIR / "platformBars"
TEXTURES_DIR      = ASSETS_DIR / "textures"
FONTS_DIR         = ASSETS_DIR / "fonts"
TEMPLATES_DIR     = ASSETS_DIR / "templates"
RATINGS_DIR       = ASSETS_DIR / "ratings"

# User-imported fonts / textures go here (the assets dir is read-only on
# installed builds and is a temp dir under PyInstaller). Readers look in
# the user dir first, then the bundled assets.
USER_FONTS_DIR    = _USER_DATA_DIR / "fonts"
USER_TEXTURES_DIR = _USER_DATA_DIR / "textures"


def font_dirs() -> list:
    return [str(USER_FONTS_DIR), str(FONTS_DIR)]


def texture_dirs() -> list:
    return [str(USER_TEXTURES_DIR), str(TEXTURES_DIR)]


def font_path(rel_name: str) -> str:
    """Absolute path of a font given the name/relative path stored on a layer."""
    for d in font_dirs():
        p = os.path.join(d, rel_name)
        if os.path.isfile(p):
            return p
    return os.path.join(str(FONTS_DIR), rel_name)   # (missing) — caller falls back

# SteamGridDB
STEAMGRIDDB_API_BASE = "https://www.steamgriddb.com/api/v2"

# PimpMySteam backend
API_URL = "https://api.pimpmysteam.com"

# ── Ensure user-writable dirs exist ───────────────────────────────────────
for _d in [CACHE_FOLDER, PRESETS_FOLDER, USER_FONTS_DIR, USER_TEXTURES_DIR,
           EXPORT_COVER, EXPORT_WIDE, EXPORT_HERO, EXPORT_LOGO, EXPORT_ICON]:
    _d.mkdir(parents=True, exist_ok=True)