"""Ported from the session scratch tests — run with `pytest tests/`."""
import os, sys, tempfile
os.environ.setdefault("XDG_DATA_HOME", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_module():
    import os, sys, io, tempfile, zipfile
    from pathlib import Path

    from app.services import drive_sync as ds
    from app.services import steamSync

    # ── fake Steam install ────────────────────────────────────────────────────────
    root = Path(tempfile.mkdtemp())
    userdata = root / "userdata"
    grid = userdata / "42" / "config" / "grid"
    grid.mkdir(parents=True)
    (grid / "123p.png").write_bytes(b"PORTRAIT")
    (grid / "123.png").write_bytes(b"WIDE")
    (grid / "123_hero.png").write_bytes(b"HERO")
    (grid / "sub").mkdir(); (grid / "sub" / "x.png").write_bytes(b"NESTED")
    steamSync.find_steam_userdata = lambda: userdata

    # ── fake Drive service ────────────────────────────────────────────────────────
    class _Exec:
        def __init__(self, v): self.v = v
        def execute(self): return self.v

    class FakeFiles:
        def __init__(self): self.store = {}; self.n = 0     # id → {name, parents, data}
        def list(self, q="", fields=""):
            out = []
            for fid, f in self.store.items():
                name_ok = (f"name='{f['name']}'" in q) if "name='" in q else True
                parent_ok = (f"'{f['parents'][0]}' in parents" in q) if "in parents" in q else True
                folder = f["mime"] == "application/vnd.google-apps.folder"
                if "mimeType='application/vnd.google-apps.folder'" in q and not folder: continue
                if "mimeType!='application/vnd.google-apps.folder'" in q and folder: continue
                if name_ok and parent_ok:
                    out.append({"id": fid, "name": f["name"], "size": str(len(f["data"])),
                                "modifiedTime": "2026-09-19T10:00:00.000Z"})
            return _Exec({"files": out})
        def create(self, body, media_body=None, fields=""):
            self.n += 1; fid = f"id{self.n}"
            data = media_body._fd.read() if media_body else b""
            self.store[fid] = {"name": body["name"], "parents": body.get("parents", ["root"]),
                               "mime": body.get("mimeType", "application/zip"), "data": data}
            return _Exec({"id": fid})
        def update(self, fileId, media_body):
            self.store[fileId]["data"] = media_body._fd.read(); return _Exec({})
        def get_media(self, fileId): return ("MEDIA", self.store[fileId]["data"])

    class FakeSvc:
        def __init__(self): self._f = FakeFiles()
        def files(self): return self._f

    svc = FakeSvc()
    ds._service = lambda: svc

    class FakeUpload:
        def __init__(self, fd, mimetype, resumable, chunksize): self._fd = fd
    class FakeDownload:
        def __init__(self, buf, req): buf.write(req[1]); self.done = False
        def next_chunk(self): return None, True
    import googleapiclient.http as gh
    gh.MediaIoBaseUpload = FakeUpload
    gh.MediaIoBaseDownload = FakeDownload

    # ── backup ────────────────────────────────────────────────────────────────────
    msgs = []
    r = ds.backup_grid("42", on_progress=msgs.append)
    assert r["ok"] and r["files"] == 4, r
    zips = [f for f in svc._f.store.values() if f["name"] == "steam-grid-42.zip"]
    assert len(zips) == 1
    names = sorted(zipfile.ZipFile(io.BytesIO(zips[0]["data"])).namelist())
    assert names == ["123.png", "123_hero.png", "123p.png", "sub/x.png"], names

    # second backup replaces, does not duplicate
    (grid / "999p.png").write_bytes(b"NEW")
    r = ds.backup_grid("42")
    assert r["ok"] and r["files"] == 5
    assert len([f for f in svc._f.store.values() if f["name"] == "steam-grid-42.zip"]) == 1

    # list
    b = ds.list_backups()
    assert len(b) == 1 and b[0]["steam_id"] == "42" and b[0]["size"] > 0, b

    # ── restore into a wiped grid ─────────────────────────────────────────────────
    import shutil; shutil.rmtree(grid); grid.mkdir()
    (grid / "123p.png").write_bytes(b"STALE")
    r = ds.restore_grid("42", on_progress=msgs.append)
    assert r["ok"] and r["files"] == 5, r
    assert (grid / "123p.png").read_bytes() == b"PORTRAIT"
    assert (grid / "sub" / "x.png").read_bytes() == b"NESTED"

    # restore for unknown account → clean error
    r = ds.restore_grid("777")
    assert not r["ok"] and "No backup" in r["error"], r

    # ── zip-slip guard ────────────────────────────────────────────────────────────
    evil = io.BytesIO()
    with zipfile.ZipFile(evil, "w") as z: z.writestr("../../evil.txt", b"x"); z.writestr("ok.png", b"y")
    fid = [k for k, f in svc._f.store.items() if f["name"] == "steam-grid-42.zip"][0]
    svc._f.store[fid]["data"] = evil.getvalue()
    r = ds.restore_grid("42")
    assert r["ok"] and r["files"] == 1 and not (userdata / "42" / "evil.txt").exists() \
        and not (root / "evil.txt").exists(), r

    # ── is_steam_running must not detect ourselves ────────────────────────────────
    assert steamSync.is_steam_running() is False

    print("ALL BACKUP TESTS PASSED", msgs[:2])
