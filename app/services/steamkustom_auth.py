"""
PimpMySteam authentication for Steam Grunge Editor.
Token generated at pimpmysteam.com → Settings → Apps.
"""
import json
import threading
from pathlib import Path
from typing import Optional, Callable

_BASE_DIR   = Path(__file__).resolve().parents[2]
_PREFS_PATH = _BASE_DIR / "app" / "data" / "preferences.json"
API_URL     = "https://steamkustom-production.up.railway.app"


def get_token() -> Optional[str]:
    try:
        if _PREFS_PATH.exists():
            with open(_PREFS_PATH, encoding="utf-8") as f:
                return json.load(f).get("steamkustom_token") or None
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
    except Exception as e:
        print(f"[PimpMySteam] save_token error: {e}")
        return False


def verify_token(token: str) -> Optional[dict]:
    """Verify token. Returns user dict or None."""
    if not token or not token.strip():
        print("[PimpMySteam] verify_token: empty token")
        return None

    token = token.strip()
    print(f"[PimpMySteam] Verifying token (len={len(token)}) against {API_URL}")

    try:
        import urllib.request, urllib.error, ssl
        req = urllib.request.Request(
            f"{API_URL}/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Use certifi certificates — works in PyInstaller bundles on macOS
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            if resp.status == 200:
                import json as _json
                data = _json.loads(resp.read().decode())
                print(f"[PimpMySteam] Token valid — user: {data.get('username')}")
                return data
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode()
        except: pass
        print(f"[PimpMySteam] HTTP {e.code}: {e.reason} — {body[:200]}")
    except urllib.error.URLError as e:
        print(f"[PimpMySteam] URL error: {e.reason}")
    except Exception as e:
        print(f"[PimpMySteam] verify_token error: {type(e).__name__}: {e}")
    return None


def get_user() -> Optional[dict]:
    token = get_token()
    if not token:
        return None
    return verify_token(token)


def get_drive_token() -> Optional[str]:
    """Get Google Drive access token via PimpMySteam API."""
    token = get_token()
    if not token:
        return None
    try:
        import urllib.request, ssl
        req = urllib.request.Request(
            f"{API_URL}/google/drive-token",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Use certifi certificates — works in PyInstaller bundles on macOS
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            if resp.status == 200:
                import json as _json
                return _json.loads(resp.read().decode()).get("access_token")
    except Exception as e:
        print(f"[PimpMySteam] get_drive_token error: {e}")
    return None


def verify_async(token: str, on_done: Callable[[bool, Optional[dict]], None]):
    """Verify token in background. Always calls on_done."""
    def _run():
        try:
            user = verify_token(token)
            on_done(bool(user), user)
        except Exception as e:
            print(f"[PimpMySteam] verify_async unhandled: {e}")
            on_done(False, None)
    threading.Thread(target=_run, daemon=True).start()


def is_connected() -> bool:
    token = get_token()
    if not token:
        return False
    return bool(verify_token(token))