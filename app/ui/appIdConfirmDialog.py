"""
AppID Confirmation Dialog — shown once per game per tab session.

Flow:
  1. Opens with the detected game name from SteamGridDB.
  2. Auto-searches Steam Store API in background thread.
  3. Shows: "Game detected: X  |  AppID: Y  |  Is this correct?"
  4a. [Confirm]         → stores AppID in tab state, dialog closes.
  4b. [Search Manually] → expands a search panel where user can type + pick.
  5. Once confirmed, the caller proceeds with export using the cached AppID.

Usage:
    from app.ui.appIdConfirmDialog import AppIdConfirmDialog

    dlg = AppIdConfirmDialog(game_name="Resident Evil 4", parent=self)
    if dlg.exec() == QDialog.Accepted:
        app_id = dlg.result_app_id      # int
        canonical = dlg.result_name     # str — canonical Steam name
"""
from __future__ import annotations
from typing import Optional, List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QFrame,
    QSizePolicy, QProgressBar, QWidget,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui  import QFont, QColor

from app.services.appIdGetter import search_candidates, NetworkError


# ── async worker ──────────────────────────────────────────────────────────────
class _SearchWorker(QObject):
    """
    Runs search_candidates() on a background QThread.

    Emits done(candidates, error_code, error_message):
      - error_code is "" on success, or one of:
        "network" | "timeout" | "ssl" | "no_results"
      - All UI updates must happen in slots connected to done — never inside run().
    """
    done = Signal(list, str, str)   # (candidates, error_code, error_message)

    def __init__(self, query: str):
        super().__init__()
        self._q = query

    def run(self):
        """
        Executed on the worker thread.  Must NOT touch any Qt widgets.
        All results are delivered via the done signal.
        """
        try:
            results = search_candidates(self._q, limit=10)
            if results:
                self.done.emit(results, "", "")
            else:
                self.done.emit([], "no_results", "No Steam matches found.")
        except NetworkError as exc:
            msg = str(exc)
            # Classify the error so the UI can show a helpful message
            lower = msg.lower()
            if "ssl" in lower or "certificate" in lower:
                code = "ssl"
            elif "timeout" in lower or "timed out" in lower:
                code = "timeout"
            else:
                code = "network"
            self.done.emit([], code, msg)
        except Exception as exc:
            self.done.emit([], "network", str(exc))


_ERROR_LABELS = {
    "ssl":        "SSL / certificate error — network may be restricted.",
    "timeout":    "Request timed out — check your internet connection.",
    "network":    "Network error — check your internet connection.",
    "no_results": "No Steam matches found.",
}


# ── helpers ───────────────────────────────────────────────────────────────────
def _hline():
    f = QFrame(); f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color:#2a2a2a; background:#2a2a2a; max-height:1px;")
    return f


