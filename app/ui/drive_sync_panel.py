"""
SteamKustom Drive Sync panel for Steam Grunge Editor — PySide6.
Token-only auth: no client_secret.json needed.
"""
import threading
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QFrame,
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer

_BLUE  = "#60a5fa"
_GREEN = "#4ade80"
_GOLD  = "#fbbf24"
_RED   = "#f87171"
_TEXT  = "#e2e8f0"
_DIM   = "#71717a"
_CARD  = "#161616"
_MONO  = "'Courier New', monospace"

_BTN = """
QPushButton {{
    background: {bg};
    color: {fg};
    border: 1px solid {border};
    border-radius: 2px;
    font-family: {font};
    font-size: 12px;
    padding: 5px 14px;
    min-height: 28px;
}}
QPushButton:hover  {{ background: {hover}; border-color: {hb}; }}
QPushButton:disabled {{ color: #333; border-color: #1a1a1a; background: #111; }}
"""

def _primary(text):
    btn = QPushButton(text)
    btn.setStyleSheet(_BTN.format(
        bg="#0a1a2e", fg=_BLUE, border="#1a4060",
        hover="#0e2240", hb=_BLUE, font=_MONO))
    return btn

def _ghost(text):
    btn = QPushButton(text)
    btn.setStyleSheet(_BTN.format(
        bg="transparent", fg=_DIM, border="#2a2a2a",
        hover="#1a1a1a", hb="#555", font=_MONO))
    return btn

def _hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color: #222;")
    return f

def _lbl(text, color=_DIM, size=11, bold=False, wrap=False):
    l = QLabel(text)
    w = "bold" if bold else "normal"
    l.setStyleSheet(
        f"color:{color}; font-size:{size}px; font-weight:{w}; font-family:{_MONO};")
    if wrap:
        l.setWordWrap(True)
    return l


class _Sig(QObject):
    progress = Signal(str)
    done     = Signal(bool, str)


