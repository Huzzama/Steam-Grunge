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
    token = get_token()
    if not token:
        return None
    try:
        import urllib.request, ssl
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
            if resp.status == 200:
                import json as _j
                return _j.loads(resp.read().decode()).get("access_token")
    except Exception as e:
        print(f"[PimpMySteam] get_drive_token error: {e}")
    return None


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