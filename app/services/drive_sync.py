"""
drive_sync.py — Google Drive backup of the Steam custom-artwork folder.

One ZIP per Steam account:  Drive / "Steam Grunge Editor" / backups / steam-grid-<steamid>.zip
containing everything inside  Steam/userdata/<steamid>/config/grid/
(every custom cover, wide, hero, logo and icon actually applied to Steam —
including artwork applied by other tools).

Public API (all blocking — call from a worker thread):
    is_configured()      → PimpMySteam token saved
    is_authenticated()   → backend hands us a Drive access token
    backup_grid(steam_id, on_progress)  → {"ok", "files", "bytes", "error"}
    restore_grid(steam_id, on_progress) → {"ok", "files", "error"}
    list_backups()       → [{"steam_id", "name", "size", "modified"}]
"""
import io
import re
import time
import zipfile
from pathlib import Path
from typing import Optional, Callable

DRIVE_ROOT_NAME = "Steam Grunge Editor"
DRIVE_BACKUPS   = "backups"
_ZIP_RE         = re.compile(r"steam-grid-(\d+)\.zip")

Progress = Optional[Callable[[str], None]]


# ── Auth ───────────────────────────────────────────────────────────────────────

def _get_pimpmysteam_token() -> Optional[str]:
    from app.services.steamkustom_auth import get_token
    return get_token()

def _fetch_drive_token() -> Optional[str]:
    from app.services.steamkustom_auth import get_drive_token
    return get_drive_token()

def is_configured() -> bool:
    return bool(_get_pimpmysteam_token())

def is_authenticated() -> bool:
    return bool(_fetch_drive_token())

def drive_status() -> dict:
    """{"configured", "authenticated", "reason"} — reason says what to fix when not authenticated."""
    from app.services.steamkustom_auth import get_drive_token_result
    token = _get_pimpmysteam_token()
    if not token:
        return {"configured": False, "authenticated": False,
                "reason": "No token found.\nBackup → Connect via PimpMySteam…"}
    access, reason = get_drive_token_result()
    return {"configured": True, "authenticated": bool(access), "reason": reason}

def get_status() -> dict:
    st = drive_status()
    return {"configured": st["configured"], "authenticated": st["authenticated"]}


# ── Drive helpers ──────────────────────────────────────────────────────────────

