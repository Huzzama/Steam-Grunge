"""Help → Check for Updates — version comparison and the GitHub answer handling."""
import os, sys, tempfile
os.environ.setdefault("XDG_DATA_HOME", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import json

from app.services.updates import check_latest, compare_versions


def test_compare_versions():
    assert compare_versions("4.1.0", "4.0.0") == 1
    assert compare_versions("v4.0.0", "4.0.0") == 0
    assert compare_versions("4.0.0", "4.0.10") == -1
    assert compare_versions("4.0.0-beta.1", "4.0.0") == -1
    assert compare_versions("5", "4.9.9") == 1
    assert compare_versions("3.9.0", "4.0.0") == -1      # an older tag is never "available"


def test_check_latest_with_fake_github():
    rel = {"tag_name": "v4.1.0", "html_url": "https://github.com/Huzzama/Steam-Grunge/releases/tag/v4.1.0"}
    r = check_latest("4.0.0", opener=lambda url: json.dumps(rel).encode())
    assert r["available"] and r["latest"] == "4.1.0" and r["url"].endswith("v4.1.0") and r["error"] is None
    r = check_latest("4.1.0", opener=lambda url: json.dumps(rel).encode())
    assert not r["available"]
    r = check_latest("9.0.0", opener=lambda url: json.dumps(rel).encode())
    assert not r["available"]

    def boom(url):
        raise OSError("no network")
    r = check_latest("4.0.0", opener=boom)
    assert r["error"] == "no network" and not r["available"]