STYLE = """
QDialog {
    background: #111118;
    font-family: 'Courier New', monospace;
    font-size: 13px;
    color: #ccc;
}
QLabel               { color: #aaa; font-size: 13px; }
QLabel#heading       { color: #ddd; font-size: 14px; font-weight: bold; }
QLabel#sub           { color: #666; font-size: 11px; letter-spacing: 1px; }
QLabel#game_name_lbl { color: #eee; font-size: 18px; font-weight: bold;
                       font-family: 'Courier New'; letter-spacing: 1px; }
QLabel#appid_lbl     { color: #88cc88; font-size: 22px; font-weight: bold;
                       font-family: 'Courier New'; }
QLabel#appid_sub     { color: #3a6e3a; font-size: 11px; }
QLabel#warn          { color: #cc8844; font-size: 12px; }
QLabel#ok            { color: #88cc88; font-size: 12px; }
QLineEdit {
    background: #1a1a22; border: 1px solid #333; color: #ddd;
    font-family: 'Courier New'; font-size: 13px;
    padding: 5px 8px; border-radius: 2px;
}
QLineEdit:focus { border-color: #5566aa; }
QListWidget {
    background: #0e0e14; border: 1px solid #2a2a3a; color: #ccc;
    font-family: 'Courier New'; font-size: 12px;
    outline: none;
}
QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #1a1a22; }
QListWidget::item:selected { background: #1e2a3a; color: #88aaff; }
QListWidget::item:hover    { background: #161628; }
QPushButton {
    background: #1a1a28; border: 1px solid #333;
    color: #aaa; font-family: 'Courier New'; font-size: 13px;
    padding: 7px 18px; border-radius: 2px; min-height: 30px;
}
QPushButton:hover   { background: #222238; color: #ddd; border-color: #5566aa; }
QPushButton:pressed { background: #111120; }
QPushButton#confirm_btn {
    background: #1a2e1a; border: 1px solid #3a6e3a;
    color: #88cc88; font-weight: bold; font-size: 14px;
    min-width: 140px;
}
QPushButton#confirm_btn:hover   { background: #223a22; border-color: #55aa55; color: #aaffaa; }
QPushButton#confirm_btn:disabled { background: #111; color: #333; border-color: #222; }
QPushButton#manual_btn {
    background: transparent; border: 1px solid #2a2a3a;
    color: #555; font-size: 12px;
}
QPushButton#manual_btn:hover { color: #aaa; border-color: #444; }
QProgressBar {
    background: #1a1a22; border: 1px solid #2a2a2a;
    border-radius: 2px; height: 4px;
}
QProgressBar::chunk { background: #3a5a3a; border-radius: 2px; }
"""


