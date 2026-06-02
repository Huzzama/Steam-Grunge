"""
SteamKustom authentication for Steam Grunge Editor.

User generates a token at steamkustom.com → Settings → Apps.
No Google OAuth or Steam login needed locally.
"""
import json
import threading
from pathlib import Path
from typing import Optional, Callable

_BASE_DIR = Path(__file__).resolve().parents[2]
_PREFS_PATH = _BASE_DIR / "app" / "data" / "preferences.json"
API_URL = "https://steamkustom-production.up.railway.app"


def get_token() -> Optional[str]:
    try:
        if _PREFS_PATH.exists():
            with open(_PREFS_PATH, encoding="utf-8") as f:
                return json.load(f).get("steamkustom_token", "")
    except Exception:
        pass
    return None


def save_token(token: str) -> bool:
    try:
        _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if _PREFS_PATH.exists():
            with open(_PREFS_PATH, encoding="utf-8") as f:
                data = json.load(f)
        data["steamkustom_token"] = token
        with open(_PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def verify_token(token: str) -> Optional[dict]:
    """Verify token against API. Returns user dict or None."""
    import requests
    try:
        resp = requests.get(
            f"{API_URL}/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
        if resp.status_code == 200:
            return resp.json()
        print(f"[SteamKustom] Token verify failed: HTTP {resp.status_code}")
    except requests.exceptions.ConnectionError:
        print(f"[SteamKustom] Cannot reach {API_URL} — check internet connection")
    except Exception as e:
        print(f"[SteamKustom] Token verify error: {e}")
    return None


def get_user() -> Optional[dict]:
    token = get_token()
    if not token:
        return None
    return verify_token(token)


def get_drive_token() -> Optional[str]:
    """Get Google Drive access token via SteamKustom API."""
    import requests
    token = get_token()
    if not token:
        return None
    try:
        resp = requests.get(
            f"{API_URL}/google/drive-token",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
    except Exception:
        pass
    return None


def verify_async(token: str,
                 on_done: Callable[[bool, Optional[dict]], None]):
    """Verify token in background thread. Always calls on_done."""
    def _run():
        try:
            user = verify_token(token)
            on_done(bool(user), user)
        except Exception as e:
            print(f"[SteamKustom] verify_async error: {e}")
            on_done(False, None)
    threading.Thread(target=_run, daemon=True).start()


def is_connected() -> bool:
    return bool(get_token()) and bool(get_user())