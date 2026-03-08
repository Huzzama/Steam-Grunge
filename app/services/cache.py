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


def cache_size_mb() -> float:
    total = 0
    for f in os.listdir(CACHE_FOLDER):
        fp = os.path.join(CACHE_FOLDER, f)
        if os.path.isfile(fp):
            total += os.path.getsize(fp)
    return total / (1024 * 1024)