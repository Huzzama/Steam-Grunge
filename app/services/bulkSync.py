"""
Bulk Steam sync with change detection.

Architecture
------------
Planning and execution are strictly separated:

  BulkSyncPlanner.plan(export_root)
    → Scans export folders, resolves AppIDs from AppIdRegistry, checks
      SyncManifest, classifies each asset into one of:
        "new"         → never synced
        "changed"     → synced before but file has changed
        "unchanged"   → synced, hash matches — skip by default
        "missing_id"  → game name not in registry

  BulkSyncExecutor.run(jobs, steam_id, userdata_path, on_progress)
    → Executes only the supplied jobs, records results to SyncManifest
      and AppIdRegistry, calls on_progress(job) after each job.

This separation means the UI can show the plan before anything touches
Steam, and let the user force-include unchanged assets if desired.

Usage (from Qt)
---------------
    from app.services.bulkSync import BulkSyncPlanner, BulkSyncExecutor

    planner = BulkSyncPlanner()
    jobs = planner.plan()

    # Filter as desired
    to_run = [j for j in jobs if j.status in ("new", "changed")]

    executor = BulkSyncExecutor()
    executor.run(to_run, steam_id, userdata_path,
                 on_progress=lambda j: print(j))
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, List

from app.services.appIdRegistry import AppIdRegistry
from app.services.syncManifest   import SyncManifest
from app.services.steamSync      import sync_artwork, find_steam_userdata


# ── BulkSyncJob ───────────────────────────────────────────────────────────────

@dataclass
class BulkSyncJob:
    """
    Represents a single asset to be (potentially) synced to Steam.

    Status values
    -------------
    "new"         — file exists, never synced
    "changed"     — file changed since last successful sync
    "unchanged"   — file unchanged — skip by default
    "missing_id"  — no AppID found in registry for this game
    "ok"          — sync completed successfully  (set by executor)
    "error"       — sync failed                 (set by executor)
    """
    game_name:  str
    template:   str
    file_path:  str
    app_id:     Optional[int]
    status:     str               # see above
    error:      str = ""          # populated after error
    # Set after execution
    sync_result: Optional[object] = field(default=None, repr=False)


# ── BulkSyncPlanner ───────────────────────────────────────────────────────────

# Map export sub-folder name → template key used in registry / manifest
_FOLDER_TO_TEMPLATE = {
    "cover": "cover",
    "wide":  "wide",
    "hero":  "hero",
    "logo":  "logo",
    "icon":  "icon",
}

# Reverse: template → expected filename pattern (for future use)
_TEMPLATE_LABELS = {
    "cover": "Cover (600×900)",
    "wide":  "Wide / Header (920×430)",
    "hero":  "Hero (3840×1240)",
    "logo":  "Logo (1280×720)",
    "icon":  "Icon (512×512)",
}


class BulkSyncPlanner:
    """
    Scans exported PNG files under *export_root* and builds a list of
    BulkSyncJob objects, one per (game, template) pair found.

    File naming convention (set by exportFlow.py):
        <export_root>/<template>/<appid>*.png   or
        <export_root>/<template>/<appid>_<suffix>.png

    Because the filename already encodes the AppID, we also accept
    manually placed files — as long as the filename starts with a run
    of digits we treat that as the AppID and skip registry lookup for it.

    Otherwise we scan the registry by game_name inferred from the file.
    """

    def __init__(
        self,
        export_root: Optional[str] = None,
        registry: Optional[AppIdRegistry] = None,
        manifest: Optional[SyncManifest]  = None,
    ):
        from app.config import EXPORT_FOLDER
        self._root     = Path(export_root or EXPORT_FOLDER)
        self._registry = registry or AppIdRegistry.shared()
        self._manifest = manifest or SyncManifest.shared()

    def plan(self, game_name_filter: Optional[str] = None) -> List[BulkSyncJob]:
        """
        Scan all exported assets and return a BulkSyncJob for each one.

        Asset identification order (most → least reliable):
          1. Numeric filename stem → AppID from registry by canonical name
          2. Manifest record      → app_id stored from a previous sync
          3. Registry lookup      → game name stem → app_id
          4. Filename heuristic   → pure digit prefix treated as raw app_id
        """
        jobs: List[BulkSyncJob] = []

        for folder_name, template in _FOLDER_TO_TEMPLATE.items():
            folder = self._root / folder_name
            if not folder.is_dir():
                continue

            for png_path in sorted(folder.glob("*.png")):
                file_str = str(png_path)
                stem     = png_path.stem   # e.g. "1971870" or "Cyberpunk 2077_cover"

                # ── Identify game_name and app_id ─────────────────────────
                app_id:    Optional[int] = None
                game_name: str           = stem

                # 1. Check sync manifest — most reliable if the file was
                #    synced before: manifest stores both game_name and app_id.
                manifest_match = None
                for entry in self._manifest.all_entries():
                    if (entry.get("template") == template and
                            os.path.normpath(entry.get("file_path", "")) ==
                            os.path.normpath(file_str)):
                        manifest_match = entry
                        break

                if manifest_match:
                    game_name = manifest_match.get("game_name", stem)
                    app_id    = manifest_match.get("app_id")

                # 2. Pure numeric stem → use as app_id directly, look up
                #    canonical name from registry if available.
                if app_id is None:
                    numeric_prefix = stem.split("_")[0] if "_" in stem else stem
                    if numeric_prefix.isdigit():
                        app_id = int(numeric_prefix)
                        canonical = self._registry.lookup_canonical(stem) or None
                        game_name = canonical or stem

                # 3. Registry lookup by stem (non-numeric filenames like
                #    "Resident_Evil_4_cover").
                if app_id is None:
                    app_id = self._registry.lookup(stem)

                if game_name_filter and \
                        game_name.strip().lower() != game_name_filter.strip().lower():
                    continue

                # ── Classify ──────────────────────────────────────────────
                if app_id is None:
                    status = "missing_id"
                elif self._manifest.is_changed(file_str, game_name, template):
                    entry = self._manifest.get_entry(game_name, template)
                    status = "new" if not entry else "changed"
                else:
                    status = "unchanged"

                jobs.append(BulkSyncJob(
                    game_name = game_name,
                    template  = template,
                    file_path = file_str,
                    app_id    = app_id,
                    status    = status,
                ))

        return jobs

    def plan_for_tab_exports(
        self,
        game_name: str,
        exports: dict,          # {template: absolute_path}
        app_id:  int,
    ) -> List[BulkSyncJob]:
        """
        Build a plan from a specific tab's exports dict (used by single-tab sync).
        Always treats each asset as "new" or "changed" — no unchanged filtering.
        """
        jobs = []
        for template, path in exports.items():
            if not path or not os.path.isfile(path):
                continue
            changed = self._manifest.is_changed(path, game_name, template)
            status  = "changed" if changed else "unchanged"
            entry   = self._manifest.get_entry(game_name, template)
            if not entry:
                status = "new"
            jobs.append(BulkSyncJob(
                game_name = game_name,
                template  = template,
                file_path = path,
                app_id    = app_id,
                status    = status,
            ))
        return jobs


# ── BulkSyncExecutor ─────────────────────────────────────────────────────────

class BulkSyncExecutor:
    """
    Executes a list of BulkSyncJob objects against Steam.

    Runs synchronously — wrap in QThread for UI use.
    Calls on_progress(job) after each job (job.status updated to "ok"/"error").
    """

    def __init__(
        self,
        registry: Optional[AppIdRegistry] = None,
        manifest: Optional[SyncManifest]  = None,
    ):
        self._registry = registry or AppIdRegistry.shared()
        self._manifest = manifest or SyncManifest.shared()

    def run(
        self,
        jobs: List[BulkSyncJob],
        steam_id: str,
        userdata_path: Optional[Path],
        on_progress: Optional[Callable[[BulkSyncJob], None]] = None,
        force: bool = False,
    ) -> List[BulkSyncJob]:
        """
        Execute *jobs*, updating each job's status in-place.

        Parameters
        ----------
        force : if True, run even "unchanged" jobs.

        Returns the same list with statuses updated.
        """
        if userdata_path is None:
            userdata_path = find_steam_userdata()

        for job in jobs:
            if job.status == "unchanged" and not force:
                if on_progress:
                    on_progress(job)
                continue

            if job.status == "missing_id" or job.app_id is None:
                job.status = "error"
                job.error  = "No AppID — confirm game first."
                if on_progress:
                    on_progress(job)
                continue

            try:
                result = sync_artwork(
                    app_id        = job.app_id,
                    steam_id      = steam_id,
                    userdata_path = userdata_path,
                    exports       = {job.template: job.file_path},
                    overwrite     = True,
                )
                job.sync_result = result
                if result.success:
                    job.status = "ok"
                    self._manifest.record_success(
                        job.file_path, job.game_name, job.template, job.app_id
                    )
                    # Persist mapping in case it wasn't already there
                    self._registry.register(job.game_name, job.app_id)
                else:
                    err = "; ".join(result.errors) or "Unknown sync error"
                    job.status = "error"
                    job.error  = err
                    self._manifest.record_error(
                        job.file_path, job.game_name, job.template,
                        job.app_id, err
                    )
            except Exception as e:
                job.status = "error"
                job.error  = str(e)
                self._manifest.record_error(
                    job.file_path, job.game_name, job.template,
                    job.app_id or 0, str(e)
                )

            if on_progress:
                on_progress(job)

        return jobs