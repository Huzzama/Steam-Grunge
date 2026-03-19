import logging
import os
import shutil
import platform
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, List, Literal
import subprocess

from PIL import Image


# ── Logging ────────────────────────────────────────────────────────────────────

import logging.handlers as _log_handlers

# Module-level singleton — None means "not yet initialised", False means "failed"
_FILE_LOGGER: "Optional[logging.Logger]" = None
_FILE_LOGGER_READY: bool = False


def _init_file_logger() -> Optional[logging.Logger]:
    """
    Initialise (once) a rotating file logger writing to:
      ~/.config/steam-grunge-editor/logs/steamSync.log

    Rotation: 1 MB max, 3 backups kept — prevents unbounded disk growth
    on machines that sync frequently.

    Returns the Logger on success, None on any failure.
    Never raises.
    """
    global _FILE_LOGGER, _FILE_LOGGER_READY
    if _FILE_LOGGER_READY:
        return _FILE_LOGGER  # already initialised (may be None if setup failed)

    _FILE_LOGGER_READY = True  # set before any attempt so re-entry is safe
    try:
        log_dir = Path.home() / ".config" / "steam-grunge-editor" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "steamSync.log"

        logger = logging.getLogger("steamSync.file")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False  # never bubble up to root logger

        if not logger.handlers:
            handler = _log_handlers.RotatingFileHandler(
                log_path,
                mode      = "a",
                maxBytes  = 1 * 1024 * 1024,   # 1 MB per file
                backupCount = 3,
                encoding  = "utf-8",
                delay     = False,
            )
            handler.setFormatter(logging.Formatter(
                "%(asctime)s  %(message)s",
                datefmt = "%Y-%m-%d %H:%M:%S",
            ))
            logger.addHandler(handler)

        # Write a session-start marker so log files are easy to navigate
        logger.info("─" * 60)
        logger.info("[steamSync] ── session start ──────────────────────────")

        _FILE_LOGGER = logger
    except Exception:
        _FILE_LOGGER = None  # type: ignore[assignment]

    return _FILE_LOGGER


def _log(msg: str, *, level: int = logging.INFO) -> None:
    """
    Write *msg* to stdout AND to the rotating log file.

    Drop-in replacement for every existing ``print(f"[steamSync] …")`` call.
    The ``level`` kwarg lets callers signal warnings/errors to the file logger
    while keeping the stdout output identical.

    Never raises — logging failures are silently discarded.
    """
    print(msg)
    try:
        logger = _init_file_logger()
        if logger is not None:
            logger.log(level, msg)
    except Exception:
        pass


# ── Steam root detection ───────────────────────────────────────────────────────

def _steam_roots() -> list:
    """
    Return all existing Steam root directories on this machine, in priority order.

    Linux path priority:
      1. User-configured override (steam_path_override.json)
      2. Native install  — ~/.local/share/Steam
      3. Flatpak install — ~/.var/app/com.valvesoftware.Steam/data/Steam
                           (Steam Deck default, also common on desktop Linux)
      4. Legacy symlinks — ~/.steam/steam, ~/.steam/root
    """
    system = platform.system()
    candidates = []
    if system == "Linux":
        home = Path.home()
        override = _read_path_override()
        if override:
            candidates.append(Path(override))
        candidates += [
            # Native / SteamOS (Steam Deck)
            home / ".local" / "share" / "Steam",
            # Flatpak — this IS the primary path on Steam Deck and many desktop distros
            home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam",
            # Legacy symlinks (often point to one of the above)
            home / ".steam" / "steam",
            home / ".steam" / "root",
        ]
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

    # Deduplicate while preserving priority order
    seen: set = set()
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
            _log(f"[steamSync] Steam root: {root}")
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
        _log(f"[steamSync] discovery error scanning {appid_dir}: {e}", level=logging.WARNING)

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
        _log(f"[steamSync] wrote {op.asset_type} -> {op.destination}")
        return SyncWriteResult(
            destination = op.destination,
            asset_type  = op.asset_type,
            success     = True,
        )

    except Exception as e:
        _log(
            f"[steamSync] failed {op.asset_type} -> {op.destination} : {e}",
            level=logging.WARNING,
        )
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