class DriveSyncPanel(QWidget):
    """Token-based Drive sync panel. Drop into any settings dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy  = False
        self._sig   = _Sig()
        self._sig.progress.connect(self._on_progress)
        self._sig.done.connect(self._on_done)
        self._build()
        QTimer.singleShot(100, self._refresh)

    def _build(self):
        self.setStyleSheet(f"background:{_CARD}; border-radius:3px;")
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # Header
        hdr = QHBoxLayout()
        hdr.addWidget(_lbl("Google Drive Sync", _TEXT, 13, bold=True))
        hdr.addStretch()
        self._dot = _lbl("●", _DIM, 11)
        hdr.addWidget(self._dot)
        root.addLayout(hdr)

        root.addWidget(_hline())

        root.addWidget(_lbl(
            "Back up exports and projects to your personal Google Drive.\n"
            "Requires a SteamKustom account token.",
            wrap=True,
        ))

        # Status
        self._status = _lbl("Checking…", _DIM)
        root.addWidget(self._status)

        # Token row
        token_row = QHBoxLayout()
        token_row.setSpacing(8)

        self._token_edit = QLineEdit()
        self._token_edit.setPlaceholderText("Paste token from steamkustom.com → Settings → Apps…")
        self._token_edit.setEchoMode(QLineEdit.Password)
        self._token_edit.setStyleSheet(
            f"background:#0a0a0a; border:1px solid #2a2a2a; color:{_TEXT}; "
            f"font-family:{_MONO}; font-size:12px; padding:5px 8px; border-radius:2px;")

        # Pre-fill saved token
        try:
            from app.services.steamkustom_auth import get_token
            saved = get_token() or ""
            if saved:
                self._token_edit.setText(saved)
        except Exception:
            pass

        token_row.addWidget(self._token_edit, 1)

        self._connect_btn = _primary("Connect")
        self._connect_btn.clicked.connect(self._connect)
        token_row.addWidget(self._connect_btn)

        root.addLayout(token_row)

        # Get token link
        link = QLabel(
            f'<a href="https://steamkustom.com/settings" '
            f'style="color:{_BLUE};">Get token at steamkustom.com →</a>'
        )
        link.setOpenExternalLinks(True)
        link.setStyleSheet(f"font-size:10px; font-family:{_MONO};")
        root.addWidget(link)

        root.addWidget(_hline())

        # Upload / Download buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._upload_btn = _ghost("⬆  Upload")
        self._upload_btn.clicked.connect(self._upload)
        self._upload_btn.setEnabled(False)
        btn_row.addWidget(self._upload_btn)

        self._download_btn = _ghost("⬇  Download")
        self._download_btn.clicked.connect(self._download)
        self._download_btn.setEnabled(False)
        btn_row.addWidget(self._download_btn)

        btn_row.addStretch()
        root.addLayout(btn_row)

        self._progress = _lbl("", _DIM, 11)
        root.addWidget(self._progress)

        root.addWidget(_lbl(
            "Files stored in 'Steam Grunge Editor' in your own Google Drive.",
            _DIM, 10))

    # ── Status ────────────────────────────────────────────────────────────────

    def _refresh(self):
        try:
            from app.services.steamkustom_auth import get_token, is_connected
            token = get_token()
            if not token:
                self._set_status("No token — paste one above and click Connect.", _DIM)
                self._dot.setStyleSheet(f"color:{_DIM}; font-size:11px;")
                self._upload_btn.setEnabled(False)
                self._download_btn.setEnabled(False)
                self._connect_btn.setText("Connect")
            else:
                # Token saved — check if Drive is accessible
                from app.services.drive_sync import is_authenticated
                if is_authenticated():
                    self._set_status("✓  Connected — Drive sync active", _GREEN)
                    self._dot.setStyleSheet(f"color:{_GREEN}; font-size:11px;")
                    self._upload_btn.setEnabled(True)
                    self._download_btn.setEnabled(True)
                    self._connect_btn.setText("Update Token")
                else:
                    self._set_status(
                        "Token saved but Google Drive not linked.\n"
                        "Connect Google Drive at steamkustom.com → Settings → Connections.",
                        _GOLD)
                    self._dot.setStyleSheet(f"color:{_GOLD}; font-size:11px;")
                    self._upload_btn.setEnabled(False)
                    self._download_btn.setEnabled(False)
        except Exception as e:
            self._set_status(f"Error: {e}", _RED)

    def _set_status(self, msg, color=_DIM):
        self._status.setText(msg)
        self._status.setStyleSheet(
            f"color:{color}; font-size:11px; font-family:{_MONO};")

    def _set_progress(self, msg, color=_DIM):
        self._progress.setText(msg)
        self._progress.setStyleSheet(
            f"color:{color}; font-size:11px; font-family:{_MONO};")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _connect(self):
        token = self._token_edit.text().strip()
        if not token:
            self._set_progress("Paste a token first.", _GOLD)
            return

        self._connect_btn.setEnabled(False)
        self._set_progress("Verifying token…", _BLUE)

        def _done(ok, user):
            self._sig.done.emit(
                ok,
                f"✓ Connected as {user.get('username','')}" if ok
                else "✗ Invalid token — get one at steamkustom.com/settings"
            )
            if ok:
                from app.services.steamkustom_auth import save_token
                save_token(token)

        from app.services.steamkustom_auth import verify_async
        verify_async(token, _done)

    def _upload(self):
        if self._busy:
            return
        self._busy = True
        self._upload_btn.setEnabled(False)
        self._download_btn.setEnabled(False)

        def _work():
            from app.services.drive_sync import upload_all
            try:
                r = upload_all(on_progress=lambda m: self._sig.progress.emit(m))
                n = r.get("uploaded", 0)
                e = r.get("errors", [])
                msg   = f"✓ {n} file{'s' if n != 1 else ''} uploaded" if not e else f"Error: {e[0]}"
                color = _GREEN if not e else _RED
                self._sig.done.emit(not bool(e), msg)
            except Exception as ex:
                self._sig.done.emit(False, str(ex))

        threading.Thread(target=_work, daemon=True).start()

    def _download(self):
        if self._busy:
            return
        self._busy = True
        self._upload_btn.setEnabled(False)
        self._download_btn.setEnabled(False)

        def _work():
            from app.services.drive_sync import download_all
            try:
                r = download_all(on_progress=lambda m: self._sig.progress.emit(m))
                n = r.get("downloaded", 0)
                e = r.get("errors", [])
                msg   = f"✓ {n} file{'s' if n != 1 else ''} downloaded" if not e else f"Error: {e[0]}"
                color = _GREEN if not e else _RED
                self._sig.done.emit(not bool(e), msg)
            except Exception as ex:
                self._sig.done.emit(False, str(ex))

        threading.Thread(target=_work, daemon=True).start()

    def _on_progress(self, msg):
        self._set_progress(msg, _BLUE)

    def _on_done(self, ok, msg):
        self._busy = False
        color = _GREEN if ok else _RED
        self._set_progress(msg, color)
        self._connect_btn.setEnabled(True)
        self._refresh()
        QTimer.singleShot(5000, lambda: self._set_progress(""))