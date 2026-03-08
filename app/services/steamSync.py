"""
app/services/steamSync.py
Locates the Steam custom artwork folder and installs exported artwork
using the correct Steam filename convention for each template type.

Filename convention (AppID = e.g. 730):
  cover      →  {appid}.png
  wide       →  {appid}p.png
  vhs_cover  →  {appid}p.png   (same slot as wide)
  hero       →  {appid}_hero.png
  logo       →  {appid}_logo.png
  icon       →  {appid}_icon.png
"""
from __future__ import annotations

import os
import sys
import shutil
import glob
from dataclasses import dataclass, field
from typing import Optional, List


# ── filename suffix map ────────────────────────────────────────────────────────
_SUFFIX: dict[str, str] = {
    "cover":     "{appid}.png",
    "vhs_cover": "{appid}p.png",
    "wide":      "{appid}p.png",
    "hero":      "{appid}_hero.png",
    "logo":      "{appid}_logo.png",
    "icon":      "{appid}_icon.png",
}


# ── Steam install path candidates ─────────────────────────────────────────────
def _steam_roots() -> List[str]:
    """Return candidate Steam root directories for the current OS."""
    candidates: List[str] = []
    home = os.path.expanduser("~")

    if sys.platform == "win32":
        candidates += [
            r"C:\Program Files (x86)\Steam",
            r"C:\Program Files\Steam",
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Steam"),
            os.path.join(os.environ.get("ProgramFiles", ""),       "Steam"),
        ]
    elif sys.platform == "darwin":
        candidates += [
            os.path.join(home, "Library", "Application Support", "Steam"),
        ]
    else:  # Linux / BSD
        candidates += [
            os.path.join(home, ".local", "share", "Steam"),
            os.path.join(home, ".steam", "steam"),
            os.path.join(home, ".steam", "Steam"),
            # Flatpak
            os.path.join(home, ".var", "app",
                         "com.valvesoftware.Steam", "data", "Steam"),
        ]

    return [c for c in candidates if c]  # remove blanks


def find_steam_userdata() -> Optional[str]:
    """Return the first existing Steam userdata/ directory, or None."""
    for root in _steam_roots():
        ud = os.path.join(root, "userdata")
        if os.path.isdir(ud):
            return ud
    return None


def list_steam_ids(userdata_path: str) -> List[str]:
    """Return all numeric SteamID sub-folders inside userdata/."""
    if not userdata_path or not os.path.isdir(userdata_path):
        return []
    return [
        d for d in os.listdir(userdata_path)
        if d.isdigit() and os.path.isdir(os.path.join(userdata_path, d))
    ]


def get_grid_folder(userdata_path: str, steam_id: str) -> str:
    """Return (and create if needed) the grid folder for a SteamID."""
    path = os.path.join(userdata_path, steam_id, "config", "grid")
    os.makedirs(path, exist_ok=True)
    return path


# ── result dataclass ──────────────────────────────────────────────────────────
@dataclass
class SyncResult:
    installed:  List[str] = field(default_factory=list)   # destination paths
    skipped:    List[str] = field(default_factory=list)    # templates with no export
    errors:     List[str] = field(default_factory=list)    # error messages
    grid_folder: str = ""

    @property
    def success(self) -> bool:
        return len(self.errors) == 0 and len(self.installed) > 0

    def summary(self) -> str:
        parts = []
        if self.installed:
            parts.append(f"Installed {len(self.installed)} file(s) → {self.grid_folder}")
        if self.skipped:
            parts.append(f"Skipped (no export): {', '.join(self.skipped)}")
        if self.errors:
            parts.append("Errors:\n" + "\n".join(self.errors))
        return "\n".join(parts) if parts else "Nothing to sync."


# ── main sync function ────────────────────────────────────────────────────────
def sync_artwork(
    app_id: int,
    steam_id: str,
    userdata_path: str,
    exports: dict[str, str],   # { template_name: source_file_path }
    overwrite: bool = True,
) -> SyncResult:
    """
    Copy artwork files into the Steam grid folder.

    Parameters
    ----------
    app_id        : Steam AppID (e.g. 730)
    steam_id      : SteamID folder name (e.g. "12345678")
    userdata_path : path to Steam/userdata/
    exports       : mapping of template → exported PNG path
                    e.g. {"cover": "/exports/cover/game_cover_…png"}
    overwrite     : replace existing files if True

    Returns a SyncResult with details.
    """
    result = SyncResult()
    result.grid_folder = get_grid_folder(userdata_path, steam_id)

    for template, src_path in exports.items():
        suffix_tpl = _SUFFIX.get(template)
        if not suffix_tpl:
            result.skipped.append(template)
            continue

        if not src_path or not os.path.isfile(src_path):
            result.skipped.append(template)
            continue

        dest_name = suffix_tpl.format(appid=app_id)
        dest_path = os.path.join(result.grid_folder, dest_name)

        if os.path.exists(dest_path) and not overwrite:
            result.skipped.append(template)
            continue

        try:
            shutil.copy2(src_path, dest_path)
            result.installed.append(dest_path)
        except Exception as e:
            result.errors.append(f"{template}: {e}")

    return result


# ── convenience: export-and-sync in one call ──────────────────────────────────
def export_and_sync(
    canvas,           # PreviewCanvas
    template: str,
    game_name: str,
    app_id: int,
    steam_id: str,
    userdata_path: str,
) -> SyncResult:
    """
    Compose the current canvas, save to exports folder, then copy to Steam grid.
    Returns a SyncResult.
    """
    from app.editor import exports as exporter

    result = SyncResult()
    result.grid_folder = get_grid_folder(userdata_path, steam_id)

    final = canvas.compose_to_pil()
    if final is None:
        result.errors.append("Canvas returned no image.")
        return result

    try:
        src_path = exporter.export_image(final, template, game_name)
    except Exception as e:
        result.errors.append(f"Export failed: {e}")
        return result

    return sync_artwork(
        app_id=app_id,
        steam_id=steam_id,
        userdata_path=userdata_path,
        exports={template: src_path},
    )