def _steam_pipe_path() -> Optional[Path]:
    """
    Return the steam.pipe path to use for IPC, or None if not found.

    Checks in priority order:
      1. ~/.steam/steam.pipe          — native Linux install
      2. XDG_RUNTIME_DIR/app/com.valvesoftware.Steam/.steam/steam.pipe
                                      — Flatpak sandbox (Steam Deck / desktop)
    """
    # Native
    native = Path.home() / ".steam" / "steam.pipe"
    if native.exists():
        return native

    # Flatpak: pipe lives inside the Flatpak XDG runtime directory
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if xdg_runtime:
        flatpak_pipe = (
            Path(xdg_runtime)
            / "app"
            / "com.valvesoftware.Steam"
            / ".steam"
            / "steam.pipe"
        )
        if flatpak_pipe.exists():
            return flatpak_pipe

    return None


def _send_steam_pipe(url: str) -> bool:
    """
    Write a steam:// URL to Steam's named pipe using O_NONBLOCK so we
    never block the main thread. Runs in a daemon thread with timeout.

    Supports both native and Flatpak Steam pipe locations.
    """
    pipe = _steam_pipe_path()
    if pipe is None:
        return False

    result = {"ok": False}

    def _write():
        try:
            fd = os.open(str(pipe), os.O_WRONLY | os.O_NONBLOCK)
            os.write(fd, (url.rstrip("\n") + "\n").encode())
            os.close(fd)
            result["ok"] = True
            _log(f"[steamSync] steam.pipe ← {url}")
        except BlockingIOError:
            _log("[steamSync] steam.pipe not ready — skipping signal")
        except Exception as e:
            _log(f"[steamSync] steam.pipe error: {e}")

    t = threading.Thread(target=_write, daemon=True)
    t.start()
    t.join(timeout=2.0)
    return result["ok"]


