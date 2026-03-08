import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtGui import QFont, QPixmap, QPainter, QColor, QIcon
from PySide6.QtCore import Qt

# ── App icon — icon.png lives in app/assets/ ─────────────────────────────────
# PROJECT_ROOT is already computed above (two levels up from this file)
_LOGO_PATH = os.path.join(PROJECT_ROOT, "app", "assets", "icon.png")


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


def main():
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

    # ── Heavy imports (happen after splash is visible) ────────────────────────
    from app.ui.mainWindow import MainWindow
    from app.config import FONTS_DIR
    from app.ui.fontImporter import register_all_fonts

    _n = register_all_fonts(FONTS_DIR)
    print(f"[fonts] {_n} font families registered from: {FONTS_DIR}")

    base_font = QFont("Courier New", 12)
    app.setFont(base_font)

    app.setStyleSheet("""
        QMainWindow, QWidget {
            background-color: #1a1a1a;
            color: #e0e0e0;
            font-family: 'Courier New', monospace;
            font-size: 13px;
        }
        QMenuBar {
            background: #111;
            color: #aaa;
            font-size: 13px;
            padding: 2px 4px;
        }
        QMenuBar::item:selected { background: #2a2a4a; }
        QMenu {
            background: #1a1a1a;
            border: 1px solid #333;
            color: #ccc;
            font-size: 13px;
        }
        QMenu::item:selected { background: #2a2a4a; }
        QStatusBar {
            background: #111;
            color: #666;
            font-size: 12px;
            padding: 2px 8px;
        }
        QScrollBar:vertical {
            background: #2a2a2a;
            width: 10px;
            border-radius: 5px;
        }
        QScrollBar::handle:vertical {
            background: #555;
            border-radius: 5px;
            min-height: 20px;
        }
        QScrollBar:horizontal {
            background: #2a2a2a;
            height: 10px;
            border-radius: 5px;
        }
        QScrollBar::handle:horizontal {
            background: #555;
            border-radius: 5px;
        }
        QToolTip {
            background: #222;
            color: #ddd;
            border: 1px solid #444;
            font-size: 12px;
        }
        QPushButton {
            font-size: 12px;
            padding: 5px 10px;
        }
        QComboBox {
            font-size: 12px;
            padding: 4px 8px;
            min-height: 26px;
        }
        QLineEdit {
            font-size: 12px;
            padding: 4px 8px;
            min-height: 26px;
        }
        QGroupBox {
            font-size: 11px;
            margin-top: 10px;
        }
        QLabel {
            font-size: 12px;
        }
        QCheckBox {
            font-size: 12px;
        }
        QListWidget {
            font-size: 12px;
        }
        QSlider::groove:horizontal {
            height: 4px;
            background: #333;
            border-radius: 2px;
        }
        QSlider::handle:horizontal {
            background: #667;
            border: 1px solid #888;
            width: 14px;
            height: 14px;
            margin: -5px 0;
            border-radius: 7px;
        }
    """)

    window = MainWindow()

    # Also set icon on the window itself (covers taskbar on some platforms)
    if os.path.exists(_LOGO_PATH):
        window.setWindowIcon(QIcon(_LOGO_PATH))  # re-set on window for Linux/Windows taskbar

    window.show()
    splash.finish(window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()