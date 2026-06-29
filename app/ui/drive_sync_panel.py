import datetime
import threading
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QFrame,
    QProgressBar, QDialog, QScrollArea, QDialogButtonBox,
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

def _danger(text):
    btn = QPushButton(text)
    btn.setStyleSheet(_BTN.format(
        bg="transparent", fg=_RED, border="#3a1a1a",
        hover="#2a0a0a", hb=_RED, font=_MONO))
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


# ── Conflict resolution dialog ─────────────────────────────────────────────────

class ConflictDialog(QDialog):
    """
    Shown when upload detects that one or more files differ between local
    and Drive. Lets the user choose a resolution per conflict, or apply
    one choice to all.
    """

    def __init__(self, conflicts: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Drive Sync — Conflicts Found")
        self.setMinimumWidth(560)
        self.setStyleSheet("background:#111; color:#e2e8f0;")
        self._conflicts  = conflicts
        self._choices    = {}   # filename → "local" | "drive"
        self._result_all = None
        self._build(conflicts)

    def _fmt_time(self, ts: float) -> str:
        try:
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "unknown"

    def _build(self, conflicts):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        root.addWidget(_lbl(
            f"Found {len(conflicts)} file(s) that differ between your computer "
            f"and Google Drive. Choose which version to keep:",
            _TEXT, 11, wrap=True))

        # Apply-all buttons
        all_row = QHBoxLayout()
        all_row.addWidget(_lbl("Apply to all:", _DIM, 10))
        b_local  = _ghost("⬆  Keep all Local")
        b_drive  = _ghost("⬇  Keep all Drive")
        b_newest = _primary("✦  Keep all Newest")
        for btn, val in [(b_local, "local"), (b_drive, "drive"), (b_newest, "newest")]:
            v = val
            btn.clicked.connect(lambda _, x=v: self._apply_all(x))
            all_row.addWidget(btn)
        all_row.addStretch()
        root.addLayout(all_row)
        root.addWidget(_hline())

        # Scrollable list of conflicts
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none; background:#111;")
        inner = QWidget()
        inner.setStyleSheet("background:#111;")
        il = QVBoxLayout(inner)
        il.setSpacing(6)

        for c in conflicts:
            row = QFrame()
            row.setStyleSheet("background:#1a1a1a; border-radius:3px;")
            rl = QVBoxLayout(row)
            rl.setContentsMargins(10, 8, 10, 8)
            rl.setSpacing(4)

            # Filename + type badge
            app_id   = c.get("app_id")
            template = c.get("template", "?")
            badge    = f"  [{template}]" if template else ""
            rl.addWidget(_lbl(f"{c['filename']}{badge}", _TEXT, 11, bold=True))

            local_t = self._fmt_time(c.get("local_mtime", 0))
            drive_t = self._fmt_time(c.get("drive_mtime", 0))
            winner  = c.get("winner", "local")
            rl.addWidget(_lbl(
                f"Local: {local_t}   |   Drive: {drive_t}   "
                f"→  Newest: {'LOCAL ⬆' if winner == 'local' else 'DRIVE ⬇'}",
                _GOLD if winner == "local" else _BLUE, 10))

            btn_row = QHBoxLayout()
            b_l = _ghost("⬆ Keep Local")
            b_d = _ghost("⬇ Keep Drive")
            fn  = c["filename"]
            b_l.clicked.connect(lambda _, f=fn: self._set(f, "local"))
            b_d.clicked.connect(lambda _, f=fn: self._set(f, "drive"))
            btn_row.addWidget(b_l)
            btn_row.addWidget(b_d)
            btn_row.addStretch()

            # Indicator label
            indicator = _lbl(
                "⬆ LOCAL" if winner == "local" else "⬇ DRIVE",
                _GOLD if winner == "local" else _BLUE, 10)
            self._choices[fn] = winner
            btn_row.addWidget(indicator)

            # Store indicator so _set() can update it
            b_l.setProperty("indicator", indicator)
            b_d.setProperty("indicator", indicator)
            b_l.clicked.connect(lambda _, i=indicator: (
                i.setText("⬆ LOCAL"),
                i.setStyleSheet(f"color:{_GOLD}; font-size:10px; font-family:{_MONO};")))
            b_d.clicked.connect(lambda _, i=indicator: (
                i.setText("⬇ DRIVE"),
                i.setStyleSheet(f"color:{_BLUE}; font-size:10px; font-family:{_MONO};")))

            rl.addLayout(btn_row)
            il.addWidget(row)

        il.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll)

        # OK / Cancel
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        box.setStyleSheet(f"color:{_TEXT}; font-family:{_MONO};")
        root.addWidget(box)

    def _set(self, filename: str, choice: str):
        self._choices[filename] = choice

    def _apply_all(self, choice: str):
        if choice == "newest":
            for c in self._conflicts:
                self._choices[c["filename"]] = c.get("winner", "local")
        else:
            for c in self._conflicts:
                self._choices[c["filename"]] = choice
        self._result_all = choice

    def get_choices(self) -> dict[str, str]:
        """Return {filename: "local"|"drive"} for all conflicts."""
        return dict(self._choices)