def _signal_reload(app_id: int) -> None:
    """
    Signal Steam to reload artwork for *app_id*.

    Linux strategy (in order):
      1. Write to steam.pipe (native + Flatpak pipe locations)
      2. xdg-open fallback if pipe write failed (works in Flatpak sandboxes
         where the pipe path differs from what _steam_pipe_path returns)
    """
    system = platform.system()
    url    = f"steam://reload/{app_id}"

    if system == "Linux":
        ok = _send_steam_pipe(url)
        if not ok:
            # xdg-open is available in both native and Flatpak environments
            # and correctly routes steam:// URIs to the running Steam instance.
            try:
                subprocess.Popen(
                    ["xdg-open", url],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                _log(f"[steamSync] xdg-open fallback ← {url}")
            except Exception as e:
                _log(f"[steamSync] xdg-open fallback failed: {e}")

    elif system == "Windows":
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", url],
                shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            _log(f"[steamSync] Windows reload failed: {e}")

    elif system == "Darwin":
        try:
            subprocess.Popen(
                ["open", url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            _log(f"[steamSync] macOS reload failed: {e}")


# ── H. Post-sync strategy system ──────────────────────────────────────────────

# Type alias for all supported strategy modes
PostSyncStrategy = Literal["none", "soft", "restart", "auto"]

# Default strategy when silent mode is active and no override is provided
DEFAULT_SILENT_STRATEGY: PostSyncStrategy = "soft"


def is_steam_running() -> bool:
    """
    Return True if a Steam process is currently running.

    Cross-platform:
      Linux / Steam Deck — /proc scan (substring match), then pgrep -f steam
      macOS              — pgrep -x steam_osx / steam
      Windows            — tasklist

    Handles steamwebhelper, steam-runtime, pressure-vessel and similar
    Steam-family processes as positive signals. Never raises.
    """
    system = platform.system()
    try:
        if system == "Linux":
            # Fast path: /proc scan — match any comm containing "steam"
            # Catches: steam, steamwebhelper, steam-runtime, etc.
            proc_dir = Path("/proc")
            if proc_dir.exists():
                for pid_dir in proc_dir.iterdir():
                    if not pid_dir.name.isdigit():
                        continue
                    try:
                        comm = (pid_dir / "comm").read_text().strip().lower()
                        if "steam" in comm:
                            return True
                    except (PermissionError, FileNotFoundError):
                        continue
            # Fallback: pgrep -f matches full cmdline, not just comm
            r = subprocess.run(
                ["pgrep", "-f", "steam"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return r.returncode == 0

        elif system == "Darwin":
            for name in ("steam_osx", "steam"):
                r = subprocess.run(
                    ["pgrep", "-x", name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                if r.returncode == 0:
                    return True
            return False

        elif system == "Windows":
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
                capture_output=True, text=True,
            )
            return "steam.exe" in r.stdout.lower()

    except Exception as e:
        _log(f"[steamSync] is_steam_running check failed: {e}")

    return False


def is_game_running() -> bool:
    """
    Return True if a Steam-launched game appears to be running.

    Linux heuristics (layered, fastest first):
      1. /proc scan — comm heuristics:
           - "steam_app_" prefix: Steam's own process naming for launched games
           - "pressure-vessel": Proton/Steam Runtime container supervisor
           - "reaper":          Steam's child-process supervisor (wraps all games)
      2. /proc/<pid>/environ scan for SteamAppId variable:
           - The definitive signal — Steam injects SteamAppId=<id> into every
             game process's environment. Checks a sample of candidate PIDs
             (those whose parent is a steam process) to avoid reading all envs.
      3. pgrep -f pressure-vessel fallback if /proc scan is unavailable.

    Windows: checks for GameOverlayUI.exe (injected into every running game).
    macOS:   returns False (safe fallback, no false restarts).

    Never raises.
    """
    system = platform.system()
    try:
        if system == "Linux":
            proc_dir = Path("/proc")
            if not proc_dir.exists():
                # No /proc — fall through to pgrep
                pass
            else:
                # Collect candidate PIDs from comm heuristics
                game_comms     = set()
                candidate_pids = []

                for pid_dir in proc_dir.iterdir():
                    if not pid_dir.name.isdigit():
                        continue
                    try:
                        comm = (pid_dir / "comm").read_text().strip().lower()
                    except (PermissionError, FileNotFoundError):
                        continue

                    # Fast comm-level signals
                    if (
                        comm.startswith("steam_app_")
                        or comm == "pressure-vessel"
                        or comm == "reaper"
                    ):
                        return True

                    # Collect for environ check below
                    if "steam" in comm:
                        candidate_pids.append(pid_dir.name)

                # Environ check: look for SteamAppId in candidate process envs
                # Env vars are NUL-separated in /proc/<pid>/environ
                for pid in candidate_pids[:20]:   # cap to avoid O(n) over all procs
                    try:
                        env_bytes = (proc_dir / pid / "environ").read_bytes()
                        env_vars  = env_bytes.split(b"\x00")
                        if any(v.startswith(b"SteamAppId=") for v in env_vars):
                            return True
                    except (PermissionError, FileNotFoundError, OSError):
                        continue

            # Fallback: pgrep -f (covers cases where /proc scan missed something)
            r = subprocess.run(
                ["pgrep", "-f", "pressure-vessel"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return r.returncode == 0

        elif system == "Windows":
            # GameOverlayUI.exe is injected by Steam into every running game
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq GameOverlayUI.exe", "/NH"],
                capture_output=True, text=True,
            )
            return "gameoverlayui.exe" in r.stdout.lower()

    except Exception as e:
        _log(f"[steamSync] is_game_running check failed: {e}", level=logging.WARNING)

    return False


# Threshold for the "auto" strategy: restart when num_changes >= this value.
# Override at runtime: steamSync.AUTO_RESTART_THRESHOLD = N
AUTO_RESTART_THRESHOLD: int = 5


def choose_auto_strategy(
    num_changes: int,
    threshold:   int = 0,   # 0 → use module-level AUTO_RESTART_THRESHOLD
) -> PostSyncStrategy:
    """
    Choose between "restart" and "soft" based on the number of changed files.

    Threshold defaults to AUTO_RESTART_THRESHOLD (module constant, default 5).
    Pass an explicit threshold > 0 to override per-call.

    Used by the "auto" strategy mode in apply_post_sync_strategy().
    """
    effective_threshold = threshold if threshold > 0 else AUTO_RESTART_THRESHOLD
    return "restart" if num_changes >= effective_threshold else "soft"


def _is_flatpak_steam() -> bool:
    """Return True if Steam is running as a Flatpak application."""
    flatpak_info = Path.home() / ".var" / "app" / "com.valvesoftware.Steam"
    return flatpak_info.exists()


def restart_steam(*, interactive: bool = False, silent: bool = True) -> bool:
    """
    Fully restart Steam:
      0. Settle delay (1s) — lets filesystem watchers catch up
      1. Check for running games; warn/abort if found
      2. Send shutdown command (steam -shutdown  or  flatpak kill …)
      3. Wait 2 seconds for the process to exit
      4. Relaunch Steam (native or Flatpak, auto-detected)

    Game-running guard:
      interactive=True  → prompt the user, proceed only if confirmed
      silent=True       → downgrade to "soft" strategy (no restart)

    Returns True if restart was performed, False if aborted.
    Cross-platform. Never crashes the caller.
    """
    system = platform.system()

    # ── Step 0: Settle delay ───────────────────────────────────────────────
    _log("[steamSync] Waiting 1s for filesystem watchers to settle…")
    time.sleep(1)

    # ── Game-running guard ─────────────────────────────────────────────────
    if is_game_running():
        _log("[steamSync] WARNING: A game appears to be running.", level=logging.WARNING)
        if interactive and not silent:
            try:
                answer = input(
                    "[steamSync] A game appears to be running. "
                    "Restart Steam anyway? (y/n): "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"
            if answer != "y":
                _log("[steamSync] Restart aborted by user — game is running")
                return False
        else:
            _log("[steamSync] Silent mode: skipping restart — game is running")
            return False

    _log("[steamSync] Restarting Steam…")

    # ── Step 1: Shutdown ───────────────────────────────────────────────────
    try:
        if system == "Linux":
            if _is_flatpak_steam():
                # Flatpak: use flatpak kill to signal the sandbox
                subprocess.run(
                    ["flatpak", "kill", "com.valvesoftware.Steam"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=10,
                )
            else:
                subprocess.run(
                    ["steam", "-shutdown"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=10,
                )
        elif system == "Darwin":
            subprocess.run(
                ["osascript", "-e", 'tell application "Steam" to quit'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10,
            )
        elif system == "Windows":
            subprocess.run(
                ["steam.exe", "-shutdown"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10,
            )
        _log("[steamSync] Steam shutdown signal sent")
    except Exception as e:
        _log(f"[steamSync] Steam shutdown failed: {e}", level=logging.WARNING)

    # ── Step 2: Wait ───────────────────────────────────────────────────────
    time.sleep(2)

    # ── Step 3: Relaunch ───────────────────────────────────────────────────
    try:
        if system == "Linux":
            if _is_flatpak_steam():
                subprocess.Popen(
                    ["flatpak", "run", "com.valvesoftware.Steam"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            else:
                subprocess.Popen(
                    ["steam"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
        elif system == "Darwin":
            subprocess.Popen(
                ["open", "-a", "Steam"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elif system == "Windows":
            subprocess.Popen(
                ["cmd", "/c", "start", "", "steam://open/main"],
                shell=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        _log("[steamSync] Steam relaunch signal sent")
    except Exception as e:
        _log(f"[steamSync] Steam relaunch failed: {e}", level=logging.WARNING)

    return True


def apply_post_sync_strategy(
    strategy:     PostSyncStrategy,
    app_id:       int,
    steam_root:   Path,
    grid_dir:     Path,
    appid_dir:    Optional[Path],
    *,
    num_changes:  int  = 0,
    threshold:    int  = 0,       # 0 → use AUTO_RESTART_THRESHOLD
    interactive:  bool = False,
    silent:       bool = True,
) -> None:
    """
    Execute the requested post-sync strategy.

    "none"    — no-op
    "soft"    — touch grid + librarycache folders, send steam://reload/<app_id>
    "restart" — full Steam restart (settle → game guard → shutdown → relaunch)
    "auto"    — choose_auto_strategy(num_changes, threshold): restart if ≥threshold else soft

    If a restart is attempted but a game is running in silent mode, the
    strategy automatically falls back to "soft" for that run.

    The ``threshold`` kwarg overrides AUTO_RESTART_THRESHOLD for "auto" strategy.
    Never raises — errors are logged with [steamSync] prefix and swallowed.
    """
    if strategy == "none":
        _log("[steamSync] post-sync strategy: none — skipping invalidation")
        return

    if strategy == "soft":
        _log("[steamSync] post-sync strategy: soft — touching folders + reload signal")
        _touch(grid_dir)
        if appid_dir:
            _touch(appid_dir)
        _signal_reload(app_id)
        return

    if strategy == "restart":
        _log("[steamSync] post-sync strategy: restart — full Steam restart")
        restarted = restart_steam(interactive=interactive, silent=silent)
        if not restarted:
            # Game was running and restart was blocked — fall back to soft
            _log("[steamSync] restart blocked — falling back to soft strategy")
            apply_post_sync_strategy(
                "soft", app_id, steam_root, grid_dir, appid_dir,
                num_changes=num_changes, threshold=threshold,
                interactive=interactive, silent=silent,
            )
        return

    if strategy == "auto":
        effective = choose_auto_strategy(num_changes, threshold)
        _log(
            f"[steamSync] post-sync strategy: auto → {effective} "
            f"({num_changes} change(s), threshold={threshold or AUTO_RESTART_THRESHOLD})"
        )
        apply_post_sync_strategy(
            effective, app_id, steam_root, grid_dir, appid_dir,
            num_changes=num_changes, threshold=threshold,
            interactive=interactive, silent=silent,
        )
        return

    # Unknown strategy — log and fall back to soft
    _log(
        f"[steamSync] unknown post-sync strategy '{strategy}' — falling back to soft",
        level=logging.WARNING,
    )
    apply_post_sync_strategy(
        "soft", app_id, steam_root, grid_dir, appid_dir,
        num_changes=num_changes, threshold=threshold,
        interactive=interactive, silent=silent,
    )


def resolve_post_sync_strategy(
    *,
    steam_is_running: bool,
    interactive:      bool = False,
    silent:           bool = True,
    default_strategy: PostSyncStrategy = DEFAULT_SILENT_STRATEGY,
) -> PostSyncStrategy:
    """
    Determine which post-sync strategy to use based on runtime context.

    Priority:
      1. If not interactive (or silent): return default_strategy directly.
      2. If interactive and Steam is running: prompt the user.
         - "y" → "restart"
         - "n" → "soft"
      3. If interactive and Steam is NOT running: "soft" (nothing to restart).

    This is a pure helper — it does NOT execute the strategy.
    """
    if not interactive or silent:
        _log(f"[steamSync] post-sync strategy (silent): {default_strategy}")
        return default_strategy

    if not steam_is_running:
        _log("[steamSync] Steam is not running — using soft strategy")
        return "soft"

    # Interactive prompt
    try:
        answer = input(
            "\n[steamSync] Steam is running. Apply changes instantly? "
            "This will restart Steam. (y/n): "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        _log("\n[steamSync] Prompt interrupted — using soft strategy")
        return "soft"

    if answer == "y":
        _log("[steamSync] User chose: restart")
        return "restart"

    _log("[steamSync] User declined restart — using soft strategy")
    return "soft"


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
    app_id:           int,
    steam_id:         str,
    userdata_path:    Path,
    exports:          Dict[str, str],
    overwrite:        bool             = True,
    post_sync:        PostSyncStrategy = "soft",
    interactive:      bool             = False,
    silent:           bool             = True,
    default_strategy: PostSyncStrategy = DEFAULT_SILENT_STRATEGY,
    auto_threshold:   int              = 0,    # 0 → use AUTO_RESTART_THRESHOLD
) -> SyncResult:
    """
    Copy artwork to Steam's grid folder AND all discovered librarycache
    targets so the library UI shows the new images without a restart.

    Public API is backward-compatible — all new parameters are keyword-only
    with safe defaults. Existing callers (bulkSync, exportFlow) need no changes.
    A richer SyncSummary is available at result.summary.

    Post-sync behaviour is controlled by:
      post_sync        — explicit strategy ("none" / "soft" / "restart" / "auto")
                         used directly when interactive=False and silent=True
      interactive      — if True and Steam is running, prompt the user
      silent           — if True, suppress prompts; use default_strategy
      default_strategy — fallback when silent=True (default: "soft")
      auto_threshold   — override AUTO_RESTART_THRESHOLD for this call only

    When interactive=True and silent=False, resolve_post_sync_strategy()
    is called to determine the final strategy at runtime.
    """
    grid_dir   = get_grid_folder(userdata_path, steam_id)
    steam_root = userdata_path.parent
    result     = SyncResult(success=False, grid_folder=str(grid_dir))

    _log(f"[steamSync] app_id={app_id}")

    # ── C. Discover librarycache targets recursively ───────────────────────
    appid_dir  = _librarycache_dir(steam_root, app_id)
    lc_targets = find_librarycache_targets(appid_dir) if appid_dir else LibraryCacheTargets()

    _log(f"[steamSync] discovered cover targets:    {len(lc_targets.cover)}")
    _log(f"[steamSync] discovered header targets:   {len(lc_targets.header)}")
    _log(f"[steamSync] discovered hero targets:     {len(lc_targets.hero)}")
    _log(f"[steamSync] ignored hero_blur targets:   {len(lc_targets.hero_blur)}")
    _log(f"[steamSync] discovered logo targets:     {len(lc_targets.logo)}")
    _log(f"[steamSync] discovered icon targets:     {len(lc_targets.icon)}")
    _log(f"[steamSync] unknown files:               {len(lc_targets.unknown)}")

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

    # ── H. Post-sync strategy ─────────────────────────────────────────────
    if result.installed:
        # Determine the effective strategy
        if interactive and not silent:
            running  = is_steam_running()
            strategy = resolve_post_sync_strategy(
                steam_is_running = running,
                interactive      = interactive,
                silent           = silent,
                default_strategy = default_strategy,
            )
        else:
            # Silent / non-interactive: honour the explicit post_sync arg
            strategy = post_sync

        apply_post_sync_strategy(
            strategy     = strategy,
            app_id       = app_id,
            steam_root   = steam_root,
            grid_dir     = grid_dir,
            appid_dir    = appid_dir,
            num_changes  = len(result.installed),
            threshold    = auto_threshold,
            interactive  = interactive,
            silent       = silent,
        )

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

    result.success = summary.outcome != "failure"
    result.summary = summary

    _log(
        f"[steamSync] outcome: {summary.outcome} "
        f"(grid {grid_written}/{len(grid_ops)}, "
        f"lcache {lc_written}/{lc_found})"
    )

    return result