class AppIdConfirmDialog(QDialog):
    """
    Confirm or manually pick the Steam AppID before export.

    After exec() == Accepted:
        self.result_app_id  (int)
        self.result_name    (str)
    """

    def __init__(self, game_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm Steam Game")
        self.setMinimumWidth(460)
        self.setModal(True)
        self.setStyleSheet(STYLE)

        self._game_name = game_name.strip()
        self._candidates: List[dict] = []
        self._best: Optional[dict] = None
        self._manual_open = False

        # Thread handles — tracked so we can guard stale signals from
        # previously cancelled searches arriving after a new one started.
        self._auto_worker   = None
        self._auto_thread   = None
        self._manual_worker = None
        self._manual_thread = None

        self.result_app_id: Optional[int] = None
        self.result_name:   str = ""

        self._build()
        self._start_search(self._game_name)

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(24, 20, 24, 20)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QLabel("STEAM GAME DETECTED")
        hdr.setObjectName("sub")
        root.addWidget(hdr)

        # Game name (big)
        self._name_lbl = QLabel(self._game_name)
        self._name_lbl.setObjectName("game_name_lbl")
        self._name_lbl.setWordWrap(True)
        root.addWidget(self._name_lbl)

        # AppID display
        appid_row = QHBoxLayout()
        appid_col = QVBoxLayout()
        id_lbl = QLabel("STEAM APP ID")
        id_lbl.setObjectName("sub")
        self._appid_lbl = QLabel("—")
        self._appid_lbl.setObjectName("appid_lbl")
        appid_col.addWidget(id_lbl)
        appid_col.addWidget(self._appid_lbl)
        appid_row.addLayout(appid_col)
        appid_row.addStretch()

        # store link (small)
        self._link_lbl = QLabel("")
        self._link_lbl.setObjectName("appid_sub")
        self._link_lbl.setOpenExternalLinks(True)
        self._link_lbl.setTextFormat(Qt.RichText)
        appid_row.addWidget(self._link_lbl, 0, Qt.AlignBottom)
        root.addLayout(appid_row)

        # Status / loading
        self._status_lbl = QLabel("Searching Steam Store…")
        self._status_lbl.setObjectName("warn")
        root.addWidget(self._status_lbl)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        root.addWidget(self._progress)

        root.addWidget(_hline())

        # ── Action buttons ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()

        self._manual_btn = QPushButton("Search Manually")
        self._manual_btn.setObjectName("manual_btn")
        self._manual_btn.clicked.connect(self._toggle_manual)
        btn_row.addWidget(self._manual_btn)

        btn_row.addStretch()

        self._confirm_btn = QPushButton("✔  Confirm")
        self._confirm_btn.setObjectName("confirm_btn")
        self._confirm_btn.setEnabled(False)
        self._confirm_btn.clicked.connect(self._confirm)
        btn_row.addWidget(self._confirm_btn)

        root.addLayout(btn_row)

        # ── Manual search panel (hidden by default) ───────────────────────────
        self._manual_panel = QWidget()
        self._manual_panel.setVisible(False)
        mp = QVBoxLayout(self._manual_panel)
        mp.setContentsMargins(0, 0, 0, 0)
        mp.setSpacing(6)

        mp.addWidget(_hline())

        search_row = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Enter game title…")
        self._search_edit.returnPressed.connect(self._manual_search)
        search_row.addWidget(self._search_edit, 1)
        search_btn = QPushButton("Search")
        search_btn.setFixedWidth(80)
        search_btn.clicked.connect(self._manual_search)
        search_row.addWidget(search_btn)
        mp.addLayout(search_row)

        # ── Direct numeric AppID entry ─────────────────────────────────────
        # If the user already knows their AppID (from the Steam store URL),
        # they can type it here and Confirm becomes available immediately
        # without any network request.
        numeric_lbl = QLabel("— or enter AppID directly —")
        numeric_lbl.setAlignment(Qt.AlignCenter)
        numeric_lbl.setStyleSheet("color:#444; font-size:11px; padding-top:4px;")
        mp.addWidget(numeric_lbl)

        numeric_row = QHBoxLayout()
        numeric_row.addStretch()
        self._numeric_edit = QLineEdit()
        self._numeric_edit.setPlaceholderText("e.g.  1971870")
        self._numeric_edit.setFixedWidth(160)
        self._numeric_edit.setAlignment(Qt.AlignCenter)
        self._numeric_edit.textChanged.connect(self._on_numeric_changed)
        self._numeric_edit.returnPressed.connect(self._apply_numeric)
        numeric_row.addWidget(self._numeric_edit)
        self._use_numeric_btn = QPushButton("Use This ID")
        self._use_numeric_btn.setFixedWidth(100)
        self._use_numeric_btn.setEnabled(False)
        self._use_numeric_btn.clicked.connect(self._apply_numeric)
        numeric_row.addWidget(self._use_numeric_btn)
        numeric_row.addStretch()
        mp.addLayout(numeric_row)

        self._search_progress = QProgressBar()
        self._search_progress.setRange(0, 0)
        self._search_progress.setFixedHeight(4)
        self._search_progress.setVisible(False)
        mp.addWidget(self._search_progress)

        self._results_list = QListWidget()
        self._results_list.setFixedHeight(180)
        self._results_list.itemClicked.connect(self._on_result_picked)
        mp.addWidget(self._results_list)

        root.addWidget(self._manual_panel)

    # ── auto search ───────────────────────────────────────────────────────────
    def _start_search(self, query: str):
        if not query:
            self._progress.setVisible(False)
            self._status_lbl.setText("No game name — enter AppID manually.")
            self._status_lbl.setStyleSheet("color:#cc8844;")
            if not self._manual_open:
                self._toggle_manual()
            return

        # Cancel stale in-flight search so its done signal is ignored
        if self._auto_thread and self._auto_thread.isRunning():
            self._auto_thread.quit()
            self._auto_thread.wait(200)

        self._progress.setVisible(True)
        self._confirm_btn.setEnabled(False)

        worker = _SearchWorker(query)
        thread = QThread()           # no parent — avoids "Cannot create children
                                     # for a parent in a different thread" warning
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # QueuedConnection ensures the slot always runs on the main thread,
        # even though the signal is emitted from the worker thread.
        worker.done.connect(self._on_auto_done, Qt.QueuedConnection)
        worker.done.connect(thread.quit, Qt.QueuedConnection)
        thread.finished.connect(worker.deleteLater)   # worker lives on thread; clean up after
        thread.finished.connect(thread.deleteLater)   # clean up thread object
        self._auto_worker = worker
        self._auto_thread = thread
        thread.start()

    def _on_auto_done(self, candidates: list, error_code: str, error_msg: str):
        """Trampoline: only dispatch if this signal came from the current worker."""
        # By the time this slot runs (main thread), _auto_worker may have been
        # replaced by a newer search.  The QueuedConnection guarantees we're on
        # the main thread, so the comparison is race-free.
        sender = self.sender()
        if sender is not self._auto_worker:
            return
        self._on_search_done(candidates, error_code, error_msg)

    def _on_search_done(self, candidates: list, error_code: str, error_msg: str):
        """Called on the main thread via signal — safe to update UI."""
        self._progress.setVisible(False)
        self._candidates = candidates

        if error_code and error_code != "no_results":
            # Real network/SSL failure — show a specific message and auto-open
            # the manual panel so the user can enter an AppID offline.
            friendly = _ERROR_LABELS.get(error_code, "Search unavailable.")
            detail   = error_msg[:120] + ("…" if len(error_msg) > 120 else "")
            self._status_lbl.setText(f"{friendly}\n{detail}")
            self._status_lbl.setStyleSheet("color:#cc8844;")
            if not self._manual_open:
                self._toggle_manual()
            return

        if error_code == "no_results" or not candidates:
            self._status_lbl.setText(
                "No Steam matches found — enter AppID manually or try searching."
            )
            self._status_lbl.setStyleSheet("color:#cc8844;")
            return

        # Best match: exact name first, else first result
        name_lower = self._game_name.lower()
        best = next(
            (c for c in candidates if c["name"].lower() == name_lower),
            candidates[0]
        )
        self._apply_candidate(best)

    def _apply_candidate(self, c: dict):
        self._best = c
        self._appid_lbl.setText(str(c["id"]))
        self._name_lbl.setText(c["name"])
        self._link_lbl.setText(
            f'<a href="https://store.steampowered.com/app/{c["id"]}" '
            f'style="color:#3a5a8a;">store.steampowered.com/app/{c["id"]}</a>'
        )
        self._status_lbl.setText("✔  Match found — confirm or search manually.")
        self._status_lbl.setStyleSheet("color:#88cc88;")
        self._confirm_btn.setEnabled(True)

    # ── manual search ─────────────────────────────────────────────────────────
    def _toggle_manual(self):
        self._manual_open = not self._manual_open
        self._manual_panel.setVisible(self._manual_open)
        self._manual_btn.setText(
            "Hide Manual Search" if self._manual_open else "Search Manually"
        )
        if self._manual_open and not self._search_edit.text():
            self._search_edit.setText(self._game_name)
        self.adjustSize()

    def _manual_search(self):
        q = self._search_edit.text().strip()
        if not q:
            return

        # Pure number → direct AppID, no network call needed
        if q.isdigit():
            self._numeric_edit.setText(q)
            self._apply_numeric()
            return

        # Cancel any stale manual search
        if self._manual_thread and self._manual_thread.isRunning():
            self._manual_thread.quit()
            self._manual_thread.wait(200)

        self._results_list.clear()
        self._search_progress.setVisible(True)

        worker = _SearchWorker(q)
        thread = QThread()           # no parent — avoids cross-thread parent warning
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # QueuedConnection ensures slot runs on main thread; trampoline guards
        # against stale signals from a replaced worker arriving out of order.
        worker.done.connect(self._on_manual_done, Qt.QueuedConnection)
        worker.done.connect(thread.quit, Qt.QueuedConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._manual_worker = worker
        self._manual_thread = thread
        thread.start()

    def _on_manual_done(self, candidates: list, error_code: str, error_msg: str):
        """Trampoline: only dispatch if this signal came from the current worker."""
        sender = self.sender()
        if sender is not self._manual_worker:
            return
        self._on_manual_results(candidates, error_code, error_msg)

    def _on_manual_results(self, candidates: list, error_code: str, error_msg: str):
        """Called on the main thread via signal — safe to update UI."""
        self._search_progress.setVisible(False)
        self._results_list.clear()

        if error_code and error_code != "no_results":
            friendly = _ERROR_LABELS.get(error_code, "Search unavailable.")
            detail   = error_msg[:120] + ("…" if len(error_msg) > 120 else "")
            for text, color in [(f"⚠  {friendly}", "#cc8844"), (detail, "#666")]:
                if text:
                    item = QListWidgetItem(text)
                    item.setForeground(QColor(color))
                    item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                    self._results_list.addItem(item)
            return

        if error_code == "no_results" or not candidates:
            item = QListWidgetItem("No Steam matches found — try a different name.")
            item.setForeground(QColor("#888"))
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self._results_list.addItem(item)
            return

        for c in candidates:
            item = QListWidgetItem(f"{c['name']}   —   AppID: {c['id']}")
            item.setData(Qt.UserRole, c)
            self._results_list.addItem(item)

    def _on_numeric_changed(self, text: str):
        """Enable 'Use This ID' as soon as the field contains only digits."""
        self._use_numeric_btn.setEnabled(text.strip().isdigit() and len(text.strip()) > 0)

    def _apply_numeric(self):
        """
        Accept the directly entered numeric AppID without any network lookup.
        The canonical name is set to the game_name passed into the dialog,
        since we have no Steam search result to pull a canonical name from.
        """
        raw = self._numeric_edit.text().strip()
        if not raw.isdigit():
            return
        app_id = int(raw)
        synthetic = {
            "id":   app_id,
            "name": self._game_name or f"AppID {app_id}",
        }
        self._apply_candidate(synthetic)
        self._status_lbl.setText(f"✔  Using AppID {app_id} (entered manually).")
        self._status_lbl.setStyleSheet("color:#88cc88;")
        # Collapse manual panel — user is done
        if self._manual_open:
            self._manual_open = False
            self._manual_panel.setVisible(False)
            self._manual_btn.setText("Search Manually")
            self.adjustSize()

    def _on_result_picked(self, item: QListWidgetItem):
        c = item.data(Qt.UserRole)
        if c:
            self._apply_candidate(c)
            # Collapse manual panel after picking
            self._manual_open = False
            self._manual_panel.setVisible(False)
            self._manual_btn.setText("Search Manually")
            self.adjustSize()

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def closeEvent(self, event):
        """
        Stop any in-flight search threads before the dialog is destroyed.

        Without this, a running thread can emit its done signal after the
        dialog widgets are gone, causing a crash or stale UI mutation.
        We disconnect signals first so the slots are never called on a
        dead widget, then ask the threads to quit and give them 500 ms.
        """
        for worker, thread in [
            (self._auto_worker,   self._auto_thread),
            (self._manual_worker, self._manual_thread),
        ]:
            if thread and thread.isRunning():
                if worker:
                    try: worker.done.disconnect()
                    except RuntimeError: pass   # already disconnected
                thread.quit()
                thread.wait(500)
        super().closeEvent(event)

    # ── confirm ───────────────────────────────────────────────────────────────
    def _confirm(self):
        if self._best:
            self.result_app_id = self._best["id"]
            self.result_name   = self._best["name"]
            # Persist confirmed mapping so future exports skip this dialog
            try:
                from app.services.appIdRegistry import AppIdRegistry
                AppIdRegistry.shared().register(
                    self._game_name, self.result_app_id,
                    canonical=self.result_name,
                )
            except Exception:
                pass   # registry is best-effort; never block export
            self.accept()