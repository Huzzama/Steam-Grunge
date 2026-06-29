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

# Layout zones (used by compositor)
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

# SteamGridDB
STEAMGRIDDB_API_BASE = "https://www.steamgriddb.com/api/v2"

# PimpMySteam backend
API_URL = "https://api.pimpmysteam.com"

# ── Ensure user-writable dirs exist ───────────────────────────────────────
for _d in [CACHE_FOLDER, PRESETS_FOLDER,
           EXPORT_COVER, EXPORT_WIDE, EXPORT_HERO, EXPORT_LOGO, EXPORT_ICON]:
    _d.mkdir(parents=True, exist_ok=True)