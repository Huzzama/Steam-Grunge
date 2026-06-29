import io
from pathlib import Path
from typing import Optional, Callable
import threading

_BASE_DIR = Path(__file__).resolve().parents[2]

try:
    from app.config import EXPORT_FOLDER, DATA_DIR
    EXPORT_DIR = Path(EXPORT_FOLDER)
    DATA_DIR_P = Path(DATA_DIR)
except Exception:
    EXPORT_DIR = _BASE_DIR / "exports"
    DATA_DIR_P = _BASE_DIR / "data"

SCOPES          = ["https://www.googleapis.com/auth/drive.file"]
DRIVE_ROOT_NAME = "Steam Grunge Editor"
DRIVE_EXPORTS   = "exports"
DRIVE_PRESETS   = "presets"
EXPORT_EXTS     = {".png", ".jpg", ".jpeg", ".webp"}
PRESET_EXTS     = {".sgeproj", ".json"}

def _export_subfolders() -> dict:
    try:
        from app.config import EXPORT_COVER, EXPORT_WIDE, EXPORT_HERO, EXPORT_LOGO, EXPORT_ICON
        return {
            "cover": Path(EXPORT_COVER),
            "wide":  Path(EXPORT_WIDE),
            "hero":  Path(EXPORT_HERO),
            "logo":  Path(EXPORT_LOGO),
            "icon":  Path(EXPORT_ICON),
        }
    except Exception:
        base = EXPORT_DIR
        return {k: base / k for k in ("cover","wide","hero","logo","icon")}

def _template_to_subfolder_name(template: str) -> str:
    return {"cover":"cover","vhs_cover":"cover","wide":"wide",
            "vhs_pile":"wide","vhs_cassette":"wide",
            "hero":"hero","logo":"logo","icon":"icon"}.get(template, "cover")


# ── Auth ───────────────────────────────────────────────────────────────────────

def _get_steamkustom_token() -> Optional[str]:
    from app.services.steamkustom_auth import get_token
    return get_token()

def _fetch_drive_token() -> Optional[str]:
    from app.services.steamkustom_auth import get_drive_token
    return get_drive_token()

def is_configured() -> bool:
    return bool(_get_steamkustom_token())

def is_authenticated() -> bool:
    return bool(_fetch_drive_token())

def get_status() -> dict:
    token = _get_steamkustom_token()
    return {
        "configured":    bool(token),
        "authenticated": bool(_fetch_drive_token()) if token else False,
        "mode":          "api" if token else "none",
    }


# ── Drive helpers ──────────────────────────────────────────────────────────────

def _service():
    access_token = _fetch_drive_token()
    if not access_token:
        raise RuntimeError(
            "No PimpMySteam token found. "
            "Go to Edit → Preferences and paste your token from pimpmysteam.com"
        )
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(token=access_token)
    return build("drive", "v3", credentials=creds)

def _get_or_create_folder(svc, name: str, parent_id: str = None) -> str:
    q = (f"name='{name}' and mimeType='application/vnd.google-apps.folder'"
         f" and trashed=false")
    if parent_id:
        q += f" and '{parent_id}' in parents"
    files = svc.files().list(q=q, fields="files(id)").execute().get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        meta["parents"] = [parent_id]
    return svc.files().create(body=meta, fields="id").execute()["id"]

def _find_file(svc, name: str, parent_id: str) -> Optional[str]:
    q = (f"name='{name}' and '{parent_id}' in parents and trashed=false"
         f" and mimeType!='application/vnd.google-apps.folder'")
    files = svc.files().list(q=q, fields="files(id)").execute().get("files", [])
    return files[0]["id"] if files else None

def _mime(path: Path) -> str:
    return {
        ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".webp": "image/webp",
        ".sgeproj": "application/json", ".json": "application/json",
    }.get(path.suffix.lower(), "application/octet-stream")

def _file_md5(path: Path) -> str:
    import hashlib
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def _file_mtime(path: Path) -> float:
    """Return file modification time as Unix timestamp."""
    try:
        return path.stat().st_mtime
    except Exception:
        return 0.0


