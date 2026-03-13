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
     - Many games store files inside hashed subfolders, e.g.:
         <appid>/<random_hash>/library_600x900.jpg
         <appid>/logo.png
     - The hash folder names are NOT stable and must not be hardcoded.
     - Steam reads from these subfolders and IGNORES grid/ until
       librarycache is cleared or overwritten.

  This means copying to grid/ alone is not enough — the librarycache
  entry wins on display. We must write to both locations.

ARCHITECTURE:
  A. LibraryCacheTargets     — structured container of discovered paths
  B. _classify_basename()    — maps filename → asset type, ignores folder names
  C. find_librarycache_targets() — recursive discovery, safe, non-crashing
  D. SyncOperation           — a single planned source → destination write
     _build_sync_plan()      — builds all grid + librarycache operations
  E. SyncWriteResult         — result of one write attempt
     _execute_write()        — safe per-file writer, handles format conversion
  F. Format conversion       — PNG→PNG (RGBA), PNG→JPEG (RGB), centralized
  G. SyncSummary / SyncResult — honest structured outcome for callers/UI

INVALIDATION STRATEGY:
  1. Copy to grid/                          (permanent custom override)
  2. Write to all discovered librarycache targets recursively
  3. Touch both folders                     (wakes filesystem watchers)
  4. Write steam://reload/<appid> to steam.pipe (non-blocking IPC)

HERO BLUR POLICY:
  library_hero_blur.jpg is discovered and logged but NEVER written to.
  We do not generate blur images and do not expose this as a sync target.

VHS_COVER:
  vhs_cover is a portrait cover variant. It correctly uses {appid}.png in
  grid/ and maps to cover-type targets (library_600x900.jpg, library_capsule.jpg)
  in librarycache. It is NOT a wide/header asset.
