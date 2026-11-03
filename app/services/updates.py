"""
updates.py — "Check for updates" against GitHub releases.

check_latest(current) → {"latest", "available", "url", "error"}; never raises.
Blocking (one HTTPS request) — call it from a worker thread.
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.request

REPO         = "Huzzama/Steam-Grunge"
RELEASES_URL = f"https://github.com/{REPO}/releases"


def parse_version(v: str) -> tuple:
    """'v4.1.0-beta.2' → ((4, 1, 0), 'beta.2'); a pre-release sorts below the plain version."""
    v = (v or "").strip().lstrip("vV")
    core, _, pre = v.partition("-")
    nums = tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.]", core) if x != "")
    nums = (nums + (0, 0, 0))[:max(3, len(nums))]
    return nums, pre


def compare_versions(a: str, b: str) -> int:
    """1 if a is newer than b, -1 if older, 0 if the same."""
    na, pa = parse_version(a)
    nb, pb = parse_version(b)
    width = max(len(na), len(nb))
    na, nb = na + (0,) * (width - len(na)), nb + (0,) * (width - len(nb))
    if na != nb:
        return 1 if na > nb else -1
    if pa == pb:
        return 0
    if not pa:
        return 1
    if not pb:
        return -1
    return 1 if pa > pb else -1


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def check_latest(current: str, *, timeout: float = 8.0, opener=None) -> dict:
    """
    opener: an optional callable(url) -> bytes, for tests. The default asks
    api.github.com for releases/latest (60 anonymous calls per hour — plenty).
    """
    url = f"https://api.github.com/repos/{REPO}/releases/latest"
    try:
        if opener is not None:
            raw = opener(url)
        else:
            req = urllib.request.Request(url, headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"SteamGrungeEditor/{current}",
            })
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
                raw = resp.read()
        data = json.loads(raw)
        latest = str(data.get("tag_name", "")).strip().lstrip("vV")
        if not latest:
            return {"latest": current, "available": False, "url": RELEASES_URL, "error": None}
        return {
            "latest":    latest,
            "available": compare_versions(latest, current) > 0,
            "url":       data.get("html_url") or RELEASES_URL,
            "error":     None,
        }
    except urllib.error.HTTPError as e:
        if e.code == 404:          # no release published yet
            return {"latest": current, "available": False, "url": RELEASES_URL, "error": None}
        return {"latest": None, "available": False, "url": RELEASES_URL, "error": f"GitHub answered HTTP {e.code}"}
    except Exception as e:
        return {"latest": None, "available": False, "url": RELEASES_URL, "error": str(e)}