def _upload_file(svc, path: Path, parent_id: str) -> str:
    """Upload or update file. Returns 'uploaded', 'updated', or 'skipped'."""
    from googleapiclient.http import MediaFileUpload
    q = (f"name='{path.name}' and '{parent_id}' in parents and trashed=false"
         f" and mimeType!='application/vnd.google-apps.folder'")
    files = svc.files().list(q=q, fields="files(id, md5Checksum)").execute().get("files", [])
    local_md5 = _file_md5(path)
    if files:
        drive_md5 = files[0].get("md5Checksum", "")
        if drive_md5 == local_md5:
            return "skipped"
        media = MediaFileUpload(str(path), mimetype=_mime(path), resumable=False)
        svc.files().update(fileId=files[0]["id"], media_body=media).execute()
        return "updated"
    else:
        media = MediaFileUpload(str(path), mimetype=_mime(path), resumable=False)
        svc.files().create(
            body={"name": path.name, "parents": [parent_id]},
            media_body=media, fields="id",
        ).execute()
        return "uploaded"


def _download_file(svc, file_id: str, dest: Path):
    from googleapiclient.http import MediaIoBaseDownload
    buf  = io.BytesIO()
    dl   = MediaIoBaseDownload(buf, svc.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = dl.next_chunk()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(buf.getvalue())


# ── Export filename classification ────────────────────────────────────────────

def _classify_export_file(filename: str):
    """
    Parse a Steam Grunge export filename and return (app_id_int, template_str).

    Current export naming convention (from exportFlow.py):
      {appid}.png          → cover
      {appid}p.png         → wide
      {appid}_hero.png     → hero
      {appid}_logo.png     → logo
      {appid}_icon.png     → icon

    Legacy naming convention (older exporter versions):
      GameName_cover_YYYYMMDD_HHMMSS.png   → cover  (app_id = None)
      GameName_hero_YYYYMMDD_HHMMSS.png    → hero   (app_id = None)
      GameName_wide_YYYYMMDD_HHMMSS.png    → wide   (app_id = None)
      GameName_vhs_cover_YYYYMMDD_HHMMSS.png → cover (app_id = None)
      etc.

    Legacy files are classified by type but return app_id=None because
    the game name alone can't be reliably mapped to a Steam AppID without
    an external lookup. They will be sorted into the correct subfolder on
    download but cannot be applied to Steam automatically.

    Returns (app_id_int_or_None, template_str_or_None).
    """
    import re
    name = Path(filename).stem

    # ── Current format: {appid}[_type] ───────────────────────────────────────
    m = re.fullmatch(r"(\d+)_(hero|logo|icon)", name)
    if m:
        return int(m.group(1)), m.group(2)
    m = re.fullmatch(r"(\d+)p", name)
    if m:
        return int(m.group(1)), "wide"
    m = re.fullmatch(r"(\d+)", name)
    if m:
        return int(m.group(1)), "cover"

    # ── Legacy format: GameName_type_YYYYMMDD_HHMMSS ─────────────────────────
    # Strip optional timestamp suffix (_YYYYMMDD_HHMMSS or _YYYYMMDD_HHMMSSSS)
    name_no_ts = re.sub(r"_\d{8}_\d{6,}$", "", name)

    # Check for known template suffixes at the end of the name
    _legacy_suffixes = [
        ("_vhs_cover", "cover"),
        ("_vhs_pile",  "wide"),
        ("_vhs_cassette", "wide"),
        ("_cover",     "cover"),
        ("_wide",      "wide"),
        ("_hero",      "hero"),
        ("_logo",      "logo"),
        ("_icon",      "icon"),
        ("_header",    "wide"),   # some older versions used _header for wide
    ]
    for suffix, template in _legacy_suffixes:
        if name_no_ts.lower().endswith(suffix):
            # app_id is None — we know the type but not which Steam game
            return None, template

    return None, None


# ── Conflict detection ────────────────────────────────────────────────────────

def _detect_conflicts(svc, local_files: list[Path], parent_id: str) -> list[dict]:
    """
    Compare local export files against what's already on Drive.
    Returns a list of conflict dicts:
      {
        "filename":   str,
        "local_path": Path,
        "local_mtime": float,   # Unix timestamp
        "drive_md5":  str,
        "local_md5":  str,
        "winner":     "local" | "drive"   # which is newer
      }
    A conflict exists when: file is on Drive AND content differs.
    The winner is whichever has the more recent modification time
    (local mtime vs Drive modifiedTime).
    """
    conflicts = []
    for path in local_files:
        q = (f"name='{path.name}' and '{parent_id}' in parents and trashed=false"
             f" and mimeType!='application/vnd.google-apps.folder'")
        files = svc.files().list(
            q=q, fields="files(id, md5Checksum, modifiedTime)"
        ).execute().get("files", [])
        if not files:
            continue
        drive_md5   = files[0].get("md5Checksum", "")
        local_md5   = _file_md5(path)
        if drive_md5 == local_md5:
            continue   # identical — no conflict

        # Parse Drive modifiedTime (RFC3339)
        import datetime
        drive_mtime_str = files[0].get("modifiedTime", "")
        try:
            dt = datetime.datetime.fromisoformat(
                drive_mtime_str.replace("Z", "+00:00"))
            drive_mtime = dt.timestamp()
        except Exception:
            drive_mtime = 0.0

        local_mtime = _file_mtime(path)
        winner = "local" if local_mtime >= drive_mtime else "drive"

        app_id, template = _classify_export_file(path.name)
        conflicts.append({
            "filename":    path.name,
            "local_path":  path,
            "app_id":      app_id,
            "template":    template,
            "local_mtime": local_mtime,
            "drive_mtime": drive_mtime,
            "drive_md5":   drive_md5,
            "local_md5":   local_md5,
            "winner":      winner,
        })
    return conflicts


# ── Apply downloads to Steam ──────────────────────────────────────────────────

def _apply_downloaded_to_steam(
    downloaded_paths: list[Path],
    on_progress: Callable[[str], None] = None,
) -> dict:
    """
    After a Drive download, apply each recognized export file to Steam
    via sync_artwork(). Files that don't match the export naming convention
    (presets, .json, unknown) are skipped silently.

    Returns {"synced": N, "skipped": N, "errors": [...]}.
    """
    from app.services.steamSync import (
        find_steam_userdata, list_steam_ids, sync_artwork,
    )
    from collections import defaultdict

    synced, skipped = 0, 0
    errors = []

    userdata = find_steam_userdata()
    if not userdata:
        return {"synced": 0, "skipped": len(downloaded_paths),
                "errors": ["Steam userdata folder not found — is Steam installed?"]}

    steam_ids = list_steam_ids(userdata)
    if not steam_ids:
        return {"synced": 0, "skipped": len(downloaded_paths),
                "errors": ["No Steam user found in userdata/"]}

    steam_id = steam_ids[0]

    by_app: dict[int, dict[str, str]] = defaultdict(dict)
    legacy_files = []   # files with known type but no app_id (legacy filenames)
    for path in downloaded_paths:
        app_id, template = _classify_export_file(path.name)
        if app_id is None:
            if template is not None:
                legacy_files.append(path.name)
            skipped += 1
            continue
        # If two files map to the same (app_id, template) — e.g. the file
        # exists both in the old flat exports/ root AND in the new subfolder
        # after migration — keep the one with the most recent mtime so we
        # always apply the newest version and never process it twice.
        existing = by_app[app_id].get(template)
        if existing:
            existing_mtime = Path(existing).stat().st_mtime if Path(existing).exists() else 0
            new_mtime      = path.stat().st_mtime if path.exists() else 0
            if new_mtime <= existing_mtime:
                continue   # existing is newer or same — skip the duplicate
        by_app[app_id][template] = str(path)

    if legacy_files:
        print(f"[Drive] {len(legacy_files)} legacy file(s) downloaded to correct "
              f"subfolder but need manual AppID to apply to Steam: "
              + ", ".join(legacy_files[:3])
              + ("…" if len(legacy_files) > 3 else ""))

    total_games = len(by_app)
    for i, (app_id, exports) in enumerate(by_app.items(), 1):
        try:
            if on_progress:
                on_progress(f"Applying to Steam ({i}/{total_games}): app {app_id}…")
            result = sync_artwork(
                app_id        = app_id,
                steam_id      = steam_id,
                userdata_path = userdata,
                exports       = exports,
                overwrite     = True,
                post_sync     = "soft",
            )
            if result.success:
                synced += len(exports)
            else:
                errors.append(f"app {app_id}: {result.errors}")
        except Exception as e:
            errors.append(f"app {app_id}: {e}")

    return {"synced": synced, "skipped": skipped, "errors": errors}


# ── Public API ─────────────────────────────────────────────────────────────────

def upload_all(
    on_progress: Callable[[str], None] = None,
    resolve_conflicts: str = "newest",   # "newest" | "local" | "drive" | "ask"
) -> dict:
    """
    Upload local exports and presets to Drive.

    Conflict resolution (when local file != Drive file for the same name):
      "newest"  — keep whichever was modified more recently (default)
      "local"   — always overwrite Drive with local version
      "drive"   — keep Drive version, skip local upload
      "ask"     — return conflicts in result for the UI to present to the user

    Returns:
      {"uploaded": N, "errors": [...], "conflicts": [...], "skipped_conflicts": N}
    """
    uploaded, errors, conflicts_found, skipped_conflicts = 0, [], [], 0
    try:
        svc     = _service()
        root_id = _get_or_create_folder(svc, DRIVE_ROOT_NAME)
        exp_id  = _get_or_create_folder(svc, DRIVE_EXPORTS, root_id)
        pre_id  = _get_or_create_folder(svc, DRIVE_PRESETS,  root_id)

        for folder, parent_id, exts in [
            (EXPORT_DIR, exp_id, EXPORT_EXTS),
            (DATA_DIR_P, pre_id, PRESET_EXTS),
        ]:
            if not folder.exists():
                continue

            all_files = [f for f in sorted(folder.rglob("*"))
                         if f.is_file() and f.suffix.lower() in exts]

            # Detect conflicts before uploading
            if resolve_conflicts in ("newest", "drive", "ask") and all_files:
                if on_progress:
                    on_progress("Checking for conflicts on Drive…")
                detected = _detect_conflicts(svc, all_files, parent_id)
                conflicts_found.extend(detected)

                if resolve_conflicts == "ask" and detected:
                    # Return early with conflicts — caller (UI) will re-call
                    # with explicit resolution per file.
                    return {
                        "uploaded":          0,
                        "errors":            [],
                        "conflicts":         detected,
                        "skipped_conflicts": 0,
                        "needs_resolution":  True,
                    }

            for f in all_files:
                # Check if this file has a conflict and how to resolve it
                conflict = next(
                    (c for c in conflicts_found if c["local_path"] == f), None)

                if conflict:
                    winner = (
                        resolve_conflicts if resolve_conflicts in ("local", "drive")
                        else conflict["winner"]   # "newest" → use detected winner
                    )
                    if winner == "drive":
                        skipped_conflicts += 1
                        if on_progress:
                            on_progress(
                                f"Keeping Drive version of {f.name} "
                                f"(Drive is newer)")
                        continue
                    # winner == "local" → fall through to upload

                try:
                    result = _upload_file(svc, f, parent_id)
                    if result == "skipped":
                        if on_progress:
                            on_progress(f"Skipped {f.name} (unchanged)")
                    else:
                        verb = "Updated" if result == "updated" else "Uploading"
                        if on_progress:
                            on_progress(f"{verb} {f.name}…")
                        uploaded += 1
                except Exception as e:
                    errors.append(f"{f.name}: {e}")

    except Exception as e:
        errors.append(str(e))

    return {
        "uploaded":          uploaded,
        "errors":            errors,
        "conflicts":         conflicts_found,
        "skipped_conflicts": skipped_conflicts,
        "needs_resolution":  False,
    }


def download_all(on_progress: Callable[[str], None] = None) -> dict:
    """
    Download files from Drive into the correct per-type local subfolders
    (exports/cover/, exports/wide/, exports/hero/, exports/logo/, exports/icon/),
    then apply recognized export files to Steam automatically.
    """
    downloaded, errors = 0, []
    downloaded_paths = []
    try:
        svc = _service()
        q   = (f"name='{DRIVE_ROOT_NAME}' and "
               f"mimeType='application/vnd.google-apps.folder' and trashed=false")
        folders = svc.files().list(q=q, fields="files(id)").execute().get("files", [])
        if not folders:
            return {"downloaded": 0, "synced": 0,
                    "errors": ["No Drive folder found. Upload first."]}

        root_id    = folders[0]["id"]
        subfolders = _export_subfolders()

        # ── Per-type subfolders (cover/, wide/, hero/, logo/, icon/) ──────────
        q_exp = (f"name='{DRIVE_EXPORTS}' and '{root_id}' in parents and "
                 f"mimeType='application/vnd.google-apps.folder' and trashed=false")
        r_exp = svc.files().list(q=q_exp, fields="files(id)").execute()
        exp_drive_id = r_exp["files"][0]["id"] if r_exp.get("files") else None

        if exp_drive_id:
            for type_name, local_dir in subfolders.items():
                q_sub = (f"name='{type_name}' and '{exp_drive_id}' in parents and "
                         f"mimeType='application/vnd.google-apps.folder' and trashed=false")
                r_sub = svc.files().list(q=q_sub, fields="files(id)").execute()
                if not r_sub.get("files"):
                    continue
                sub_id = r_sub["files"][0]["id"]
                files  = svc.files().list(
                    q=f"'{sub_id}' in parents and trashed=false",
                    fields="files(id, name)",
                ).execute().get("files", [])
                total = len(files)
                for idx, file in enumerate(files, 1):
                    if Path(file["name"]).suffix.lower() not in EXPORT_EXTS:
                        continue
                    dest = local_dir / file["name"]
                    if dest.exists():
                        continue
                    # Check if this file exists in the old flat exports/ root —
                    # if so, move it to the correct subfolder instead of
                    # re-downloading from Drive (saves bandwidth + time).
                    flat_path = EXPORT_DIR / file["name"]
                    if flat_path.exists() and flat_path != dest:
                        try:
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            flat_path.rename(dest)
                            if on_progress:
                                on_progress(
                                    f"Moved {file['name']} → {type_name}/")
                            downloaded_paths.append(dest)
                            downloaded += 1
                        except Exception as e:
                            errors.append(f"move {file['name']}: {e}")
                        continue
                    try:
                        if on_progress:
                            on_progress(
                                f"Downloading {type_name}/{file['name']} ({idx}/{total})…")
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        _download_file(svc, file["id"], dest)
                        downloaded += 1
                        downloaded_paths.append(dest)
                    except Exception as e:
                        errors.append(f"{type_name}/{file['name']}: {e}")

            # ── Legacy fallback: flat files in exports/ ────────────────────────
            flat_files = svc.files().list(
                q=(f"'{exp_drive_id}' in parents and trashed=false and "
                   f"mimeType!='application/vnd.google-apps.folder'"),
                fields="files(id, name)",
            ).execute().get("files", [])
            for file in flat_files:
                if Path(file["name"]).suffix.lower() not in EXPORT_EXTS:
                    continue
                _, template = _classify_export_file(file["name"])
                if template is None:
                    continue
                local_dir = subfolders.get(
                    _template_to_subfolder_name(template), EXPORT_DIR)
                dest = local_dir / file["name"]
                if dest.exists():
                    continue
                try:
                    if on_progress:
                        on_progress(f"Downloading (legacy) {file['name']}…")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    _download_file(svc, file["id"], dest)
                    downloaded += 1
                    downloaded_paths.append(dest)
                except Exception as e:
                    errors.append(f"{file['name']}: {e}")

        # ── Presets ───────────────────────────────────────────────────────────
        q_pre = (f"name='{DRIVE_PRESETS}' and '{root_id}' in parents and "
                 f"mimeType='application/vnd.google-apps.folder' and trashed=false")
        r_pre = svc.files().list(q=q_pre, fields="files(id)").execute()
        if r_pre.get("files"):
            pre_id    = r_pre["files"][0]["id"]
            pre_files = svc.files().list(
                q=f"'{pre_id}' in parents and trashed=false",
                fields="files(id, name)",
            ).execute().get("files", [])
            for file in pre_files:
                if Path(file["name"]).suffix.lower() not in PRESET_EXTS:
                    continue
                dest = DATA_DIR_P / file["name"]
                if dest.exists():
                    continue
                try:
                    if on_progress:
                        on_progress(f"Downloading preset {file['name']}…")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    _download_file(svc, file["id"], dest)
                    downloaded += 1
                except Exception as e:
                    errors.append(f"{file['name']}: {e}")

    except Exception as e:
        errors.append(str(e))

    # ── Apply to Steam ────────────────────────────────────────────────────────
    synced = 0
    if downloaded_paths:
        if on_progress:
            on_progress("Applying to Steam…")
        try:
            sync_result = _apply_downloaded_to_steam(downloaded_paths, on_progress)
            synced = sync_result.get("synced", 0)
            if sync_result.get("errors"):
                errors.extend(sync_result["errors"])
        except Exception as e:
            errors.append(f"Steam sync failed: {e}")

    return {"downloaded": downloaded, "synced": synced, "errors": errors}