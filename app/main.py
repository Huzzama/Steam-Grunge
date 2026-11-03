import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtGui import QFont, QPixmap, QPainter, QColor, QIcon
from PySide6.QtCore import Qt

# ── App icon — icon.png lives in app/assets/ ─────────────────────────────────
# config.ASSETS_DIR resolves both from source and inside PyInstaller bundles
# (where this file is not next to the assets folder).
from app.config import ASSETS_DIR  # noqa: E402  (after the sys.path fix above)
_LOGO_PATH = str(ASSETS_DIR / "icon.png")


def _app_version() -> str:
    from pathlib import Path
    try:
        return (Path(ASSETS_DIR).parent.parent / "VERSION").read_text().strip()
    except OSError:
        return "0.0.0"


def _make_splash_pixmap() -> QPixmap:
    """Draw a minimal splash screen.
    Uses app/assets/icon.png if present, otherwise draws text-only fallback."""
    w, h = 480, 220
    pix = QPixmap(w, h)
    pix.fill(QColor("#0e0e0e"))

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    # Border
    p.setPen(QColor("#2a2a2a"))
    p.drawRect(0, 0, w - 1, h - 1)

    if os.path.exists(_LOGO_PATH):
        # Show logo centred in the top portion
        logo = QPixmap(_LOGO_PATH)
        logo_h = 100
        logo_scaled = logo.scaledToHeight(logo_h, Qt.SmoothTransformation)
        lx = (w - logo_scaled.width()) // 2
        p.drawPixmap(lx, 16, logo_scaled)
        text_y_offset = logo_h + 24
    else:
        # Fallback title text
        title_font = QFont("Courier New", 22, QFont.Bold)
        p.setFont(title_font)
        p.setPen(QColor("#3a7a3a"))
        p.drawText(0, 0, w, h // 2 + 10, Qt.AlignCenter, "✦ STEAM GRUNGE EDITOR")
        text_y_offset = h // 2 + 10

    # Loading subtitle
    sub_font = QFont("Courier New", 11)
    p.setFont(sub_font)
    p.setPen(QColor("#444"))
    p.drawText(0, text_y_offset, w, 30, Qt.AlignCenter, "Loading…")

    p.end()
    return pix


def _self_test() -> int:
    """`--self-test`: build the whole UI offscreen and check the bundled assets.
    Used by the release pipeline to prove a frozen build actually starts."""
    from pathlib import Path
    app = QApplication.instance() or QApplication(sys.argv)
    problems = []
    for sub in ("icon.png", "fonts", "textures", "templates"):
        p = Path(ASSETS_DIR) / sub
        if not p.exists() or (p.is_dir() and not any(p.iterdir())):
            problems.append(f"missing asset: {p}")
    from app.ui.mainWindow import MainWindow
    from app.ui import theme
    theme.apply(app)
    window = MainWindow()
    window.show()
    app.processEvents()
    window.close()
    msg = ("SELF-TEST FAILED\n  " + "\n  ".join(problems)) if problems \
        else f"SELF-TEST OK — Steam Grunge Editor {_app_version()}"
    print(msg)
    # Windowed builds (Windows .exe, macOS .app) have no console: CI reads this file.
    if os.environ.get("SGE_SELFTEST_LOG"):
        with open(os.environ["SGE_SELFTEST_LOG"], "w", encoding="utf-8") as f:
            f.write(msg + "\n")
    return 1 if problems else 0


def main():
    if "--version" in sys.argv:
        print(_app_version())
        sys.exit(0)
    if "--self-test" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.exit(_self_test())
    app = QApplication(sys.argv)
    app.setApplicationName("Steam Grunge Editor")
    app.setOrganizationName("GrungeStudio")

    # ── App icon (window chrome, taskbar, dock) ───────────────────────────────
    print(f"[icon] looking for icon at: {_LOGO_PATH}")
    if os.path.exists(_LOGO_PATH):
        icon = QIcon(_LOGO_PATH)
        app.setWindowIcon(icon)
        print("[icon] icon loaded OK")
    else:
        print("[icon] WARNING — icon.png not found, skipping")

    # ── Show splash immediately so there's no blank-window flash ─────────────
    splash = QSplashScreen(_make_splash_pixmap(), Qt.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()

    # ── Heavy imports  ─────────────────────────────────────────────────────
    from app.ui.mainWindow import MainWindow
    from app.config import font_dirs
    from app.ui.fontImporter import register_all_fonts

    _n = sum(register_all_fonts(d) for d in font_dirs())
    print(f"[fonts] {_n} font families registered from: {font_dirs()}")

    from app.ui import theme
    theme.apply(app)          # palette, Courier New, global stylesheet

    window = MainWindow()

    # Also set icon on the window itself (covers taskbar on some platforms)
    if os.path.exists(_LOGO_PATH):
        window.setWindowIcon(QIcon(_LOGO_PATH)) 

    window.show()
    splash.finish(window)

    # Drive backup/restore is an explicit user action (Backup menu) —
    # nothing is downloaded on startup or uploaded on exit.
    sys.exit(app.exec())


if __name__ == "__main__":
    main()