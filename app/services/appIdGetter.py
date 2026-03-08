"""
app/services/appIdGetter.py
Resolves a Steam AppID for a given game name by querying the
Steam Store search API (no API key needed).
Falls back to a SteamDB scrape if the store API returns nothing.
"""
from __future__ import annotations
import re
import urllib.parse
import urllib.request
import json
from typing import Optional


# Steam Store search — public, no key required
_STORE_SEARCH = "https://store.steampowered.com/api/storesearch/?term={query}&l=en&cc=US"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


def get_app_id(game_name: str, timeout: int = 8) -> Optional[int]:
    """
    Return the best-matching Steam AppID for *game_name*, or None on failure.
    Uses the Steam Store search API — no scraping, no key required.
    """
    query   = urllib.parse.quote(game_name)
    url     = _STORE_SEARCH.format(query=query)
    req     = urllib.request.Request(url, headers=_HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data  = json.loads(resp.read().decode("utf-8"))
            items = data.get("items", [])
    except Exception as e:
        print(f"[appIdGetter] Steam Store search failed: {e}")
        return None

    if not items:
        return None

    # Try exact match first (case-insensitive), then fall back to first result
    name_lower = game_name.lower().strip()
    for item in items:
        if item.get("name", "").lower().strip() == name_lower:
            return int(item["id"])

    # Return closest (first) result
    return int(items[0]["id"])


def get_app_id_and_name(game_name: str, timeout: int = 8) -> tuple[Optional[int], str]:
    """
    Return (app_id, canonical_name) or (None, game_name) on failure.
    The canonical name is what Steam Store returned, useful to show in the UI.
    """
    query   = urllib.parse.quote(game_name)
    url     = _STORE_SEARCH.format(query=query)
    req     = urllib.request.Request(url, headers=_HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data  = json.loads(resp.read().decode("utf-8"))
            items = data.get("items", [])
    except Exception as e:
        print(f"[appIdGetter] Steam Store search failed: {e}")
        return None, game_name

    if not items:
        return None, game_name

    name_lower = game_name.lower().strip()
    for item in items:
        if item.get("name", "").lower().strip() == name_lower:
            return int(item["id"]), item["name"]

    first = items[0]
    return int(first["id"]), first["name"]


def search_candidates(game_name: str, limit: int = 8,
                      timeout: int = 8) -> list[dict]:
    """
    Return up to *limit* candidates as [{"id": int, "name": str}, …].
    Used in the sync dialog so the user can pick from a list.
    """
    query = urllib.parse.quote(game_name)
    url   = _STORE_SEARCH.format(query=query)
    req   = urllib.request.Request(url, headers=_HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data  = json.loads(resp.read().decode("utf-8"))
            items = data.get("items", [])
    except Exception as e:
        print(f"[appIdGetter] candidate search failed: {e}")
        return []

    return [{"id": int(i["id"]), "name": i["name"]}
            for i in items[:limit] if "id" in i and "name" in i]