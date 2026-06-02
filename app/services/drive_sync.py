"""
Google Drive sync for Steam Grunge Editor.
Auth is handled exclusively via SteamKustom API token.
No client_secret.json needed.
"""
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


# ── Auth — token only ─────────────────────────────────────────────────────────

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


# ── Drive helpers ─────────────────────────────────────────────────────────────

def _service():
    access_token = _fetch_drive_token()
    if not access_token:
        raise RuntimeError(
            "No SteamKustom token found. "
            "Go to Edit → Preferences and paste your token from steamkustom.com"
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


def _upload_file(svc, path: Path, parent_id: str) -> str:
    """Upload file. Returns 'uploaded', 'updated', or 'skipped'."""
    from googleapiclient.http import MediaFileUpload

    # Check if file exists on Drive
    q = (f"name='{path.name}' and '{parent_id}' in parents and trashed=false"
         f" and mimeType!='application/vnd.google-apps.folder'")
    files = svc.files().list(q=q, fields="files(id, md5Checksum)").execute().get("files", [])

    local_md5 = _file_md5(path)

    if files:
        drive_md5 = files[0].get("md5Checksum", "")
        if drive_md5 == local_md5:
            return "skipped"  # Identical file already on Drive
        # Different content — update
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


# ── Public API ────────────────────────────────────────────────────────────────

def upload_all(on_progress: Callable[[str], None] = None) -> dict:
    uploaded, errors = 0, []
    try:
        svc      = _service()
        root_id  = _get_or_create_folder(svc, DRIVE_ROOT_NAME)
        exp_id   = _get_or_create_folder(svc, DRIVE_EXPORTS, root_id)
        pre_id   = _get_or_create_folder(svc, DRIVE_PRESETS,  root_id)

        for folder, parent_id, exts in [
            (EXPORT_DIR, exp_id, EXPORT_EXTS),
            (DATA_DIR_P, pre_id, PRESET_EXTS),
        ]:
            if not folder.exists():
                continue
            for f in sorted(folder.rglob("*")):
                if not f.is_file() or f.suffix.lower() not in exts:
                    continue
                try:
                    result = _upload_file(svc, f, parent_id)
                    if result == "skipped":
                        if on_progress:
                            on_progress(f"Skipped {f.name} (unchanged)")
                    else:
                        if on_progress:
                            on_progress(f"{'Updating' if result == 'updated' else 'Uploading'} {f.name}…")
                        uploaded += 1
                except Exception as e:
                    errors.append(f"{f.name}: {e}")

    except Exception as e:
        errors.append(str(e))

    return {"uploaded": uploaded, "errors": errors}


def download_all(on_progress: Callable[[str], None] = None) -> dict:
    downloaded, errors = 0, []
    try:
        svc = _service()
        q   = (f"name='{DRIVE_ROOT_NAME}' and "
               f"mimeType='application/vnd.google-apps.folder' and trashed=false")
        folders = svc.files().list(q=q, fields="files(id)").execute().get("files", [])
        if not folders:
            return {"downloaded": 0, "errors": ["No Drive folder found. Upload first."]}

        root_id = folders[0]["id"]
        for sub_name, local_dir, allowed_exts in [
            (DRIVE_EXPORTS, EXPORT_DIR, EXPORT_EXTS),
            (DRIVE_PRESETS, DATA_DIR_P, PRESET_EXTS),
        ]:
            q2 = (f"name='{sub_name}' and '{root_id}' in parents and "
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
                if Path(file["name"]).suffix.lower() not in allowed_exts:
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
        errors.append(str(e))

    return {"downloaded": downloaded, "errors": errors}