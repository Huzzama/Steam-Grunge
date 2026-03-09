import os

# ── Canvas sizes ──────────────────────────────────────────────────────────────
COVER_SIZE      = (600, 900)
WIDE_SIZE       = (920, 430)
VHS_COVER_SIZE  = (600, 900)   # same canvas, different template overlay
HERO_SIZE       = (3840, 1240) # Steam background / hero art
LOGO_SIZE       = (1280, 720)  # Steam logo (exported as transparent PNG)
ICON_SIZE       = (512, 512)   # Steam icon (exported as transparent PNG)

# Templates that export with a transparent background (no solid fill)
TRANSPARENT_TEMPLATES = {"logo", "icon"}

# Wide-format template variants (all share WIDE_SIZE = 920x430)
WIDE_TEMPLATE_VARIANTS = ["wide", "vhs_pile", "vhs_cassette"]

# Layout zones (used by compositor)
COVER_SPINE_WIDTH          = 40
COVER_PLATFORM_BAR_HEIGHT  = 70

# ── Paths ─────────────────────────────────────────────────────────────────────
# BASE_DIR = wherever the app is installed (may be read-only, e.g. /usr/lib/...)
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(BASE_DIR, "app", "assets")

# User-writable data lives in ~/.local/share/steam-grunge-editor
# This works correctly whether running from source, .deb, AppImage, or .dmg
_USER_DATA_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share")),
    "steam-grunge-editor"
)

DATA_DIR       = os.path.join(_USER_DATA_DIR, "data")
CACHE_FOLDER   = os.path.join(DATA_DIR, "cache")
PRESETS_FOLDER = os.path.join(DATA_DIR, "presets")
EXPORT_FOLDER  = os.path.join(_USER_DATA_DIR, "exports")
EXPORT_COVER   = os.path.join(EXPORT_FOLDER, "cover")
EXPORT_WIDE    = os.path.join(EXPORT_FOLDER, "wide")
EXPORT_HERO    = os.path.join(EXPORT_FOLDER, "hero")
EXPORT_LOGO    = os.path.join(EXPORT_FOLDER, "logo")
EXPORT_ICON    = os.path.join(EXPORT_FOLDER, "icon")

# Read-only asset dirs (installed alongside the app)
PLATFORM_BARS_DIR = os.path.join(ASSETS_DIR, "platformBars")
TEXTURES_DIR      = os.path.join(ASSETS_DIR, "textures")
FONTS_DIR         = os.path.join(ASSETS_DIR, "fonts")
TEMPLATES_DIR     = os.path.join(ASSETS_DIR, "templates")
RATINGS_DIR       = os.path.join(ASSETS_DIR, "ratings")

# SteamGridDB
STEAMGRIDDB_API_BASE = "https://www.steamgriddb.com/api/v2"

# ── Ensure user-writable dirs exist (never touches read-only install paths) ───
for _d in [CACHE_FOLDER, PRESETS_FOLDER,
           EXPORT_COVER, EXPORT_WIDE, EXPORT_HERO, EXPORT_LOGO, EXPORT_ICON]:
    os.makedirs(_d, exist_ok=True)