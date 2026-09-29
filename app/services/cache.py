import os
import hashlib
from app.config import CACHE_FOLDER


def get_cache_path(url: str) -> str:
    """Generate a deterministic local filepath for a given URL."""
    ext = url.split(".")[-1].split("?")[0]
    if ext not in ("jpg", "jpeg", "png", "webp"):
        ext = "png"
    name = hashlib.md5(url.encode()).hexdigest()
    return os.path.join(CACHE_FOLDER, f"{name}.{ext}")


def is_cached(url: str) -> bool:
    return os.path.exists(get_cache_path(url))


def clear_cache():
    for f in os.listdir(CACHE_FOLDER):
        fp = os.path.join(CACHE_FOLDER, f)
        if os.path.isfile(fp):
            os.remove(fp)


CACHE_MAX_MB = 200   # thumbnails + full-res downloads are re-fetched on demand


def prune_cache(max_mb: float = CACHE_MAX_MB):
    """
    Keep the cache folder under *max_mb* by deleting the least recently used
    files first (by mtime). Never raises.
    """
    try:
        files = []
        for f in os.listdir(CACHE_FOLDER):
            fp = os.path.join(CACHE_FOLDER, f)
            if os.path.isfile(fp):
                st = os.stat(fp)
                files.append((st.st_mtime, st.st_size, fp))
        total = sum(size for _, size, _ in files)
        limit = max_mb * 1024 * 1024
        if total <= limit:
            return
        files.sort()   # oldest first
        for _, size, fp in files:
            try:
                os.remove(fp)
                total -= size
            except OSError:
                continue
            if total <= limit:
                break
    except Exception:
        pass


def cache_size_mb() -> float:
    total = 0
    for f in os.listdir(CACHE_FOLDER):
        fp = os.path.join(CACHE_FOLDER, f)
        if os.path.isfile(fp):
            total += os.path.getsize(fp)
    return total / (1024 * 1024)