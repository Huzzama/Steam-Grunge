"""
Persistent record of every Steam sync operation, keyed by
(game_name, template).

Each entry records:
  - app_id          confirmed Steam AppID
  - template        asset type (cover, wide, hero, …)
  - file_path       absolute path to the exported PNG
  - file_hash       SHA-256 of the file at the time of last successful sync
  - last_synced     ISO-8601 timestamp of last successful sync
  - status          "ok" | "error" | "skipped"
  - error_message   last error, if any

Change detection:
  manifest.is_changed(path, game, template) → True  means file has changed
  (or was never synced) and should be included in the next sync run.

Thread-safety: all mutations protected by threading.Lock.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from typing import Optional


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sha256(path: str) -> Optional[str]:
    """Return hex SHA-256 of file at *path*, or None on error."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manifest_key(game_name: str, template: str) -> str:
    return f"{game_name.strip().lower()}::{template}"


# ── SyncManifest ───────────────────────────────────────────────────────────────

class SyncManifest:
    """Persistent sync history and file-fingerprint store."""

    _instance: Optional["SyncManifest"] = None
    _class_lock = threading.Lock()

    @classmethod
    def shared(cls) -> "SyncManifest":
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self, path: Optional[str] = None):
        from app.config import DATA_DIR
        self._path = path or os.path.join(DATA_DIR, "sync_manifest.json")
        self._lock = threading.Lock()
        self._data: dict = {}
        self._load()

    # ── Public API ────────────────────────────────────────────────────────────

    def is_changed(self, file_path: str, game_name: str, template: str) -> bool:
        """
        Return True if:
          - This (game, template) pair has never been synced, OR
          - The file has changed since the last successful sync.
        """
        key = _manifest_key(game_name, template)
        with self._lock:
            entry = self._data.get(key)
            if not entry or entry.get("status") != "ok":
                return True
            if entry.get("file_path") != file_path:
                return True
            stored_hash = entry.get("file_hash")
            if not stored_hash:
                return True
        # Hash comparison outside lock (slow I/O)
        current_hash = _sha256(file_path)
        return current_hash != stored_hash

    def record_success(self, file_path: str, game_name: str,
                       template: str, app_id: int):
        """Record a successful sync for (game, template)."""
        key   = _manifest_key(game_name, template)
        fhash = _sha256(file_path)
        with self._lock:
            self._data[key] = {
                "game_name":    game_name,
                "app_id":       app_id,
                "template":     template,
                "file_path":    file_path,
                "file_hash":    fhash,
                "last_synced":  _now_iso(),
                "status":       "ok",
                "error_message": "",
            }
            self._save_unlocked()

    def record_error(self, file_path: str, game_name: str,
                     template: str, app_id: int, error: str):
        """Record a failed sync (does NOT update the file hash)."""
        key = _manifest_key(game_name, template)
        with self._lock:
            prev = self._data.get(key, {})
            self._data[key] = {
                "game_name":    game_name,
                "app_id":       app_id,
                "template":     template,
                "file_path":    file_path,
                "file_hash":    prev.get("file_hash"),   # keep old hash
                "last_synced":  prev.get("last_synced"),
                "status":       "error",
                "error_message": error,
            }
            self._save_unlocked()

    def get_entry(self, game_name: str, template: str) -> Optional[dict]:
        """Return the raw manifest entry for (game, template), or None."""
        key = _manifest_key(game_name, template)
        with self._lock:
            return dict(self._data[key]) if key in self._data else None

    def all_entries(self) -> list[dict]:
        """Return a snapshot of all manifest entries as a list of dicts."""
        with self._lock:
            return [dict(v) for v in self._data.values()]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load(self):
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
        except Exception as e:
            print(f"[SyncManifest] Load error (starting fresh): {e}")
            self._data = {}

    def _save_unlocked(self):
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._path)
        except Exception as e:
            print(f"[SyncManifest] Save error: {e}")