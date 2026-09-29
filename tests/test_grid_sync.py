"""Ported from the session scratch tests — run with `pytest tests/`."""
import os, sys, tempfile
os.environ.setdefault("XDG_DATA_HOME", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_module():
    from pathlib import Path

    from PIL import Image
    from app.config import grid_filename, GRID_FILENAMES
    from app.services import steamSync
    from app.services import cache
    from app.config import CACHE_FOLDER

    # 1. naming: cover = portrait = p.png, wide = plain
    assert grid_filename(123, "cover")        == "123p.png"
    assert grid_filename(123, "vhs_cover")    == "123p.png"
    assert grid_filename(123, "wide")         == "123.png"
    assert grid_filename(123, "vhs_pile")     == "123.png"
    assert grid_filename(123, "vhs_cassette") == "123.png"
    assert grid_filename(123, "hero")         == "123_hero.png"
    assert grid_filename(123, "logo")         == "123_logo.png"
    assert grid_filename(123, "icon")         == "123_icon.png"
    assert steamSync._grid_filename(123, "cover") == "123p.png"

    # 3. sync_artwork writes only to grid, never into librarycache
    root = Path(tempfile.mkdtemp())
    userdata = root / "userdata"; (userdata / "42" / "config").mkdir(parents=True)
    lc = root / "appcache" / "librarycache" / "123"; lc.mkdir(parents=True)
    (lc / "library_600x900.jpg").write_bytes(b"STEAM-OWNED")
    src = root / "cover.png"; Image.new("RGB", (600, 900), "red").save(src)
    src_w = root / "wide.png"; Image.new("RGB", (920, 430), "blue").save(src_w)

    r = steamSync.sync_artwork(123, "42", userdata, {"cover": str(src), "wide": str(src_w), "hero": ""},
                               post_sync="none")
    grid = userdata / "42" / "config" / "grid"
    assert r.success and r.summary.outcome == "success", r
    assert sorted(p.name for p in grid.iterdir()) == ["123.png", "123p.png"], list(grid.iterdir())
    assert Image.open(grid / "123p.png").size == (600, 900)
    assert Image.open(grid / "123.png").size == (920, 430)
    assert (lc / "library_600x900.jpg").read_bytes() == b"STEAM-OWNED"   # untouched
    assert r.skipped == ["hero"]

    # 4. cache prune keeps newest, drops oldest
    os.makedirs(CACHE_FOLDER, exist_ok=True)
    for i in range(5):
        p = os.path.join(CACHE_FOLDER, f"f{i}.png")
        with open(p, "wb") as f: f.write(b"x" * 1024 * 1024)   # 1 MB each
        os.utime(p, (i, i))
    cache.prune_cache(max_mb=2)
    left = sorted(os.listdir(CACHE_FOLDER))
    assert left == ["f3.png", "f4.png"], left

    print("ALL TESTS PASSED")