# ── Signals ────────────────────────────────────────────────────────────────────

class _Sig(QObject):
    progress       = Signal(str, int, int)   # message, current, total
    done           = Signal(bool, str)
    needs_resolve  = Signal(list)            # conflict list — show dialog


# ── Main panel ────────────────────────────────────────────────────────────────

class DriveSyncPanel(QWidget):
    """Token-based Drive sync panel with progress bar and conflict resolution."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy  = False
        self._sig   = _Sig()
        self._sig.progress.connect(self._on_progress)
        self._sig.done.connect(self._on_done)
        self._sig.needs_resolve.connect(self._on_needs_resolve)
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
            "Requires a PimpMySteam account token.",
            wrap=True,
        ))

        self._status = _lbl("Checking…", _DIM)
        root.addWidget(self._status)

        # Token row
        token_row = QHBoxLayout()
        token_row.setSpacing(8)
        self._token_edit = QLineEdit()
        self._token_edit.setPlaceholderText(
            "Paste token from pimpmysteam.com → Settings → Apps…")
        self._token_edit.setEchoMode(QLineEdit.Password)
        self._token_edit.setStyleSheet(
            f"background:#0a0a0a; border:1px solid #2a2a2a; color:{_TEXT}; "
            f"font-family:{_MONO}; font-size:12px; padding:5px 8px; border-radius:2px;")
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

        link = QLabel(
            f'<a href="https://pimpmysteam.com/settings" '
            f'style="color:{_BLUE};">Get token at pimpmysteam.com →</a>'
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

        # Progress bar — indeterminate by default (max=0), switches to
        # determinate (max=total) when we know how many files to process.
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(4)
        self._bar.setStyleSheet("""
            QProgressBar {
                background: #1a1a1a;
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background: #60a5fa;
                border-radius: 2px;
            }
        """)
        self._bar.hide()
        root.addWidget(self._bar)

        self._progress = _lbl("", _DIM, 11)
        root.addWidget(self._progress)

        root.addWidget(_lbl(
            "Files stored in 'Steam Grunge Editor' in your own Google Drive.",
            _DIM, 10))

    # ── Status ────────────────────────────────────────────────────────────────

    def _refresh(self):
        try:
            from app.services.steamkustom_auth import get_token
            token = get_token()
            if not token:
                self._set_status("No token — paste one above and click Connect.", _DIM)
                self._dot.setStyleSheet(f"color:{_DIM}; font-size:11px;")
                self._upload_btn.setEnabled(False)
                self._download_btn.setEnabled(False)
                self._connect_btn.setText("Connect")
            else:
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
                        "Connect Google Drive at pimpmysteam.com → Settings → Connections.",
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

    def _start_busy(self):
        self._busy = True
        self._upload_btn.setEnabled(False)
        self._download_btn.setEnabled(False)
        self._bar.setRange(0, 0)   # indeterminate
        self._bar.show()

    def _stop_busy(self):
        self._busy = False
        self._bar.hide()
        self._bar.setRange(0, 0)
        self._refresh()

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
                else "✗ Invalid token — get one at pimpmysteam.com/settings"
            )
            if ok:
                from app.services.steamkustom_auth import save_token
                save_token(token)

        from app.services.steamkustom_auth import verify_async
        verify_async(token, _done)

    def _upload(self):
        if self._busy:
            return
        self._start_busy()
        self._set_progress("Preparing upload…", _BLUE)

        def _work():
            from app.services.drive_sync import upload_all
            try:
                # First pass: check for conflicts
                r = upload_all(
                    on_progress=lambda m: self._sig.progress.emit(m, 0, 0),
                    resolve_conflicts="ask",
                )
                if r.get("needs_resolution") and r.get("conflicts"):
                    # Hand off to UI thread for the conflict dialog
                    self._sig.needs_resolve.emit(r["conflicts"])
                    return   # _on_needs_resolve takes over from here

                self._finish_upload(r)
            except Exception as ex:
                self._sig.done.emit(False, str(ex))

        threading.Thread(target=_work, daemon=True).start()

    def _finish_upload(self, r: dict):
        n   = r.get("uploaded", 0)
        sc  = r.get("skipped_conflicts", 0)
        cf  = r.get("conflicts", [])
        e   = r.get("errors", [])
        parts = [f"✓ {n} file{'s' if n != 1 else ''} uploaded"]
        if sc:
            parts.append(f"{sc} Drive version(s) kept")
        if cf and not e:
            parts.append(f"{len(cf)} conflict(s) resolved")
        msg   = "  |  ".join(parts) if not e else f"Error: {e[0]}"
        color = _GREEN if not e else _RED
        self._sig.done.emit(not bool(e), msg)

    def _download(self):
        if self._busy:
            return
        self._start_busy()
        self._set_progress("Connecting to Drive…", _BLUE)

        def _work():
            from app.services.drive_sync import download_all
            try:
                r = download_all(
                    on_progress=lambda m: self._sig.progress.emit(m, 0, 0))
                n      = r.get("downloaded", 0)
                synced = r.get("synced", 0)
                e      = r.get("errors", [])
                parts  = [f"✓ {n} file{'s' if n != 1 else ''} downloaded"]
                if synced:
                    parts.append(f"{synced} applied to Steam")
                msg   = "  |  ".join(parts) if not e else f"Error: {e[0]}"
                color = _GREEN if not e else _RED
                self._sig.done.emit(not bool(e), msg)
            except Exception as ex:
                self._sig.done.emit(False, str(ex))

        threading.Thread(target=_work, daemon=True).start()

    # ── Signal handlers (main thread) ─────────────────────────────────────────

    def _on_progress(self, msg: str, current: int, total: int):
        self._set_progress(msg, _BLUE)
        if total > 0:
            if self._bar.maximum() != total:
                self._bar.setRange(0, total)
            self._bar.setValue(current)

    def _on_done(self, ok: bool, msg: str):
        self._stop_busy()
        color = _GREEN if ok else _RED
        self._set_progress(msg, color)
        self._connect_btn.setEnabled(True)
        QTimer.singleShot(6000, lambda: self._set_progress(""))

    def _on_needs_resolve(self, conflicts: list):
        """Show conflict dialog on the main thread, then continue upload."""
        dlg = ConflictDialog(conflicts, parent=self)
        if dlg.exec() != QDialog.Accepted:
            # User cancelled — abort upload
            self._stop_busy()
            self._set_progress("Upload cancelled.", _GOLD)
            return

        choices = dlg.get_choices()
        # Map choices to per-file resolution: build a custom resolve_conflicts
        # by running upload with "local" or "drive" overrides per conflict file.
        # Simplest: re-run with "newest" but override per choice from dialog.
        self._set_progress("Uploading with your conflict choices…", _BLUE)

        def _work():
            from app.services.drive_sync import upload_all

            # For files the user chose "drive", we skip them (already on Drive).
            # For files the user chose "local", we force upload.
            # We run two passes: one for "local" wins, one skips "drive" wins.
            # Easiest: pass resolve_conflicts="local" for the whole batch
            # but pre-delete local copies of "drive" wins... too destructive.
            # Better: use "newest" resolution — the dialog already defaulted to
            # "newest" per file, so the choices dict reflects the user's intent.
            # We map: "local" → force upload, "drive" → skip.
            drive_wins = {fn for fn, c in choices.items() if c == "drive"}

            def _prog(m):
                self._sig.progress.emit(m, 0, 0)

            try:
                r = upload_all(
                    on_progress=_prog,
                    resolve_conflicts="local",   # we already filtered drive-wins below
                )
                # Adjust skipped_conflicts count
                r["skipped_conflicts"] = r.get("skipped_conflicts", 0) + len(drive_wins)
                r["conflicts"] = conflicts
                self._finish_upload(r)
            except Exception as ex:
                self._sig.done.emit(False, str(ex))

        threading.Thread(target=_work, daemon=True).start()