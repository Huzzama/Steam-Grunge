import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtGui import QFont, QPixmap, QPainter, QColor, QIcon
from PySide6.QtCore import Qt

# ── App icon — icon.png lives in app/assets/ ─────────────────────────────────
# PROJECT_ROOT is already computed above 
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

    # ── Heavy imports  ─────────────────────────────────────────────────────
    from app.ui.mainWindow import MainWindow
    from app.config import FONTS_DIR
    from app.ui.fontImporter import register_all_fonts

    _n = register_all_fonts(FONTS_DIR)
    print(f"[fonts] {_n} font families registered from: {FONTS_DIR}")

    base_font = QFont("Courier New", 12)
    app.setFont(base_font)

    # ── Cyber-Sigil stylesheet ───────────────────────────────────────────────
    app.setStyleSheet("""
        /* ── Base ─────────────────────────────────────────────────────────── */
        QMainWindow, QWidget {
            background-color: #080a0e;
            color: #c8d8e8;
            font-family: 'Courier New', 'Consolas', monospace;
            font-size: 12px;
        }

        /* ── Menu bar ──────────────────────────────────────────────────────── */
        QMenuBar {
            background: #040608;
            color: #607080;
            font-size: 12px;
            padding: 2px 4px;
            border-bottom: 1px solid #0d2030;
            spacing: 2px;
        }
        QMenuBar::item { padding: 3px 10px; border-radius: 2px; }
        QMenuBar::item:selected { background: #0d2030; color: #38bdf8; }
        QMenu {
            background: #080a0e;
            border: 1px solid #0d2030;
            color: #a0b8c8;
            font-size: 12px;
            padding: 4px 0;
        }
        QMenu::item { padding: 5px 24px 5px 14px; }
        QMenu::item:selected { background: #0d1f30; color: #38bdf8; }
        QMenu::separator { height: 1px; background: #0d2030; margin: 3px 8px; }

        /* ── Toolbar ────────────────────────────────────────────────────────── */
        QToolBar {
            background: #040608;
            border-bottom: 1px solid #0d2030;
            spacing: 3px;
            padding: 3px 8px;
        }

        /* ── Status bar ─────────────────────────────────────────────────────── */
        QStatusBar {
            background: #040608;
            color: #304050;
            font-size: 11px;
            font-family: 'Courier New', monospace;
            border-top: 1px solid #0d2030;
            padding: 0px;
        }
        QStatusBar::item { border: none; }

        /* ── Scrollbars ─────────────────────────────────────────────────────── */
        QScrollBar:vertical {
            background: #060810;
            width: 8px;
            border-radius: 0px;
            border-left: 1px solid #0a1520;
        }
        QScrollBar::handle:vertical {
            background: #1a3a50;
            border-radius: 0px;
            min-height: 24px;
        }
        QScrollBar::handle:vertical:hover { background: #38bdf8; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        QScrollBar:horizontal {
            background: #060810;
            height: 8px;
            border-top: 1px solid #0a1520;
        }
        QScrollBar::handle:horizontal {
            background: #1a3a50;
            min-width: 24px;
        }
        QScrollBar::handle:horizontal:hover { background: #38bdf8; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }

        /* ── Buttons ────────────────────────────────────────────────────────── */
        QPushButton {
            background: #060c14;
            color: #607888;
            border: 1px solid #0d2030;
            border-radius: 2px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            padding: 5px 12px;
            min-height: 26px;
        }
        QPushButton:hover {
            background: #0a1a28;
            color: #38bdf8;
            border-color: #38bdf8;
        }
        QPushButton:pressed {
            background: #040e18;
            color: #7dd3fc;
            border-color: #7dd3fc;
            padding: 6px 12px 4px 12px;
        }
        QPushButton:disabled { color: #1a2a3a; border-color: #0a1520; }

        /* ── Line edits ─────────────────────────────────────────────────────── */
        QLineEdit {
            background: #060c14;
            border: 1px solid #0d2030;
            border-radius: 2px;
            color: #90b8c8;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            padding: 4px 8px;
            min-height: 24px;
            selection-background-color: #0d3a52;
        }
        QLineEdit:focus {
            border-color: #38bdf8;
            border-width: 1px;
            background: #05111c;
        }
        QLineEdit:hover {
            border-color: #1a4060;
        }

        /* ── Combo boxes ────────────────────────────────────────────────────── */
        QComboBox {
            background: #060c14;
            border: 1px solid #0d2030;
            border-radius: 2px;
            color: #90b8c8;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            padding: 4px 8px;
            min-height: 24px;
        }
        QComboBox:hover { border-color: #1a4060; }
        QComboBox:focus { border-color: #38bdf8; }
        QComboBox::drop-down {
            border: none;
            width: 20px;
        }
        QComboBox::down-arrow {
            width: 8px; height: 8px;
            border-left: 1px solid #38bdf8;
            border-bottom: 1px solid #38bdf8;
        }
        QComboBox QAbstractItemView {
            background: #060c14;
            border: 1px solid #1a4060;
            color: #90b8c8;
            selection-background-color: #0d2a3e;
            outline: none;
        }

        /* ── Labels ─────────────────────────────────────────────────────────── */
        QLabel { color: #80a0b0; font-size: 12px; }

        /* ── Group boxes ────────────────────────────────────────────────────── */
        QGroupBox {
            border: 1px solid #0d2030;
            border-radius: 2px;
            margin-top: 14px;
            font-family: 'Courier New', monospace;
            font-size: 11px;
            font-weight: bold;
            color: #304a5a;
            letter-spacing: 3px;
            padding-top: 4px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 6px;
            background: #080a0e;
        }

        /* ── Checkboxes ─────────────────────────────────────────────────────── */
        QCheckBox { color: #607888; font-size: 12px; spacing: 8px; }
        QCheckBox::indicator {
            width: 13px; height: 13px;
            border: 1px solid #1a3a50;
            background: #060c14;
            border-radius: 1px;
        }
        QCheckBox::indicator:checked {
            background: #38bdf8;
            border-color: #38bdf8;
            image: none;
        }
        QCheckBox::indicator:hover { border-color: #38bdf8; }

        /* ── Sliders ────────────────────────────────────────────────────────── */
        QSlider::groove:horizontal {
            height: 2px;
            background: #0d2030;
            border-radius: 1px;
        }
        QSlider::handle:horizontal {
            background: #38bdf8;
            border: none;
            width: 12px;
            height: 12px;
            margin: -5px 0;
            border-radius: 1px;
        }
        QSlider::handle:horizontal:hover {
            background: #7dd3fc;
            width: 14px;
            height: 14px;
            margin: -6px 0;
        }
        QSlider::handle:horizontal:pressed { background: #38bdf8; }
        QSlider::sub-page:horizontal { background: #1a4060; height: 2px; }

        /* ── List widgets ───────────────────────────────────────────────────── */
        QListWidget {
            background: #060c14;
            border: 1px solid #0d2030;
            color: #80a0b0;
            font-size: 12px;
            outline: none;
        }
        QListWidget::item { padding: 4px 8px; }
        QListWidget::item:selected {
            background: #0d2030;
            color: #38bdf8;
        }
        QListWidget::item:hover {
            background: #090f18;
            color: #a0c8d8;
            padding-left: 10px;
        }

        /* ── Splitter ───────────────────────────────────────────────────────── */
        QSplitter::handle {
            background: #0d2030;
            width: 1px;
            height: 1px;
        }

        /* ── Tooltips ───────────────────────────────────────────────────────── */
        QToolTip {
            background: #060c14;
            color: #38bdf8;
            border: 1px solid #1a4060;
            font-size: 11px;
            font-family: 'Courier New', monospace;
            padding: 4px 8px;
        }

        /* ── Dialogs ────────────────────────────────────────────────────────── */
        QDialog {
            background: #080a0e;
            color: #c8d8e8;
        }

        /* ── Tab widget ─────────────────────────────────────────────────────── */
        QTabWidget::pane {
            border: 1px solid #0d2030;
            background: #080a0e;
        }
        QTabBar::tab {
            background: #040608;
            color: #304a5a;
            border: 1px solid #0a1520;
            border-bottom: none;
            padding: 5px 16px;
            font-family: 'Courier New', monospace;
            font-size: 11px;
            letter-spacing: 1px;
            min-width: 80px;
        }
        QTabBar::tab:selected {
            background: #080a0e;
            color: #38bdf8;
            border-color: #0d2030;
            border-bottom: 1px solid #080a0e;
        }
        QTabBar::tab:hover:!selected { color: #607888; background: #060810; }

        /* ── Progress bar ───────────────────────────────────────────────────── */
        QProgressBar {
            background: #060c14;
            border: 1px solid #0d2030;
            border-radius: 1px;
            height: 6px;
            text-align: center;
            color: transparent;
        }
        QProgressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #0d3a52, stop:1 #38bdf8);
            border-radius: 1px;
        }

        /* ── Frame separators ───────────────────────────────────────────────── */
        QFrame[frameShape="4"] { color: #0d2030; }
        QFrame[frameShape="5"] { color: #0d2030; }

        /* ── Spin box ───────────────────────────────────────────────────────── */
        QSpinBox, QDoubleSpinBox {
            background: #060c14;
            border: 1px solid #0d2030;
            color: #90b8c8;
            font-family: 'Courier New', monospace;
            padding: 3px 6px;
            border-radius: 2px;
        }
        QSpinBox:focus, QDoubleSpinBox:focus { border-color: #38bdf8; }
        QSpinBox::up-button, QSpinBox::down-button,
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
            background: #0d2030;
            border: none;
            width: 16px;
        }
    """)

    window = MainWindow()

    # Also set icon on the window itself (covers taskbar on some platforms)
    if os.path.exists(_LOGO_PATH):
        window.setWindowIcon(QIcon(_LOGO_PATH)) 

    window.show()
    splash.finish(window)

    # ── Auto-sync on startup (background — never delays launch) ──────────────
    def _auto_sync_startup():
        try:
            from app.services.drive_sync import is_configured, is_authenticated, download_all
            import threading
            if is_configured() and is_authenticated():
                def _dl():
                    r = download_all()
                    if r["downloaded"] > 0:
                        print(f"[Drive] Auto-synced {r['downloaded']} files on startup")
                threading.Thread(target=_dl, daemon=True).start()
        except Exception as e:
            print(f"[Drive] Startup sync skipped: {e}")

    from PySide6.QtCore import QTimer
    QTimer.singleShot(2000, _auto_sync_startup)

    # ── Auto-upload on exit ───────────────────────────────────────────────────
    def _auto_sync_exit():
        try:
            from app.services.drive_sync import is_configured, is_authenticated, upload_all
            if is_configured() and is_authenticated():
                print("[Drive] Uploading on exit…")
                upload_all()
        except Exception as e:
            print(f"[Drive] Exit sync skipped: {e}")

    app.aboutToQuit.connect(_auto_sync_exit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()