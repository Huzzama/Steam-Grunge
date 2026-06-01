"""
Google Drive sync panel for Steam Grunge Editor — PySide6 version.

Drop into any QWidget-based settings/preferences dialog:

    from app.ui.drive_sync_panel import DriveSyncPanel
    panel = DriveSyncPanel()
    your_layout.addWidget(panel)
"""
import threading
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QFont, QColor


# ── Shared stylesheet tokens ───────────────────────────────────────────────────
_BG      = "#0f0f0f"
_CARD    = "#161616"
_BORDER  = "#2a2a2a"
_BLUE    = "#60a5fa"
_GREEN   = "#4ade80"
_GOLD    = "#fbbf24"
_RED     = "#f87171"
_TEXT    = "#e2e8f0"
_DIM     = "#71717a"
_MONO    = "'Courier New', monospace"

_BTN = """
QPushButton {{
    background: {bg};
    color: {fg};
    border: 1px solid {border};
    border-radius: 3px;
    font-family: {font};
    font-size: 12px;
    padding: 5px 14px;
    min-height: 28px;
}}
QPushButton:hover  {{ background: {hover}; border-color: {hborder}; }}
QPushButton:disabled {{ color: #444; border-color: #222; background: #111; }}
"""

def _primary_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setStyleSheet(_BTN.format(
        bg="#1a3a5a", fg=_BLUE, border="#2a4a7a",
        hover="#1e4a72", hborder=_BLUE, font=_MONO,
    ))
    return btn

def _ghost_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setStyleSheet(_BTN.format(
        bg="transparent", fg=_DIM, border=_BORDER,
        hover="#1e1e1e", hborder="#555", font=_MONO,
    ))
    return btn

def _danger_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setStyleSheet(_BTN.format(
        bg="transparent", fg=_RED, border="#4a1515",
        hover="#2a0a0a", hborder=_RED, font=_MONO,
    ))
    return btn

def _hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color: {_BORDER};")
    return f

