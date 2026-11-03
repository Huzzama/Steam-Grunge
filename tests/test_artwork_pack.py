"""Export / import of Steam artwork as a file (USB) — run with `pytest tests/`."""
import os, sys, tempfile
os.environ.setdefault("XDG_DATA_HOME", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import zipfile
from pathlib import Path

import pytest

from app.services import artwork_pack as ap
from app.services import steamSync


@pytest.fixture
def steam(monkeypatch):
    """A fake Steam install with one account, a grid and a librarycache."""
    root = Path(tempfile.mkdtemp())
    userdata = root / "userdata"
    grid = userdata / "42" / "config" / "grid"
    grid.mkdir(parents=True)
    (grid / "123p.png").write_bytes(b"PORTRAIT")
    (grid / "123_hero.png").write_bytes(b"HERO")
    cache = root / "appcache" / "librarycache"
    (cache / "123").mkdir(parents=True)
    (cache / "123" / "library_600x900.jpg").write_bytes(b"CACHE-PORTRAIT")
    (cache / "assets.vdf").write_bytes(b"VDF")
    monkeypatch.setattr(steamSync, "find_steam_userdata", lambda: userdata)
    return root, grid, cache


def test_export_then_import_round_trip(steam, tmp_path):
    root, grid, cache = steam
    dest = tmp_path / "usb" / ap.default_pack_name("42")
    r = ap.export_pack("42", dest)
    assert r["ok"], r
    assert r["files"] == 4
    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
    assert names == {ap.PACK_META, "grid/123p.png", "grid/123_hero.png",
                     "librarycache/123/library_600x900.jpg", "librarycache/assets.vdf"}

    # Wipe Steam, import the pack: both folders come back.
    for p in (grid / "123p.png", grid / "123_hero.png", cache / "123" / "library_600x900.jpg"):
        p.unlink()
    r = ap.import_pack(dest, "42")
    assert r["ok"], r
    assert r["grid"] == 2 and r["librarycache"] == 2
    assert (grid / "123p.png").read_bytes() == b"PORTRAIT"
    assert (cache / "123" / "library_600x900.jpg").read_bytes() == b"CACHE-PORTRAIT"


def test_export_grid_only(steam, tmp_path):
    dest = tmp_path / "p.zip"
    r = ap.export_pack("42", dest, include_cache=False)
    assert r["ok"] and r["files"] == 2
    with zipfile.ZipFile(dest) as zf:
        assert all(n == ap.PACK_META or n.startswith("grid/") for n in zf.namelist())


def test_import_drive_backup_zip_goes_to_grid(steam, tmp_path):
    root, grid, cache = steam
    z = tmp_path / "steam-grid-42.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("999p.png", b"FROM-DRIVE")
        zf.writestr("../../evil.png", b"NOPE")        # zip-slip: skipped
    r = ap.import_pack(z, "42")
    assert r["ok"], r
    assert r["grid"] == 1 and r["librarycache"] == 0 and r["skipped"] == 1
    assert (grid / "999p.png").read_bytes() == b"FROM-DRIVE"
    assert not (root / "evil.png").exists()


def test_import_bare_folders(steam, tmp_path):
    root, grid, cache = steam
    # A copied grid folder (recognised by its file names) …
    g = tmp_path / "my-covers"
    g.mkdir()
    (g / "777p.png").write_bytes(b"G")
    assert ap.classify_folder(g) == {"grid": g}
    # … a copied librarycache (per-app numeric folders) …
    c = tmp_path / "librarycache"
    (c / "777").mkdir(parents=True)
    (c / "777" / "x.jpg").write_bytes(b"C")
    assert ap.classify_folder(c) == {"librarycache": c}
    # … and a folder holding both.
    both = tmp_path / "both"
    (both / "grid").mkdir(parents=True)
    (both / "grid" / "888p.png").write_bytes(b"G2")
    (both / "librarycache" / "888").mkdir(parents=True)
    (both / "librarycache" / "888" / "y.jpg").write_bytes(b"C2")
    assert set(ap.classify_folder(both)) == {"grid", "librarycache"}

    assert ap.import_pack(g, "42")["grid"] == 1
    assert ap.import_pack(c, "42")["librarycache"] == 1
    r = ap.import_pack(both, "42")
    assert r["grid"] == 1 and r["librarycache"] == 1
    assert (grid / "888p.png").exists() and (cache / "888" / "y.jpg").exists()

    assert not ap.classify_folder(tmp_path / "nothing-here")
    assert ap.import_pack(tmp_path / "missing", "42")["ok"] is False


def test_folder_stats(steam):
    root, grid, cache = steam
    assert ap.folder_stats(grid) == (2, len(b"PORTRAIT") + len(b"HERO"))
    assert ap.folder_stats(root / "nope") == (0, 0)
