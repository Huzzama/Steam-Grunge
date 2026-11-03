"""
PimpMySteam authentication for Steam Curator.
Token generated at pimpmysteam.com → Settings → Apps.
"""
import json
import threading
from pathlib import Path
from typing import Optional, Callable

from app.config import BASE_DIR, DATA_DIR, API_URL

# Token lives in the user-writable data dir (same settings.json the
# SteamGridDB key uses). The old location next to the code is read-only on
# installed builds and is only read as a fallback for migration.
SETTINGS_PATH        = Path(DATA_DIR) / "settings.json"
_LEGACY_SETTINGS     = BASE_DIR / "settings.json"
_TOKEN_KEY           = "steamkustom_token"


def _read_json(path: Path) -> dict:
    try:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[PimpMySteam] could not read {path}: {e}")
    return {}


def get_token() -> Optional[str]:
    token = _read_json(SETTINGS_PATH).get(_TOKEN_KEY)
    if not token:
        token = _read_json(_LEGACY_SETTINGS).get(_TOKEN_KEY)
    return token or None


def save_token(token: str) -> bool:
    try:
        data = _read_json(SETTINGS_PATH)
        data[_TOKEN_KEY] = token
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        try:
            import os
            os.chmod(SETTINGS_PATH, 0o600)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[PimpMySteam] save_token error: {e}")
        return False


def verify_token(token: str) -> Optional[dict]:
    """Returns user dict if valid, None otherwise."""
    try:
        import urllib.request, urllib.error, ssl
        req = urllib.request.Request(
            f"{API_URL}/auth/me",
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0 (compatible; SteamGrunge/1.0)",
            },
        )
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            if resp.status == 200:
                import json as _j
                return _j.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[PimpMySteam] HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        print(f"[PimpMySteam] URL error: {e.reason}")
    except Exception as e:
        print(f"[PimpMySteam] verify_token error: {e}")
    return None


def get_user() -> Optional[dict]:
    token = get_token()
    if not token:
        return None
    return verify_token(token)


def get_drive_token() -> Optional[str]:
    return get_drive_token_result()[0]


def get_drive_token_result() -> tuple[Optional[str], Optional[str]]:
    """
    (access token, None) when the backend hands us a Drive token, else
    (None, reason) — a sentence that says what to do about it. The backend
    answers 404 when the account has no Drive link and 502 when Google
    rejected the stored one; both used to collapse into "not connected".
    """
    token = get_token()
    if not token:
        return None, "No PimpMySteam token saved. Backup → Connect via PimpMySteam…"
    try:
        import urllib.request, urllib.error, ssl, json as _j
        req = urllib.request.Request(
            f"{API_URL}/google/drive-token",
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0 (compatible; SteamGrunge/1.0)",
            },
        )
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = _j.loads(resp.read().decode())
            access = data.get("access_token")
            if access:
                return access, None
            return None, "PimpMySteam answered without a Drive token. Try again in a minute."
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            body = e.read().decode(errors="replace")
            detail = _j.loads(body).get("detail", "") if body.strip().startswith("{") else body
        except Exception:
            pass
        detail = str(detail or "").strip()
        print(f"[PimpMySteam] drive-token HTTP {e.code}: {detail}")
        if e.code == 401:
            return None, ("PimpMySteam rejected the app token (revoked or expired). "
                          "Make a new one at pimpmysteam.com → Settings → Apps and paste it in "
                          "Backup → Connect via PimpMySteam…")
        if e.code == 404:
            return None, ("Google Drive is not connected to your PimpMySteam account. Signing in "
                          "with Google is not enough — open pimpmysteam.com → Settings → "
                          "Connections and press Connect Google Drive, then try again."
                          + (f"\n({detail})" if detail else ""))
        if e.code == 502:
            return None, ("Google rejected the Drive link stored for your account (it expired or "
                          "was revoked). On pimpmysteam.com → Settings → Connections disconnect "
                          "Google Drive and connect it again, then try again.")
        return None, f"PimpMySteam answered HTTP {e.code}{': ' + detail if detail else ''}."
    except urllib.error.URLError as e:
        print(f"[PimpMySteam] drive-token URL error: {e.reason}")
        return None, f"Could not reach api.pimpmysteam.com ({e.reason}). Check your connection."
    except Exception as e:
        print(f"[PimpMySteam] get_drive_token error: {e}")
        return None, f"Drive token error: {e}"


def get_steam_id() -> Optional[str]:
    user = get_user()
    if user:
        return user.get("steam_id") or user.get("steam_id64")
    return None


def verify_async(token: str, on_done: Callable[[bool, Optional[dict]], None]):
    """Always calls on_done even on error."""
    def _run():
        try:
            user = verify_token(token)
            on_done(bool(user), user)
        except Exception as e:
            print(f"[PimpMySteam] verify_async error: {e}")
            on_done(False, None)
    threading.Thread(target=_run, daemon=True).start()


def is_connected() -> bool:
    token = get_token()
    return bool(token) and bool(verify_token(token))


def get_steam_api_key(token: str = None) -> Optional[str]:
    """
    Get the Steam API key from the PimpMySteam backend.
    The key is stored server-side — users never need to enter it locally.
    """
    if not token:
        token = get_token()
    if not token:
        return None
    try:
        import urllib.request, ssl
        req = urllib.request.Request(
            f"{API_URL}/auth/steam-api-key",
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0 (compatible; SteamGrunge/1.0)",
            },
        )
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            if resp.status == 200:
                import json as _j
                return _j.loads(resp.read().decode()).get("api_key")
    except Exception as e:
        print(f"[SteamKustom] get_steam_api_key error: {e}")
    return None