def _label(text: str, color: str = _DIM, size: int = 11,
           bold: bool = False, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    w   = "bold" if bold else "normal"
    lbl.setStyleSheet(
        f"color: {color}; font-size: {size}px; font-weight: {w}; "
        f"font-family: {_MONO};"
    )
    if wrap:
        lbl.setWordWrap(True)
    return lbl


# ── Worker signals (cross-thread UI updates) ───────────────────────────────────
class _Signals(QObject):
    progress = Signal(str)
    done     = Signal(bool, str)   # success, message


# ── Panel ──────────────────────────────────────────────────────────────────────
class DriveSyncPanel(QWidget):
    """
    Self-contained Google Drive sync widget.
    Handles auth, upload, download, and status.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy    = False
        self._signals = _Signals()
        self._signals.progress.connect(self._on_progress)
        self._signals.done.connect(self._on_done)
        self._build()
        # Refresh status after a short delay so Drive libs have time to import
        QTimer.singleShot(200, self._refresh_status)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self):
        self.setStyleSheet(f"background: {_CARD}; border-radius: 4px;")
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # Section title
        title_row = QHBoxLayout()
        title_row.addWidget(_label("Google Drive Sync", _TEXT, 13, bold=True))
        title_row.addStretch()
        self._dot = _label("●", _DIM, 11)
        title_row.addWidget(self._dot)
        root.addLayout(title_row)

        root.addWidget(_hline())

        # Description
        root.addWidget(_label(
            "Back up your exported artwork and project files to your "
            "personal Google Drive.  Your data never passes through any server.",
            wrap=True,
        ))

        # Status label
        self._status_lbl = _label("Checking…", _DIM)
        root.addWidget(self._status_lbl)

        root.addWidget(_hline())

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._connect_btn = _primary_btn("Connect Google Drive")
        self._connect_btn.clicked.connect(self._connect)
        btn_row.addWidget(self._connect_btn)

        self._upload_btn = _ghost_btn("⬆  Upload")
        self._upload_btn.clicked.connect(self._upload)
        self._upload_btn.setEnabled(False)
        btn_row.addWidget(self._upload_btn)

        self._download_btn = _ghost_btn("⬇  Download")
        self._download_btn.clicked.connect(self._download)
        self._download_btn.setEnabled(False)
        btn_row.addWidget(self._download_btn)

        btn_row.addStretch()
        root.addLayout(btn_row)

        # Progress / feedback
        self._progress_lbl = _label("", _DIM, 11)
        root.addWidget(self._progress_lbl)

        # Privacy note
        root.addWidget(_label(
            "Files are stored in 'Steam Grunge Editor' in your own Google Drive.",
            _DIM, 10,
        ))

    # ── Status ─────────────────────────────────────────────────────────────────

    def _refresh_status(self):
        try:
            from app.services.drive_sync import get_status
            s = get_status()

            if not s["configured"]:
                self._set_status(
                    "client_secret.json not found in project root.", _GOLD)
                self._dot.setStyleSheet(f"color:{_GOLD}; font-size:11px;")
                self._connect_btn.setEnabled(False)
                self._upload_btn.setEnabled(False)
                self._download_btn.setEnabled(False)

            elif s["authenticated"]:
                self._set_status("✓  Connected to Google Drive", _GREEN)
                self._dot.setStyleSheet(f"color:{_GREEN}; font-size:11px;")
                # Switch to Disconnect
                self._connect_btn.setText("Disconnect")
                self._connect_btn.setStyleSheet(_BTN.format(
                    bg="transparent", fg=_RED, border="#4a1515",
                    hover="#2a0a0a", hborder=_RED, font=_MONO,
                ))
                try:
                    self._connect_btn.clicked.disconnect()
                except RuntimeError:
                    pass
                self._connect_btn.clicked.connect(self._disconnect)
                self._connect_btn.setEnabled(True)
                self._upload_btn.setEnabled(True)
                self._download_btn.setEnabled(True)

            else:
                self._set_status("Not connected — click Connect to authenticate.", _DIM)
                self._dot.setStyleSheet(f"color:{_DIM}; font-size:11px;")
                self._connect_btn.setText("Connect Google Drive")
                self._connect_btn.setStyleSheet(_BTN.format(
                    bg="#1a3a5a", fg=_BLUE, border="#2a4a7a",
                    hover="#1e4a72", hborder=_BLUE, font=_MONO,
                ))
                try:
                    self._connect_btn.clicked.disconnect()
                except RuntimeError:
                    pass
                self._connect_btn.clicked.connect(self._connect)
                self._connect_btn.setEnabled(True)
                self._upload_btn.setEnabled(False)
                self._download_btn.setEnabled(False)

        except ImportError:
            self._set_status(
                "Install: google-auth google-auth-oauthlib google-api-python-client",
                _RED,
            )

    def _set_status(self, msg: str, color: str = _DIM):
        self._status_lbl.setText(msg)
        self._status_lbl.setStyleSheet(
            f"color: {color}; font-size: 11px; font-family: {_MONO};"
        )

    def _set_progress(self, msg: str, color: str = _DIM):
        self._progress_lbl.setText(msg)
        self._progress_lbl.setStyleSheet(
            f"color: {color}; font-size: 11px; font-family: {_MONO};"
        )

    # ── Actions ────────────────────────────────────────────────────────────────

    def _connect(self):
        from app.services.drive_sync import is_configured, authenticate
        if not is_configured():
            self._set_progress(
                "Place client_secret.json in the project root first.", _GOLD)
            return

        self._connect_btn.setEnabled(False)
        self._set_progress("Opening browser for Google authentication…", _BLUE)

        def _done(ok: bool, msg: str):
            self._signals.done.emit(ok, msg)

        authenticate(on_done=_done)

    def _disconnect(self):
        from app.services.drive_sync import disconnect
        disconnect()
        self._set_progress("")
        self._refresh_status()

    def _upload(self):
        if self._busy:
            return
        self._busy = True
        self._set_busy_ui(True)

        def _work():
            from app.services.drive_sync import upload_all

            def _prog(msg):
                self._signals.progress.emit(msg)

            try:
                r      = upload_all(on_progress=_prog)
                n      = r["uploaded"]
                errors = r["errors"]
                if errors:
                    self._signals.done.emit(False, f"Error: {errors[0]}")
                else:
                    self._signals.done.emit(
                        True,
                        f"✓  {n} file{'s' if n != 1 else ''} uploaded to Drive",
                    )
            except Exception as e:
                self._signals.done.emit(False, f"Error: {e}")

        threading.Thread(target=_work, daemon=True).start()

    def _download(self):
        if self._busy:
            return
        self._busy = True
        self._set_busy_ui(True)

        def _work():
            from app.services.drive_sync import download_all

            def _prog(msg):
                self._signals.progress.emit(msg)

            try:
                r      = download_all(on_progress=_prog)
                n      = r["downloaded"]
                errors = r["errors"]
                if errors:
                    self._signals.done.emit(False, f"Error: {errors[0]}")
                else:
                    self._signals.done.emit(
                        True,
                        f"✓  {n} file{'s' if n != 1 else ''} downloaded",
                    )
            except Exception as e:
                self._signals.done.emit(False, f"Error: {e}")

        threading.Thread(target=_work, daemon=True).start()

    def _set_busy_ui(self, busy: bool):
        self._upload_btn.setEnabled(not busy)
        self._download_btn.setEnabled(not busy)

    # ── Signals ────────────────────────────────────────────────────────────────

    def _on_progress(self, msg: str):
        self._set_progress(msg, _BLUE)

    def _on_done(self, ok: bool, msg: str):
        self._busy = False
        color = _GREEN if ok else _RED
        self._set_progress(msg, color)
        self._refresh_status()
        # Clear message after 5s
        QTimer.singleShot(5000, lambda: self._set_progress(""))
