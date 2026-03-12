"""
Persistent registry that maps game names → confirmed Steam AppIDs.

Survives application restarts so users never need to re-confirm the same
game twice. Stored as a simple JSON file in DATA_DIR.

Thread-safety:
  All mutations are protected by a threading.Lock, so background workers
  can call register() concurrently without corruption.

Usage:
    from app.services.appIdRegistry import AppIdRegistry

    reg = AppIdRegistry()
    reg.register("Resident Evil 4", 2050650, canonical="Resident Evil 4")

    app_id = reg.lookup("Resident Evil 4")   # → 2050650 or None
"""
from __future__ import annotations

import json
import os
import threading
from typing import Optional


class AppIdRegistry:
    """Persistent game-name → AppID mapping backed by a JSON file."""

    _instance: Optional["AppIdRegistry"] = None
    _lock = threading.Lock()

    # ── Singleton access ──────────────────────────────────────────────────────
    @classmethod
    def shared(cls) -> "AppIdRegistry":
        """Return the process-wide shared registry (lazy-initialized)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Init ─────────────────────────────────────────────────────────────────
    def __init__(self, path: Optional[str] = None):
        from app.config import DATA_DIR
        self._path = path or os.path.join(DATA_DIR, "appid_registry.json")
        self._lock = threading.Lock()
        self._data: dict = {}   # normalized_name → {"id": int, "canonical": str}
        self._load()

    # ── Public API ────────────────────────────────────────────────────────────
    def lookup(self, game_name: str) -> Optional[int]:
        """
        Return the confirmed AppID for *game_name*, or None if unknown.
        Lookup is case-insensitive and strips leading/trailing whitespace.
        """
        key = self._normalize(game_name)
        with self._lock:
            entry = self._data.get(key)
            return entry["id"] if entry else None

    def lookup_canonical(self, game_name: str) -> Optional[str]:
        """Return the canonical Steam name for *game_name*, if known."""
        key = self._normalize(game_name)
        with self._lock:
            entry = self._data.get(key)
            return entry.get("canonical") if entry else None

    def register(self, game_name: str, app_id: int,
                 canonical: Optional[str] = None):
        """
        Persist a confirmed game_name → app_id mapping.
        If *canonical* is given, the Steam-canonical name is stored too.
        Overwrites any previous mapping for the same normalized name.
        """
        key = self._normalize(game_name)
        with self._lock:
            self._data[key] = {
                "id":        app_id,
                "canonical": canonical or game_name,
            }
            self._save_unlocked()

    def remove(self, game_name: str):
        """Remove a mapping (e.g. if the user selected the wrong game)."""
        key = self._normalize(game_name)
        with self._lock:
            if key in self._data:
                del self._data[key]
                self._save_unlocked()

    def all_entries(self) -> dict:
        """Return a snapshot of {normalized_name: {id, canonical}} for UIs."""
        with self._lock:
            return dict(self._data)

    # ── Internal ──────────────────────────────────────────────────────────────
    @staticmethod
    def _normalize(name: str) -> str:
        return name.strip().lower()

    def _load(self):
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                # Accept both old flat {name: id} and new {name: {id, canonical}}
                for k, v in raw.items():
                    if isinstance(v, int):
                        self._data[k] = {"id": v, "canonical": k}
                    elif isinstance(v, dict) and "id" in v:
                        self._data[k] = v
        except Exception as e:
            print(f"[AppIdRegistry] Load error (starting fresh): {e}")
            self._data = {}

    def _save_unlocked(self):
        """Must be called with self._lock held."""
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._path)
        except Exception as e:
            print(f"[AppIdRegistry] Save error: {e}")