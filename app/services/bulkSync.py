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
        jobs: List[BulkSyncJob] = []

        for folder_name, template in _FOLDER_TO_TEMPLATE.items():
            folder = self._root / folder_name
            if not folder.is_dir():
                continue

            for png_path in sorted(folder.glob("*.png")):
                file_str = str(png_path)
                stem     = png_path.stem   

                # ── Identify game_name and app_id ─────────────────────────
                app_id:    Optional[int] = None
                game_name: str           = stem

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

                if app_id is None:
                    numeric_prefix = stem.split("_")[0] if "_" in stem else stem
                    if numeric_prefix.isdigit():
                        app_id = int(numeric_prefix)
                        canonical = self._registry.lookup_canonical(stem) or None
                        game_name = canonical or stem


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
        exports: dict,          
        app_id:  int,
    ) -> List[BulkSyncJob]:

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