"""

import os
import shutil
import platform
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, List
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


# ── Grid filename mapping ──────────────────────────────────────────────────────

def _grid_filename(app_id: int, template: str) -> str:
    """
    Filename for userdata/.../config/grid/
    These are the custom artwork override files Steam reads.

    vhs_cover is a portrait cover variant and correctly maps to {appid}.png,
    the same slot as cover. It is NOT a wide/header asset.
    """
    mapping = {
        "cover":        f"{app_id}.png",
        "vhs_cover":    f"{app_id}.png",    # portrait cover variant — same slot as cover
        "wide":         f"{app_id}p.png",
        "vhs_pile":     f"{app_id}p.png",
        "vhs_cassette": f"{app_id}p.png",
        "hero":         f"{app_id}_hero.png",
        "logo":         f"{app_id}_logo.png",
        "icon":         f"{app_id}_icon.png",
    }
    return mapping.get(template, f"{app_id}_{template}.png")


# ── A. Structured target container ────────────────────────────────────────────

@dataclass
class LibraryCacheTargets:
    """
    Discovered file paths inside appcache/librarycache/<appid>/, classified
    by asset type using basename matching only (folder names are ignored so
    hashed subfolder layouts like <appid>/<hash>/library_600x900.jpg work).

    hero_blur: collected for logging/reporting only — never written to.
    unknown:   files that didn't match any known pattern — never touched.
    """
    cover:     List[Path] = field(default_factory=list)
    header:    List[Path] = field(default_factory=list)
    hero:      List[Path] = field(default_factory=list)
    hero_blur: List[Path] = field(default_factory=list)   # observed, never synced
    logo:      List[Path] = field(default_factory=list)
    icon:      List[Path] = field(default_factory=list)
    unknown:   List[Path] = field(default_factory=list)

    def targets_for_template(self, template: str) -> List[Path]:
        """
        Return discovered librarycache destination paths for a given export
        template name.

        vhs_cover is a portrait cover variant — it maps to cover targets
        (library_600x900.jpg, library_capsule.jpg), NOT header targets.
        wide / vhs_pile / vhs_cassette are wide assets and map to header targets.
        """
        _map = {
            "cover":        self.cover,
            "vhs_cover":    self.cover,     # portrait cover variant — same targets as cover
            "wide":         self.header,
            "vhs_pile":     self.header,
            "vhs_cassette": self.header,
            "hero":         self.hero,
            "logo":         self.logo,
            "icon":         self.icon,
        }
        return _map.get(template, [])

    def total_syncable(self) -> int:
        """Count of all targets that can actually be written to."""
        return (len(self.cover) + len(self.header) + len(self.hero)
                + len(self.logo) + len(self.icon))


# ── B. Basename classification ────────────────────────────────────────────────

# Files to silently skip — not errors, just irrelevant noise
_IGNORE_BASENAMES = {"markers.svg"}


def _classify_basename(name: str) -> Optional[str]:
    """
    Classify a file into an asset-type string using only its basename.

    Parent folder names are deliberately ignored so that hashed subfolders
    (e.g. <appid>/a3f8c2d1e.../library_600x900.jpg) are handled identically
    to flat layouts (e.g. <appid>/library_600x900.jpg).

    Returns one of:
      "cover", "header", "hero", "hero_blur", "logo", "icon", "ignore", None
    None means the file is unrecognized and will be collected in 'unknown'.
    """
    lower = name.lower()

    if lower in _IGNORE_BASENAMES:
        return "ignore"

    # Cover / capsule
    if lower in ("library_600x900.jpg", "library_600x900.jpeg",
                 "library_capsule.jpg", "library_capsule.jpeg"):
        return "cover"

    # Header / wide
    if lower in ("header.jpg", "header.jpeg",
                 "library_header.jpg", "library_header.jpeg"):
        return "header"

    # Hero blur — must be checked before hero (substring match would collide)
    if lower in ("library_hero_blur.jpg", "library_hero_blur.jpeg",
                 "library_hero_blur.png"):
        return "hero_blur"

    # Hero
    if lower in ("library_hero.jpg", "library_hero.jpeg", "library_hero.png"):
        return "hero"

    # Logo
    if lower in ("logo.png", "logo.jpg", "logo.jpeg"):
        return "logo"

    # Icon
    if lower in ("icon.jpg", "icon.jpeg", "icon.png"):
        return "icon"

    return None  # unrecognized


# ── C. Recursive discovery ────────────────────────────────────────────────────

def find_librarycache_targets(appid_dir: Path) -> LibraryCacheTargets:
    """
    Recursively scan appcache/librarycache/<appid>/ and classify every file
    by its basename. Returns a LibraryCacheTargets with all discovered paths.

    Works with both:
      - flat layouts:   <appid>/library_600x900.jpg
      - hashed layouts: <appid>/<hash>/library_600x900.jpg

    Safe to call when appid_dir does not exist — returns empty targets.
    Never raises for normal missing-path or permission conditions.
    """
    targets = LibraryCacheTargets()

    if not appid_dir or not appid_dir.is_dir():
        return targets

    try:
        for path in appid_dir.rglob("*"):
            if not path.is_file():
                continue
            category = _classify_basename(path.name)
            if category == "ignore":
                continue
            if category is None:
                targets.unknown.append(path)
            else:
                getattr(targets, category).append(path)
    except Exception as e:
        print(f"[steamSync] discovery error scanning {appid_dir}: {e}")

    return targets


def _librarycache_dir(steam_root: Path, app_id: int) -> Optional[Path]:
    """
    Return the per-appid librarycache subfolder if it exists.
    We never create this directory ourselves — Steam owns it.
    """
    d = steam_root / "appcache" / "librarycache" / str(app_id)
    return d if d.is_dir() else None


# ── D. Sync plan ──────────────────────────────────────────────────────────────

@dataclass
class SyncOperation:
    """Represents a single planned file write: source PNG → destination."""
    asset_type:  str
    source:      Path
    destination: Path


def _build_sync_plan(
    app_id:     int,
    exports:    Dict[str, str],        # template → absolute PNG source path
    grid_dir:   Path,
    lc_targets: LibraryCacheTargets,
) -> List[SyncOperation]:
    """
    Build the complete list of SyncOperations for one sync run.

    For each valid export:
      - one grid write  (always present when source exists)
      - N librarycache writes  (one per discovered matching target)

    hero_blur targets are never added to the plan (per product policy).
    """
    ops: List[SyncOperation] = []

    for template, src_path in exports.items():
        if not src_path or not Path(src_path).is_file():
            continue
        src = Path(src_path)

        # Grid destination — always one per template
        ops.append(SyncOperation(
            asset_type  = template,
            source      = src,
            destination = grid_dir / _grid_filename(app_id, template),
        ))

        # librarycache destinations — zero or more discovered targets
        for lc_dest in lc_targets.targets_for_template(template):
            ops.append(SyncOperation(
                asset_type  = template,
                source      = src,
                destination = lc_dest,
            ))

    return ops


# ── E & F. Safe writer with format conversion ─────────────────────────────────

@dataclass
class SyncWriteResult:
    """Result of a single file write attempt."""
    destination: Path
    asset_type:  str
    success:     bool
    error:       Optional[str] = None


def _execute_write(op: SyncOperation) -> SyncWriteResult:
    """
    Execute one SyncOperation. Never raises — always returns SyncWriteResult.

    Format conversion (F):
      - Destination .png        → open source, convert to RGBA, save as PNG
      - Destination .jpg/.jpeg  → open source, convert to RGB, save as JPEG q=92

    Source is always a PNG exported by the editor. Destination extension
    determines the output format, not the source extension.
    """
    try:
        suffix = op.destination.suffix.lower()
        img    = Image.open(op.source)

        if suffix == ".png":
            img.convert("RGBA").save(op.destination, "PNG", optimize=True)
        else:
            img.convert("RGB").save(op.destination, "JPEG", quality=92, optimize=True)

        os.utime(op.destination, (time.time(), time.time()))
        print(f"[steamSync] wrote {op.asset_type} -> {op.destination}")
        return SyncWriteResult(
            destination = op.destination,
            asset_type  = op.asset_type,
            success     = True,
        )

    except Exception as e:
        print(f"[steamSync] failed {op.asset_type} -> {op.destination} : {e}")
        return SyncWriteResult(
            destination = op.destination,
            asset_type  = op.asset_type,
            success     = False,
            error       = str(e),
        )


# ── Cache bust helpers ─────────────────────────────────────────────────────────

def _touch(path: Path):
    try:
        os.utime(path, (time.time(), time.time()))
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
            subprocess.Popen(
                ["cmd", "/c", "start", f"steam://reload/{app_id}"],
                shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"[steamSync] Windows reload failed: {e}")
    elif system == "Darwin":
        try:
            subprocess.Popen(
                ["open", f"steam://reload/{app_id}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"[steamSync] macOS reload failed: {e}")


# ── G. Result dataclasses ──────────────────────────────────────────────────────

@dataclass
class SyncSummary:
    """
    Detailed, honest accounting of a sync run. Attached to SyncResult.summary.

    outcome property returns one of:
      "success"   — all planned writes completed successfully
      "partial"   — some writes succeeded, some failed or were skipped
      "grid_only" — grid written, but no librarycache targets existed
      "failure"   — nothing written anywhere
    """
    app_id:                       int
    grid_targets_found:           int
    grid_targets_written:         int
    librarycache_targets_found:   int
    librarycache_targets_written: int
    skipped_targets:              List[str] = field(default_factory=list)
    warnings:                     List[str] = field(default_factory=list)
    errors:                       List[str] = field(default_factory=list)

    @property
    def outcome(self) -> str:
        grid_ok  = self.grid_targets_written > 0
        lc_ok    = self.librarycache_targets_written > 0
        lc_exist = self.librarycache_targets_found > 0

        if not grid_ok and self.errors:
            return "failure"
        if grid_ok and not lc_exist:
            return "grid_only"
        total_planned = self.grid_targets_found + self.librarycache_targets_found
        total_written = self.grid_targets_written + self.librarycache_targets_written
        if grid_ok and lc_ok and total_written >= total_planned:
            return "success"
        if grid_ok or lc_ok:
            return "partial"
        return "failure"


@dataclass
class SyncResult:
    """
    Legacy-compatible result returned by sync_artwork().

    Existing callers (bulkSync, exportFlow, UI) are unchanged.
    result.summary carries the richer SyncSummary for UIs that want detail.

    success = True when at least one grid target was written successfully.
    """
    success:     bool
    grid_folder: str                   = ""
    installed:   list                  = field(default_factory=list)
    skipped:     list                  = field(default_factory=list)
    errors:      list                  = field(default_factory=list)
    summary:     Optional[SyncSummary] = field(default=None, repr=False)


# ── Main sync ──────────────────────────────────────────────────────────────────

def sync_artwork(
    app_id:        int,
    steam_id:      str,
    userdata_path: Path,
    exports:       Dict[str, str],
    overwrite:     bool = True,
) -> SyncResult:
    """
    Copy artwork to Steam's grid folder AND all discovered librarycache
    targets so the library UI shows the new images without a restart.

    Public API is identical to the previous version — no callers need changes.
    A richer SyncSummary is available at result.summary.
    """
    grid_dir   = get_grid_folder(userdata_path, steam_id)
    steam_root = userdata_path.parent
    result     = SyncResult(success=False, grid_folder=str(grid_dir))

    print(f"[steamSync] app_id={app_id}")

    # ── C. Discover librarycache targets recursively ───────────────────────
    appid_dir  = _librarycache_dir(steam_root, app_id)
    lc_targets = find_librarycache_targets(appid_dir) if appid_dir else LibraryCacheTargets()

    print(f"[steamSync] discovered cover targets:    {len(lc_targets.cover)}")
    print(f"[steamSync] discovered header targets:   {len(lc_targets.header)}")
    print(f"[steamSync] discovered hero targets:     {len(lc_targets.hero)}")
    print(f"[steamSync] ignored hero_blur targets:   {len(lc_targets.hero_blur)}")
    print(f"[steamSync] discovered logo targets:     {len(lc_targets.logo)}")
    print(f"[steamSync] discovered icon targets:     {len(lc_targets.icon)}")
    print(f"[steamSync] unknown files:               {len(lc_targets.unknown)}")

    # ── Filter to valid sources, record missing as skipped ────────────────
    valid_exports: Dict[str, str] = {}
    for template, src_path in exports.items():
        if src_path and os.path.isfile(src_path):
            valid_exports[template] = src_path
        else:
            result.skipped.append(template)

    # ── D. Build sync plan ────────────────────────────────────────────────
    all_ops  = _build_sync_plan(app_id, valid_exports, grid_dir, lc_targets)
    grid_ops = [op for op in all_ops if op.destination.parent == grid_dir]
    lc_ops   = [op for op in all_ops if op.destination.parent != grid_dir]

    # Overwrite guard applies to grid only (librarycache always overwritten)
    if not overwrite:
        approved_grid = []
        for op in grid_ops:
            if op.destination.exists():
                result.skipped.append(op.asset_type)
            else:
                approved_grid.append(op)
        grid_ops = approved_grid

    # ── E. Execute all writes safely ──────────────────────────────────────
    grid_results: List[SyncWriteResult] = [_execute_write(op) for op in grid_ops]
    lc_results:   List[SyncWriteResult] = [_execute_write(op) for op in lc_ops]

    for wr in grid_results:
        if wr.success:
            result.installed.append(str(wr.destination))
        else:
            result.errors.append(f"{wr.asset_type} grid: {wr.error}")

    for wr in lc_results:
        if not wr.success:
            # Non-fatal — grid write may already have succeeded
            result.errors.append(f"{wr.asset_type} lcache: {wr.error}")

    # Nothing installed and nothing errored → everything was skipped
    if not result.installed and not result.errors:
        result.skipped = list(exports.keys())

    # ── Touch folders + signal Steam to reload ────────────────────────────
    if result.installed:
        _touch(grid_dir)
        if appid_dir:
            _touch(appid_dir)
        _signal_reload(app_id)

    # ── G. Build SyncSummary ──────────────────────────────────────────────
    grid_written = sum(1 for wr in grid_results if wr.success)
    lc_written   = sum(1 for wr in lc_results   if wr.success)
    # Use the number of *planned* lc operations, not all discovered targets.
    # This prevents misleading "partial" outcomes when other asset types exist
    # in librarycache that simply weren't part of this sync run.
    lc_found     = len(lc_ops)

    warnings = []
    if lc_targets.hero_blur:
        warnings.append(
            f"Ignored {len(lc_targets.hero_blur)} hero_blur target(s) "
            f"(not a supported sync type)."
        )
    if lc_targets.unknown:
        warnings.append(
            f"{len(lc_targets.unknown)} unrecognized file(s) in librarycache "
            f"left untouched."
        )

    summary = SyncSummary(
        app_id                       = app_id,
        grid_targets_found           = len(grid_ops),
        grid_targets_written         = grid_written,
        librarycache_targets_found   = lc_found,
        librarycache_targets_written = lc_written,
        skipped_targets              = list(result.skipped),
        warnings                     = warnings,
        errors                       = list(result.errors),
    )

    # result.success preserves backward compatibility for existing callers
    # (bulkSync, exportFlow) that only check the boolean.
    # For honest reporting — especially distinguishing partial from full sync —
    # callers and UI should use result.summary.outcome, summary.warnings, and
    # summary.errors instead of relying on result.success alone.
    #
    # Mapping: outcome "failure" → success=False; everything else → success=True
    # so that grid-only and partial syncs still unblock callers that only need
    # to know "did anything land in Steam at all?".
    result.success = summary.outcome != "failure"
    result.summary = summary

    print(
        f"[steamSync] outcome: {summary.outcome} "
        f"(grid {grid_written}/{len(grid_ops)}, "
        f"lcache {lc_written}/{lc_found})"
    )

    return result