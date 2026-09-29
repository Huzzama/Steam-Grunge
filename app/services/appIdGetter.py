from __future__ import annotations

import json
import logging
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

_STORE_SEARCH = (
    "https://store.steampowered.com/api/storesearch/?term={query}&l=en&cc=US"
)
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


# ── Structured result ──────────────────────────────────────────────────────────

@dataclass
class SearchResult:
    candidates:    List[dict] = field(default_factory=list)
    error_code:    str = ""          # "" = success
    error_message: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_code

    def __bool__(self) -> bool:
        return bool(self.candidates)


class NetworkError(Exception):
    """Raised by search_candidates() for network/SSL/timeout failures."""


# ── Internal fetch ─────────────────────────────────────────────────────────────

def _fetch_raw(query: str, timeout: int) -> list:
    """
    Return raw item list from Steam Store search API.
    Raises typed exceptions so _safe_fetch can categorise them.
    """
    query = query.strip()
    if not query:
        return []

    encoded = urllib.parse.quote(query)
    url     = _STORE_SEARCH.format(query=encoded)
    headers = {"User-Agent": _UA}

    try:
        import requests as _req

        verify: object = True
        try:
            import certifi
            verify = certifi.where()
        except ImportError:
            pass   

        resp = _req.get(url, headers=headers, timeout=timeout, verify=verify)
        resp.raise_for_status()
        return resp.json().get("items", [])

    except ImportError:
        log.debug("[appIdGetter] requests not available — trying urllib")

    except Exception as exc:
        # Classify and re-raise so _safe_fetch can handle it correctly.
        exc_type = type(exc).__name__
        if "SSLError" in exc_type:
            raise ssl.SSLError(str(exc)) from exc
        if "Timeout" in exc_type or "ReadTimeout" in exc_type:
            raise TimeoutError(str(exc)) from exc
        if "HTTPError" in exc_type:
            raise ConnectionError(str(exc)) from exc
        if "ConnectionError" in exc_type or "RequestException" in exc_type:
            raise ConnectionError(str(exc)) from exc
        if isinstance(exc, (ValueError, KeyError)):
            raise ValueError(f"Malformed response: {exc}") from exc
        raise ConnectionError(str(exc)) from exc

    # ── Strategy 2: urllib (requests not installed). Certificates are still
    # verified — a wrong AppID would be written into the Steam library and
    # persisted, so we never accept an unverified peer.
    log.debug("[appIdGetter] Using urllib fallback")
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode("utf-8")).get("items", [])
    except TimeoutError as exc:
        raise TimeoutError(str(exc)) from exc
    except ssl.SSLError as exc:
        raise ssl.SSLError(str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Malformed response: {exc}") from exc
    except Exception as exc:
        raise ConnectionError(str(exc)) from exc


def _safe_fetch(query: str, timeout: int) -> SearchResult:
    """
    Wraps _fetch_raw and converts every exception into a SearchResult.
    Never raises — always returns a SearchResult.
    """
    try:
        items = _fetch_raw(query, timeout)
        if not items:
            return SearchResult(error_code="no_results",
                                error_message="No games found on Steam for that name.")
        return SearchResult(candidates=items)

    except TimeoutError as exc:
        msg = f"Steam search timed out after {timeout}s. Check your connection."
        log.warning("[appIdGetter] timeout: %s", exc)
        return SearchResult(error_code="timeout", error_message=msg)

    except ssl.SSLError as exc:
        msg = (
            "SSL certificate validation failed. "
            "On macOS this is common in packaged builds — "
            "install certifi (pip install certifi) to fix it. "
            f"Detail: {exc}"
        )
        log.warning("[appIdGetter] ssl error: %s", exc)
        return SearchResult(error_code="ssl", error_message=msg)

    except ConnectionError as exc:
        msg = f"Network error contacting Steam: {exc}"
        log.warning("[appIdGetter] network error: %s", exc)
        return SearchResult(error_code="network", error_message=msg)

    except ValueError as exc:
        msg = f"Steam returned an unexpected response: {exc}"
        log.warning("[appIdGetter] parse error: %s", exc)
        return SearchResult(error_code="parse", error_message=msg)

    except Exception as exc:
        msg = f"Unexpected error during Steam search: {exc}"
        log.exception("[appIdGetter] unexpected: %s", exc)
        return SearchResult(error_code="network", error_message=msg)


# ── Candidate helpers ──────────────────────────────────────────────────────────

def _clean_candidates(items: list, limit: int) -> list:
    seen, out = set(), []
    for item in items:
        try:
            cid   = int(item["id"])
            cname = str(item.get("name", "")).strip()
        except (KeyError, ValueError, TypeError):
            continue
        if cid not in seen and cname:
            seen.add(cid)
            out.append({"id": cid, "name": cname})
        if len(out) >= limit:
            break
    return out


def _norm(name: str) -> str:
    """Lower-case, strip ™/®/punctuation and collapse whitespace for matching."""
    import re
    n = name.lower().replace("™", "").replace("®", "")
    n = re.sub(r"[^a-z0-9]+", " ", n)
    return " ".join(n.split())


def match_confidence(candidates: list, query: str) -> Tuple[Optional[dict], float]:
    """
    Pick the candidate that best matches *query* and say how sure we are.

    Returns (candidate, score 0–1). A score ≥ CONFIDENT_SCORE means the name
    is (nearly) identical and the UI may pre-select it; anything lower is a
    guess ("Portal" → "Portal 2") and must NOT be auto-confirmed.
    """
    import difflib
    if not candidates:
        return None, 0.0
    q = _norm(query)
    best, best_score = None, -1.0
    for c in candidates:
        cn = _norm(c["name"])
        if cn == q:
            return c, 1.0
        score = difflib.SequenceMatcher(None, q, cn).ratio()
        if score > best_score:
            best, best_score = c, score
    return best, best_score


CONFIDENT_SCORE = 0.92


def _best_match(candidates: list, query: str) -> Optional[dict]:
    best, score = match_confidence(candidates, query)
    return best if score >= CONFIDENT_SCORE else None


# ── Public API ─────────────────────────────────────────────────────────────────

def search_candidates(
    game_name: str,
    limit: int = 10,
    timeout: int = 8,
) -> list:
    """
    Return up to *limit* candidate dicts [{"id": int, "name": str}, …].

    Raises NetworkError for transport/SSL/timeout failures so callers can
    show a real error instead of a silent empty list.
    Returns [] only when Steam genuinely has no matches.
    """
    result = _safe_fetch(game_name, timeout)
    if result.error_code and result.error_code != "no_results":
        raise NetworkError(result.error_message)
    return _clean_candidates(result.candidates, limit)


def search_candidates_safe(
    game_name: str,
    limit: int = 10,
    timeout: int = 8,
) -> SearchResult:
    """
    Like search_candidates() but never raises — returns a SearchResult.
    Use in UI workers that need structured error codes.
    """
    result = _safe_fetch(game_name, timeout)
    if result.ok:
        result.candidates = _clean_candidates(result.candidates, limit)
    return result


def get_app_id(game_name: str, timeout: int = 8) -> Optional[int]:
    """Return best-matching AppID or None on any failure."""
    result = _safe_fetch(game_name, timeout)
    if not result.ok or not result.candidates:
        return None
    cleaned = _clean_candidates(result.candidates, 10)
    best    = _best_match(cleaned, game_name)
    return best["id"] if best else None


def get_app_id_and_name(
    game_name: str, timeout: int = 8,
) -> Tuple[Optional[int], str]:
    """Return (app_id, canonical_name) or (None, game_name) on failure."""
    result = _safe_fetch(game_name, timeout)
    if not result.ok or not result.candidates:
        return None, game_name
    cleaned = _clean_candidates(result.candidates, 10)
    best    = _best_match(cleaned, game_name)
    if best:
        return best["id"], best["name"]
    return None, game_name


__all__ = [
    "match_confidence",
    "CONFIDENT_SCORE",
    "search_candidates",
    "search_candidates_safe",
    "get_app_id",
    "get_app_id_and_name",
    "SearchResult",
    "NetworkError",
]