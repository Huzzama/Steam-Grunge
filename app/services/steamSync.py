"""
app/services/steamSync.py

Copies exported artwork into Steam's grid folder AND Steam's librarycache,
so the new artwork actually appears in the library without a restart.

WHY TWO LOCATIONS:
  Steam maintains two separate artwork systems:

  1. userdata/<steamid>/config/grid/
     - Custom artwork overrides set by the user
     - Files: {appid}.png, {appid}p.png, {appid}_hero.png, etc.

  2. appcache/librarycache/
     - Steam's own download cache for official artwork
     - Files: {appid}_library_600x900.jpeg, {appid}_header.jpeg, etc.
     - Steam's CEF-based library UI (introduced ~2022) renders from here
       and IGNORES the grid/ folder until librarycache is cleared or
       overwritten.

  This means copying to grid/ alone is not enough — the librarycache
  entry wins on display. We must write to both locations.

INVALIDATION STRATEGY:
  1. Copy PNG to grid/                    (the permanent custom override)
  2. Convert + write JPEG to librarycache (forces immediate UI refresh)
  3. Touch both folders                   (wakes filesystem watchers)
  4. Write steam://reload/<appid> to steam.pipe (non-blocking IPC)
"""

import os
import glob
import shutil
import platform
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict
import subprocess

from PIL import Image


# ── Steam root detection ───────────────────────────────────────────────────────

def _steam_roots() -> list:
    system = platform.system()
    candidates = []
    if system == "Linux":
        home = Path.home()
        candidates = [
            home / ".local" / "share" / "Steam",
            home / ".steam" / "steam",
            home / ".steam" / "root",
        ]
        override = _read_path_override()
        if override:
            candidates.insert(0, Path(override))
    elif system == "Darwin":
        candidates = [Path.home() / "Library" / "Application Support" / "Steam"]
    elif system == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
            path, _ = winreg.QueryValueEx(key, "SteamPath")
            candidates.append(Path(path))
        except Exception:
            pass
        candidates += [
            Path(r"C:\Program Files (x86)\Steam"),
            Path(r"C:\Program Files\Steam"),
        ]
    # Resolve symlinks so we always work with the real path
    resolved = []
    for p in candidates:
        try:
            resolved.append(p.resolve())
        except Exception:
            pass
    # Deduplicate while preserving order
    seen = set()
    result = []
    for p in resolved:
        if p not in seen and p.exists():
            seen.add(p)
            result.append(p)
    return result


def _read_path_override() -> Optional[str]:
    try:
        import json
        from app.config import DATA_DIR
        fp = os.path.join(DATA_DIR, "steam_path_override.json")
        if os.path.exists(fp):
            with open(fp) as f:
                return json.load(f).get("steam_path")
    except Exception:
        pass
    return None


# ── Public helpers ─────────────────────────────────────────────────────────────

def find_steam_userdata() -> Optional[Path]:
    """Return the userdata/ directory inside the Steam root."""
    for root in _steam_roots():
        ud = root / "userdata"
        if ud.exists():
            print(f"[steamSync] Steam root: {root}")
            return ud
    return None


def list_steam_ids(userdata_path: Path) -> list:
    """Return SteamID folder names found under userdata/."""
    if not userdata_path or not userdata_path.exists():
        return []
    ids = []
    for entry in sorted(userdata_path.iterdir()):
        if entry.is_dir() and entry.name.isdigit():
            if (entry / "config").exists():
                ids.append(entry.name)
    return ids


def get_grid_folder(userdata_path: Path, steam_id: str) -> Path:
    """Return (and create if needed) the grid folder for a given SteamID."""
    grid = userdata_path / steam_id / "config" / "grid"
    grid.mkdir(parents=True, exist_ok=True)
    return grid


# ── Filename mappings ──────────────────────────────────────────────────────────

def _grid_filename(app_id: int, template: str) -> str:
    """
    Filename for userdata/.../config/grid/
    These are the custom artwork override files Steam reads.
    """
    mapping = {
        "cover":        f"{app_id}.png",
        "vhs_cover":    f"{app_id}.png",
        "wide":         f"{app_id}p.png",
        "vhs_pile":     f"{app_id}p.png",
        "vhs_cassette": f"{app_id}p.png",
        "hero":         f"{app_id}_hero.png",
        "logo":         f"{app_id}_logo.png",
        "icon":         f"{app_id}_icon.png",
    }
    return mapping.get(template, f"{app_id}_{template}.png")


def _librarycache_filename(app_id: int, template: str) -> Optional[str]:
    """
    Filename inside appcache/librarycache/<appid>/ (Steam's new folder structure).
    Steam reads from this subfolder, NOT the old flat {appid}_library_600x900.jpeg files.
    Observed filenames from real Steam installs:
      library_600x900.jpg, header.jpg, library_hero.jpg, logo.png
    Returning None means skip librarycache for this template.
    """
    mapping = {
        "cover":        "library_600x900.jpg",
        "vhs_cover":    "library_600x900.jpg",
        "wide":         "header.jpg",
        "vhs_pile":     "header.jpg",
        "vhs_cassette": "header.jpg",
        "hero":         "library_hero.jpg",
        "logo":         "logo.png",
        "icon":         "icon.jpg",
    }
    return mapping.get(template)


