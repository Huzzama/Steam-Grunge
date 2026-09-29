"""
Headless screenshot of the editor (window, a panel, or a dialog).

    QT_QPA_PLATFORM=offscreen python3 tools/shot.py window   /tmp/gshots/window.png
    QT_QPA_PLATFORM=offscreen python3 tools/shot.py editor   /tmp/gshots/editor.png   (full scroll content)
    QT_QPA_PLATFORM=offscreen python3 tools/shot.py search   /tmp/gshots/search.png
    QT_QPA_PLATFORM=offscreen python3 tools/shot.py editor-text  ...   (with a text layer selected)
    QT_QPA_PLATFORM=offscreen python3 tools/shot.py editor-image ...   (with an image layer selected)
    QT_QPA_PLATFORM=offscreen python3 tools/shot.py dialog:<name> ...  name = preferences | about | sync | appid | drive

Options: --size 1400x860  --delay 900
The app's own settings/data folder is never touched: it runs against a temp dir.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_cfg = Path(tempfile.gettempdir()) / "grunge_offscreen.json"
_cfg.write_text('{"screens": [{"name": "main", "width": 1920, "height": 1200, "logicalDpi": 96}]}', encoding="utf-8")
os.environ.setdefault("QT_QPA_PLATFORM", f"offscreen:configfile={_cfg.as_posix()}")
os.environ.setdefault("XDG_DATA_HOME", tempfile.mkdtemp(prefix="grunge_shot_"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("out")
    ap.add_argument("--size", default="1400x860")
    ap.add_argument("--delay", type=int, default=900)
    args = ap.parse_args()

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QScrollArea
    app = QApplication(sys.argv)
    from app.ui import theme
    theme.apply(app)
    from app.ui.mainWindow import MainWindow
    w, h = (int(x) for x in args.size.split("x"))
    win = MainWindow()
    win.resize(w, h)
    win.show()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    holder: dict = {}

    def prepare():
        t = args.target
        if t.startswith("editor-"):
            kind = t.split("-", 1)[1]
            ep = win.editor_panel
            fn = {"text": "_add_text_layer", "image": "_add_fill_layer", "paint": "_add_paint_layer"}.get(kind)
            if fn and hasattr(ep, fn):
                getattr(ep, fn)()
        elif t == "search-results":
            sp = win.tab_manager.search_panel
            if hasattr(sp, "debug_fill_results"):
                sp.debug_fill_results()
        elif t.startswith("dialog:"):
            name = t.split(":", 1)[1]
            opener = {"preferences": "_open_preferences", "about": "_show_about", "sync": "_open_sync_dialog",
                      "appid": "_open_appid_registry", "drive": "_open_drive_status", "shortcuts": "_show_shortcuts"}.get(name, name)
            fn = getattr(win, opener, None)
            if fn is None:
                sys.exit(f"unknown dialog {name!r}")
            QTimer.singleShot(0, fn)

    def grab():
        t = args.target
        app.processEvents()
        if t in ("window",) or t.startswith("dialog:"):
            target = app.activeModalWidget() or win
            target.grab().save(str(out))
        elif t == "search":
            win.tab_manager.search_panel.grab().save(str(out))
        elif t.startswith("editor"):
            sa = win.editor_panel.findChild(QScrollArea)
            inner = sa.widget()
            inner.resize(sa.viewport().width(), inner.sizeHint().height())
            app.processEvents()
            inner.grab().save(str(out))
        else:
            win.grab().save(str(out))
        print("saved", out)
        for wdg in app.topLevelWidgets():
            wdg.close()
        app.quit()
        os._exit(0)

    QTimer.singleShot(200, prepare)
    QTimer.singleShot(200 + args.delay, grab)
    app.exec()


if __name__ == "__main__":
    main()