def _service():
    from app.services.steamkustom_auth import get_drive_token_result
    access_token, reason = get_drive_token_result()
    if not access_token:
        raise RuntimeError(reason or "Not connected to Google Drive. "
                           "Use Backup → Connect via PimpMySteam… first.")
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(token=access_token)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _q(value: str) -> str:
    """Escape a value for a Drive query string."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _get_or_create_folder(svc, name: str, parent_id: str = None) -> str:
    q = (f"name='{_q(name)}' and mimeType='application/vnd.google-apps.folder'"
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


def _backups_folder(svc) -> str:
    root_id = _get_or_create_folder(svc, DRIVE_ROOT_NAME)
    return _get_or_create_folder(svc, DRIVE_BACKUPS, root_id)


def _find_zip(svc, folder_id: str, name: str) -> Optional[dict]:
    q = (f"name='{_q(name)}' and '{folder_id}' in parents and trashed=false"
         f" and mimeType!='application/vnd.google-apps.folder'")
    files = svc.files().list(
        q=q, fields="files(id, name, size, modifiedTime)").execute().get("files", [])
    return files[0] if files else None


# ── Steam grid folder ──────────────────────────────────────────────────────────

def _grid_dir(steam_id: str) -> Path:
    from app.services.steamSync import find_steam_userdata, get_grid_folder
    userdata = find_steam_userdata()
    if not userdata:
        raise RuntimeError("Steam installation not found.")
    return get_grid_folder(userdata, steam_id)


def _zip_name(steam_id: str) -> str:
    return f"steam-grid-{steam_id}.zip"


def _zip_grid(grid: Path, on_progress: Progress = None) -> tuple[bytes, int]:
    """Zip every file under *grid* (recursively). Returns (zip_bytes, file_count)."""
    buf = io.BytesIO()
    files = [p for p in sorted(grid.rglob("*")) if p.is_file()]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for i, p in enumerate(files, 1):
            if on_progress and (i % 25 == 0 or i == len(files)):
                on_progress(f"Compressing {i}/{len(files)}…")
            zf.write(p, p.relative_to(grid).as_posix())
    return buf.getvalue(), len(files)


# ── Public API ─────────────────────────────────────────────────────────────────

def backup_grid(steam_id: str, on_progress: Progress = None) -> dict:
    """
    Zip Steam/userdata/<steam_id>/config/grid and upload it to Drive,
    replacing the previous backup for that account.
    """
    try:
        grid = _grid_dir(steam_id)
        if on_progress:
            on_progress("Reading Steam grid folder…")
        data, count = _zip_grid(grid, on_progress)
        if count == 0:
            return {"ok": False, "files": 0, "bytes": 0,
                    "error": "Grid folder is empty — nothing to back up."}

        from googleapiclient.http import MediaIoBaseUpload
        svc       = _service()
        folder_id = _backups_folder(svc)
        name      = _zip_name(steam_id)
        media     = MediaIoBaseUpload(io.BytesIO(data), mimetype="application/zip",
                                      resumable=True, chunksize=4 * 1024 * 1024)
        if on_progress:
            on_progress(f"Uploading {name} ({len(data) / 1024 / 1024:.1f} MB)…")

        existing = _find_zip(svc, folder_id, name)
        if existing:
            svc.files().update(fileId=existing["id"], media_body=media).execute()
        else:
            svc.files().create(body={"name": name, "parents": [folder_id]},
                               media_body=media, fields="id").execute()
        return {"ok": True, "files": count, "bytes": len(data), "error": None}
    except Exception as e:
        return {"ok": False, "files": 0, "bytes": 0, "error": str(e)}


def restore_grid(steam_id: str, on_progress: Progress = None) -> dict:
    """
    Download the backup ZIP for *steam_id* and extract it into the grid folder
    (existing files with the same name are overwritten), then ask Steam to
    reload its library.
    """
    try:
        from googleapiclient.http import MediaIoBaseDownload
        svc       = _service()
        folder_id = _backups_folder(svc)
        name      = _zip_name(steam_id)
        entry     = _find_zip(svc, folder_id, name)
        if not entry:
            return {"ok": False, "files": 0,
                    "error": f"No backup found on Drive for Steam account {steam_id}."}

        if on_progress:
            on_progress(f"Downloading {name}…")
        buf = io.BytesIO()
        dl  = MediaIoBaseDownload(buf, svc.files().get_media(fileId=entry["id"]))
        done = False
        while not done:
            status, done = dl.next_chunk()
            if on_progress and status:
                on_progress(f"Downloading… {int(status.progress() * 100)}%")

        grid = _grid_dir(steam_id)
        buf.seek(0)
        count = 0
        with zipfile.ZipFile(buf) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            for i, m in enumerate(members, 1):
                target = (grid / m.filename).resolve()
                if grid.resolve() not in target.parents:
                    continue   # never write outside the grid folder
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(m) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                count += 1
                if on_progress and (i % 25 == 0 or i == len(members)):
                    on_progress(f"Restoring {i}/{len(members)}…")

        # Steam only re-reads the grid folder on restart (or when a single
        # app is reloaded); the caller tells the user to restart Steam.
        return {"ok": True, "files": count, "error": None}
    except Exception as e:
        return {"ok": False, "files": 0, "error": str(e)}


def list_backups() -> list:
    """Return the backup ZIPs currently on Drive (one per Steam account)."""
    svc       = _service()
    folder_id = _backups_folder(svc)
    files = svc.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(id, name, size, modifiedTime)",
    ).execute().get("files", [])
    out = []
    for f in files:
        m = _ZIP_RE.fullmatch(f.get("name", ""))
        if not m:
            continue
        out.append({
            "steam_id": m.group(1),
            "name":     f["name"],
            "size":     int(f.get("size", 0) or 0),
            "modified": f.get("modifiedTime", ""),
        })
    return out
