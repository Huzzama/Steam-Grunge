"""
Google Drive sync for Steam Grunge Editor.

Syncs:
  - exports/   → all exported artwork (cover, wide, hero, logo, icon)
  - data/      → presets and project files (.sgeproj)

Credentials:
  - client_secret.json  → place in project root (next to requirements.txt)
  - token.json          → auto-created after first auth, same location
"""
import io
import os
import threading
from pathlib import Path
from typing import Optional, Callable

# ── Paths ─────────────────────────────────────────────────────────────────────
_BASE_DIR          = Path(__file__).resolve().parents[2]   # project root
CLIENT_SECRET_PATH = _BASE_DIR / "client_secret.json"
TOKEN_PATH         = _BASE_DIR / "token.json"

# Sync what lives in user data dir
from app.config import EXPORT_FOLDER, DATA_DIR, PRESETS_FOLDER

EXPORT_DIR   = Path(EXPORT_FOLDER)
DATA_DIR_P   = Path(DATA_DIR)

SCOPES          = ["https://www.googleapis.com/auth/drive.file"]
DRIVE_ROOT_NAME = "Steam Grunge Editor"
DRIVE_EXPORTS   = "exports"
DRIVE_PRESETS   = "presets"

EXPORT_EXTS  = {".png", ".jpg", ".jpeg", ".webp"}
PRESET_EXTS  = {".sgeproj", ".json"}


# ── Auth ──────────────────────────────────────────────────────────────────────

def is_configured() -> bool:
    return CLIENT_SECRET_PATH.exists()


def is_authenticated() -> bool:
    if not TOKEN_PATH.exists():
        return False
    try:
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        return creds and (creds.valid or bool(creds.refresh_token))
    except Exception:
        return False


def authenticate(on_done: Callable[[bool, str], None] = None):
    """Open browser for OAuth. Calls on_done(success, message) when finished."""
    def _run():
        try:
            creds = _load_or_refresh()
            msg   = "Connected to Google Drive" if creds else "Authentication failed"
            if on_done:
                on_done(bool(creds), msg)
        except Exception as e:
            if on_done:
                on_done(False, str(e))
    threading.Thread(target=_run, daemon=True).start()


def disconnect():
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()


def _load_or_refresh():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow  = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return creds


def _service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_load_or_refresh())


# ── Drive helpers ─────────────────────────────────────────────────────────────

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
        ".png":     "image/png",
        ".jpg":     "image/jpeg",
        ".jpeg":    "image/jpeg",
        ".webp":    "image/webp",
        ".sgeproj": "application/json",
        ".json":    "application/json",
    }.get(path.suffix.lower(), "application/octet-stream")


def _upload_file(svc, path: Path, parent_id: str):
    from googleapiclient.http import MediaFileUpload
    media    = MediaFileUpload(str(path), mimetype=_mime(path), resumable=False)
    existing = _find_file(svc, path.name, parent_id)
    if existing:
        svc.files().update(fileId=existing, media_body=media).execute()
    else:
        svc.files().create(
            body={"name": path.name, "parents": [parent_id]},
            media_body=media, fields="id",
        ).execute()


def _download_file(svc, file_id: str, dest: Path):
    from googleapiclient.http import MediaIoBaseDownload
    request = svc.files().get_media(fileId=file_id)
    buf     = io.BytesIO()
    dl      = MediaIoBaseDownload(buf, request)
    done    = False
    while not done:
        _, done = dl.next_chunk()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(buf.getvalue())


# ── Public API ────────────────────────────────────────────────────────────────

def upload_all(on_progress: Callable[[str], None] = None) -> dict:
    """
    Upload all exports and presets to Drive.
    Returns {"uploaded": n, "errors": [...]}.
    """
    uploaded, errors = 0, []
    try:
        svc      = _service()
        root_id  = _get_or_create_folder(svc, DRIVE_ROOT_NAME)
        exp_id   = _get_or_create_folder(svc, DRIVE_EXPORTS, root_id)
        pre_id   = _get_or_create_folder(svc, DRIVE_PRESETS,  root_id)

        # Exports — walk all subfolders (cover/, wide/, hero/, etc.)
        if EXPORT_DIR.exists():
            for f in sorted(EXPORT_DIR.rglob("*")):
                if f.is_file() and f.suffix.lower() in EXPORT_EXTS:
                    try:
                        if on_progress:
                            on_progress(f"Uploading {f.name}…")
                        _upload_file(svc, f, exp_id)
                        uploaded += 1
                    except Exception as e:
                        errors.append(f"{f.name}: {e}")

        # Presets / project files
        if DATA_DIR_P.exists():
            for f in sorted(DATA_DIR_P.rglob("*")):
                if f.is_file() and f.suffix.lower() in PRESET_EXTS:
                    try:
                        if on_progress:
                            on_progress(f"Uploading {f.name}…")
                        _upload_file(svc, f, pre_id)
                        uploaded += 1
                    except Exception as e:
                        errors.append(f"{f.name}: {e}")

    except Exception as e:
        errors.append(f"Error: {e}")

    return {"uploaded": uploaded, "errors": errors}


def download_all(on_progress: Callable[[str], None] = None) -> dict:
    """
    Download exports and presets from Drive to local folders.
    Skips files that already exist locally.
    """
    downloaded, errors = 0, []
    try:
        svc = _service()

        q       = (f"name='{DRIVE_ROOT_NAME}' and "
                   f"mimeType='application/vnd.google-apps.folder' and trashed=false")
        folders = svc.files().list(q=q, fields="files(id)").execute().get("files", [])
        if not folders:
            return {"downloaded": 0, "errors": ["No Drive folder found. Upload first."]}

        root_id = folders[0]["id"]

        for subfolder_name, local_dir, allowed_exts in [
            (DRIVE_EXPORTS, EXPORT_DIR,   EXPORT_EXTS),
            (DRIVE_PRESETS, DATA_DIR_P,   PRESET_EXTS),
        ]:
            q2 = (f"name='{subfolder_name}' and '{root_id}' in parents and "
                  f"mimeType='application/vnd.google-apps.folder' and trashed=false")
            r2 = svc.files().list(q=q2, fields="files(id)").execute()
            if not r2.get("files"):
                continue

            sub_id = r2["files"][0]["id"]
            files  = svc.files().list(
                q=f"'{sub_id}' in parents and trashed=false",
                fields="files(id, name)",
            ).execute().get("files", [])

            for file in files:
                ext  = Path(file["name"]).suffix.lower()
                if ext not in allowed_exts:
                    continue
                dest = local_dir / file["name"]
                if dest.exists():
                    continue
                try:
                    if on_progress:
                        on_progress(f"Downloading {file['name']}…")
                    _download_file(svc, file["id"], dest)
                    downloaded += 1
                except Exception as e:
                    errors.append(f"{file['name']}: {e}")

    except Exception as e:
        errors.append(f"Error: {e}")

    return {"downloaded": downloaded, "errors": errors}


def get_status() -> dict:
    return {
        "configured":    is_configured(),
        "authenticated": is_authenticated(),
    }