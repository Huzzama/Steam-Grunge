from __future__ import annotations
from typing import Optional, List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QFrame,
    QSizePolicy, QProgressBar, QWidget,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui  import QColor

from app.services.appIdGetter import search_candidates, NetworkError
from app.ui        import icons
from app.ui.kit    import Button, Divider, label, hbox, vbox, grid, set_tone
from app.ui.theme  import C, SP


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


# ── status line (icon + tone-coloured text) ───────────────────────────────────
_TONE_ICON = {"green": ("circle-check", C["green"]), "red": ("circle-x", C["red"]),
              "gold": ("triangle-alert", C["gold"]), "accent": ("loader-circle", C["accent"]),
              None: ("info", C["text_dim"])}


class _StatusLine(QWidget):
    def __init__(self, text: str = "", tone=None, parent=None):
        super().__init__(parent)
        lay = hbox(self, spacing=SP["sm"])
        self._ic = QLabel()
        self._ic.setFixedSize(16, 16)
        lay.addWidget(self._ic, 0, Qt.AlignmentFlag.AlignTop)
        self._lbl = label("", "dim", wrap=True)
        lay.addWidget(self._lbl, 1)
        self.set(text, tone)

    def set(self, text: str, tone=None):
        name, color = _TONE_ICON[tone]
        self._ic.setPixmap(icons.pixmap(name, color, 16))
        self._lbl.setText(text)
        set_tone(self._lbl, tone)

    def setText(self, text: str):
        self._lbl.setText(text)


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
        self.setMinimumWidth(500)
        self.setModal(True)

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
        root = vbox(self, (SP["xl"], SP["lg"], SP["xl"], SP["lg"]), SP["md"])

        # ── Header ────────────────────────────────────────────────────────────
        head = hbox(spacing=SP["sm"])
        ic = QLabel()
        ic.setPixmap(icons.pixmap("gamepad-2", C["accent"], 18))
        head.addWidget(ic)
        head.addWidget(label("CONFIRM STEAM GAME", "title"), 1)
        root.addLayout(head)
        root.addWidget(label("The exported file is named after the Steam AppID, so Steam shows it on the "
                             "right game. Confirm the match below or pick another one.", "dim", wrap=True))

        # ── Match card ────────────────────────────────────────────────────────
        card = QFrame()
        card.setProperty("surface", "inset")
        cg = grid(card, (SP["md"], SP["md"], SP["md"], SP["md"]), SP["md"], SP["xs"])
        cg.addWidget(label("GAME", "eyebrow"), 0, 0)
        self._name_lbl = label(self._game_name, "body", wrap=True)
        cg.addWidget(self._name_lbl, 1, 0)
        cg.addWidget(label("STEAM APP ID", "eyebrow"), 0, 1)
        self._appid_lbl = label("—", "value")
        cg.addWidget(self._appid_lbl, 1, 1)
        self._link_lbl = label("", "muted")
        self._link_lbl.setOpenExternalLinks(True)
        self._link_lbl.setTextFormat(Qt.TextFormat.RichText)
        cg.addWidget(self._link_lbl, 2, 0, 1, 2)
        cg.setColumnStretch(0, 1)
        cg.setColumnMinimumWidth(1, 120)
        root.addWidget(card)

        # Status / loading
        self._status_lbl = _StatusLine("Searching Steam Store…", "accent")
        root.addWidget(self._status_lbl)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        root.addWidget(self._progress)

        # ── Manual search panel (hidden by default) ───────────────────────────
        self._manual_panel = QWidget()
        self._manual_panel.setVisible(False)
        mp = vbox(self._manual_panel, spacing=SP["sm"])

        mp.addWidget(Divider())
        mg = grid(h=SP["md"], v=SP["sm"])

        search_row = hbox(spacing=SP["sm"])
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Enter game title…")
        self._search_edit.returnPressed.connect(self._manual_search)
        search_row.addWidget(self._search_edit, 1)
        search_row.addWidget(Button("Search", icon="search", on_click=self._manual_search))
        l = label("Search by title", "dim"); l.setMinimumWidth(110)
        mg.addWidget(l, 0, 0)
        mg.addLayout(search_row, 0, 1)

        # ── Direct numeric AppID entry ─────────────────────────────────────
        numeric_row = hbox(spacing=SP["sm"])
        self._numeric_edit = QLineEdit()
        self._numeric_edit.setPlaceholderText("e.g.  1971870")
        self._numeric_edit.setMaximumWidth(160)
        self._numeric_edit.textChanged.connect(self._on_numeric_changed)
        self._numeric_edit.returnPressed.connect(self._apply_numeric)
        numeric_row.addWidget(self._numeric_edit)
        self._use_numeric_btn = Button("Use this ID", icon="check", on_click=self._apply_numeric)
        self._use_numeric_btn.setEnabled(False)
        numeric_row.addWidget(self._use_numeric_btn)
        numeric_row.addStretch()
        l = label("or enter AppID", "dim"); l.setMinimumWidth(110)
        mg.addWidget(l, 1, 0)
        mg.addLayout(numeric_row, 1, 1)
        mg.setColumnStretch(1, 1)
        mp.addLayout(mg)

        self._search_progress = QProgressBar()
        self._search_progress.setRange(0, 0)
        self._search_progress.setFixedHeight(6)
        self._search_progress.setTextVisible(False)
        self._search_progress.setVisible(False)
        mp.addWidget(self._search_progress)

        self._results_list = QListWidget()
        self._results_list.setFixedHeight(180)
        self._results_list.itemClicked.connect(self._on_result_picked)
        mp.addWidget(self._results_list)

        root.addWidget(self._manual_panel)

        root.addWidget(Divider())

        # ── Action buttons ────────────────────────────────────────────────────
        btn_row = hbox(spacing=SP["sm"])
        self._manual_btn = Button("Search manually", "ghost", icon="search", on_click=self._toggle_manual)
        btn_row.addWidget(self._manual_btn)
        btn_row.addStretch()
        cancel_btn = Button("Cancel", on_click=self.reject)
        cancel_btn.setMinimumWidth(90)
        btn_row.addWidget(cancel_btn)
        self._confirm_btn = Button("Confirm", "primary", icon="check", on_click=self._confirm)
        self._confirm_btn.setMinimumWidth(140)
        self._confirm_btn.setEnabled(False)
        btn_row.addWidget(self._confirm_btn)
        root.addLayout(btn_row)

    # ── auto search ───────────────────────────────────────────────────────────
    def _start_search(self, query: str):
        if not query:
            self._progress.setVisible(False)
            self._status_lbl.set("No game name — enter AppID manually.", "gold")
            if not self._manual_open:
                self._toggle_manual()
            return

        if self._auto_thread and self._auto_thread.isRunning():
            self._auto_thread.quit()
            self._auto_thread.wait(200)

        self._progress.setVisible(True)
        self._confirm_btn.setEnabled(False)

        worker = _SearchWorker(query)
        thread = QThread()          

        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        worker.done.connect(self._on_auto_done, Qt.QueuedConnection)
        worker.done.connect(thread.quit, Qt.QueuedConnection)
        thread.finished.connect(worker.deleteLater)  
        thread.finished.connect(thread.deleteLater)  
        self._auto_worker = worker
        self._auto_thread = thread
        thread.start()

    def _on_auto_done(self, candidates: list, error_code: str, error_msg: str):    
        sender = self.sender()
        if sender is not self._auto_worker:
            return
        self._on_search_done(candidates, error_code, error_msg)

    def _on_search_done(self, candidates: list, error_code: str, error_msg: str):
        """Called on the main thread via signal — safe to update UI."""
        self._progress.setVisible(False)
        self._candidates = candidates

        if error_code and error_code != "no_results":

            friendly = _ERROR_LABELS.get(error_code, "Search unavailable.")
            detail   = error_msg[:120] + ("…" if len(error_msg) > 120 else "")
            self._status_lbl.set(f"{friendly}\n{detail}", "gold")
            if not self._manual_open:
                self._toggle_manual()
            return

        if error_code == "no_results" or not candidates:
            self._status_lbl.set("No Steam matches found — enter AppID manually or try searching.", "gold")
            return

        from app.services.appIdGetter import match_confidence, CONFIDENT_SCORE
        best, score = match_confidence(candidates, self._game_name)
        if best is not None and score >= CONFIDENT_SCORE:
            self._apply_candidate(best)
        else:
            # Not sure which game this is — show the list, make the user pick.
            self._best = None
            self._confirm_btn.setEnabled(False)
            self._status_lbl.set(f"Closest match: {best['name']} — not identical. "
                                 "Pick the right game below or enter the AppID.", "gold")
            if not self._manual_open:
                self._toggle_manual()

    def _apply_candidate(self, c: dict):
        self._best = c
        self._appid_lbl.setText(str(c["id"]))
        self._name_lbl.setText(c["name"])
        self._link_lbl.setText(
            f'<a href="https://store.steampowered.com/app/{c["id"]}" '
            f'style="color:{C["accent"]};">store.steampowered.com/app/{c["id"]}</a>'
        )
        self._status_lbl.set("Match found — confirm or search manually.", "green")
        self._confirm_btn.setEnabled(True)

    # ── manual search ─────────────────────────────────────────────────────────
    def _toggle_manual(self):
        self._manual_open = not self._manual_open
        self._manual_panel.setVisible(self._manual_open)
        self._manual_btn.setText(
            "Hide manual search" if self._manual_open else "Search manually"
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
            for text, color in [(friendly, C["gold"]), (detail, C["text_dim"])]:
                if text:
                    item = QListWidgetItem(text)
                    if color == C["gold"]:
                        item.setIcon(icons.icon("triangle-alert", C["gold"], 14))
                    item.setForeground(QColor(color))
                    item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                    self._results_list.addItem(item)
            return

        if error_code == "no_results" or not candidates:
            item = QListWidgetItem("No Steam matches found — try a different name.")
            item.setForeground(QColor(C["text_dim"]))
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self._results_list.addItem(item)
            return

        for c in candidates:
            item = QListWidgetItem(f"{c['name']}   —   AppID: {c['id']}")
            item.setIcon(icons.icon("gamepad-2", C["text_dim"], 14))
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
        self._status_lbl.set(f"Using AppID {app_id} (entered manually).", "green")
        # Collapse manual panel — user is done
        if self._manual_open:
            self._manual_open = False
            self._manual_panel.setVisible(False)
            self._manual_btn.setText("Search manually")
            self.adjustSize()

    def _on_result_picked(self, item: QListWidgetItem):
        c = item.data(Qt.UserRole)
        if c:
            self._apply_candidate(c)
            # Collapse manual panel after picking
            self._manual_open = False
            self._manual_panel.setVisible(False)
            self._manual_btn.setText("Search manually")
            self.adjustSize()

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def closeEvent(self, event):
   
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
            # Only remember real game names — a manual AppID with no name
            # would create a junk "" / "AppID 123" entry.
            if self._game_name.strip():
                try:
                    from app.services.appIdRegistry import AppIdRegistry
                    AppIdRegistry.shared().register(
                        self._game_name, self.result_app_id,
                        canonical=self.result_name,
                    )
                except Exception:
                    pass   # registry is best-effort; never block export
            self.accept()