def _librarycache_dir(steam_root: Path, app_id: int) -> Optional[Path]:
    """
    Return the per-appid librarycache subfolder if it exists.
    Steam only creates this folder for games it knows about, so we
    never create it ourselves — only write into it if it's already there.
    """
    d = steam_root / "appcache" / "librarycache" / str(app_id)
    return d if d.is_dir() else None


def _write_librarycache(src_png: str, dest: Path, template: str):
    """
    Convert src_png and write it to the librarycache destination.
    Logo stays PNG; everything else is written as JPEG quality=92.
    """
    img = Image.open(src_png).convert("RGB")
    if dest.suffix.lower() == ".png":
        img.save(dest, "PNG", optimize=True)
    else:
        img.save(dest, "JPEG", quality=92, optimize=True)
    now = time.time()
    os.utime(dest, (now, now))


# ── Cache bust helpers ─────────────────────────────────────────────────────────

def _touch(path: Path):
    try:
        now = time.time()
        os.utime(path, (now, now))
    except OSError:
        pass


# ── Steam IPC ──────────────────────────────────────────────────────────────────

def _send_steam_pipe(url: str) -> bool:
    """
    Write a steam:// URL to Steam's named pipe using O_NONBLOCK so we
    never block the main thread. Runs in a daemon thread with timeout.
    """
    pipe = Path.home() / ".steam" / "steam.pipe"
    if not pipe.exists():
        return False

    result = {"ok": False}

    def _write():
        try:
            fd = os.open(str(pipe), os.O_WRONLY | os.O_NONBLOCK)
            os.write(fd, (url.rstrip("\n") + "\n").encode())
            os.close(fd)
            result["ok"] = True
            print(f"[steamSync] steam.pipe ← {url}")
        except BlockingIOError:
            print("[steamSync] steam.pipe not ready — skipping signal")
        except Exception as e:
            print(f"[steamSync] steam.pipe error: {e}")

    t = threading.Thread(target=_write, daemon=True)
    t.start()
    t.join(timeout=2.0)
    return result["ok"]


def _signal_reload(app_id: int):
    system = platform.system()
    if system == "Linux":
        _send_steam_pipe(f"steam://reload/{app_id}")
    elif system == "Windows":
        try:
            subprocess.Popen(["cmd", "/c", "start", f"steam://reload/{app_id}"],
                             shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"[steamSync] Windows reload failed: {e}")
    elif system == "Darwin":
        try:
            subprocess.Popen(["open", f"steam://reload/{app_id}"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"[steamSync] macOS reload failed: {e}")


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class SyncResult:
    success:     bool
    grid_folder: str  = ""
    installed:   list = field(default_factory=list)
    skipped:     list = field(default_factory=list)
    errors:      list = field(default_factory=list)


# ── Main sync ──────────────────────────────────────────────────────────────────

def sync_artwork(
    app_id: int,
    steam_id: str,
    userdata_path: Path,
    exports: Dict[str, str],
    overwrite: bool = True,
) -> SyncResult:
    """
    Copy artwork to Steam's grid folder AND librarycache so the library
    UI actually shows the new image without needing a full restart.
    """
    grid_dir  = get_grid_folder(userdata_path, steam_id)
    steam_root = userdata_path.parent
    # lc_dir resolved per-template via _librarycache_dir()
    result    = SyncResult(success=False, grid_folder=str(grid_dir))

    for template, src_path in exports.items():
        if not src_path or not os.path.isfile(src_path):
            result.skipped.append(template)
            continue

        # ── 1. Write to grid/ (permanent custom override) ──────────────────
        grid_name = _grid_filename(app_id, template)
        grid_dest = grid_dir / grid_name

        if grid_dest.exists() and not overwrite:
            result.skipped.append(template)
            continue

        try:
            shutil.copy2(src_path, grid_dest)
            os.utime(grid_dest, (time.time(), time.time()))
            print(f"[steamSync] grid/     {template}: {src_path}")
            print(f"[steamSync]        →  {grid_dest}")
            result.installed.append(str(grid_dest))
        except OSError as e:
            result.errors.append(f"{template} grid: {e}")
            continue

        # ── 2. Write to librarycache/<appid>/ (forces UI refresh) ────────
        lc_name = _librarycache_filename(app_id, template)
        lc_subdir = _librarycache_dir(steam_root, app_id)
        if lc_name and lc_subdir:
            lc_dest = lc_subdir / lc_name
            try:
                _write_librarycache(src_path, lc_dest, template)
                print(f"[steamSync] lcache/   {template}: {lc_dest}")
            except Exception as e:
                # Non-fatal — grid copy already succeeded
                print(f"[steamSync] librarycache warning ({template}): {e}")

    if not result.installed and not result.errors:
        result.skipped = list(exports.keys())

    # ── 3. Touch folders + signal reload ──────────────────────────────────
    if result.installed:
        _touch(grid_dir)
        lc_subdir = _librarycache_dir(steam_root, app_id)
        if lc_subdir:
            _touch(lc_subdir)
        _signal_reload(app_id)

    result.success = len(result.installed) > 0
    return result