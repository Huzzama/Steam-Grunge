"""
app/ui/appIdConfirmDialog.py

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
from PySide6.QtGui  import QFont

from app.services.appIdGetter import search_candidates


# ── async worker ──────────────────────────────────────────────────────────────
class _SearchWorker(QObject):
    done = Signal(list)   # list[dict]  {"id": int, "name": str}

    def __init__(self, query: str):
        super().__init__()
        self._q = query

    def run(self):
        self.done.emit(search_candidates(self._q, limit=10))


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
        self._progress.setVisible(True)
        self._confirm_btn.setEnabled(False)

        self._worker = _SearchWorker(query)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_search_done)
        self._worker.done.connect(self._thread.quit)
        self._thread.start()

    def _on_search_done(self, candidates: list):
        self._progress.setVisible(False)
        self._candidates = candidates

        if not candidates:
            self._status_lbl.setText("No results found — use Search Manually.")
            self._status_lbl.setObjectName("warn")
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
        self._results_list.clear()
        self._search_progress.setVisible(True)

        self._msworker = _SearchWorker(q)
        self._msthread = QThread()
        self._msworker.moveToThread(self._msthread)
        self._msthread.started.connect(self._msworker.run)
        self._msworker.done.connect(self._on_manual_results)
        self._msworker.done.connect(self._msthread.quit)
        self._msthread.start()

    def _on_manual_results(self, candidates: list):
        self._search_progress.setVisible(False)
        self._results_list.clear()
        if not candidates:
            item = QListWidgetItem("No results found.")
            item.setForeground(Qt.gray)
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self._results_list.addItem(item)
            return
        for c in candidates:
            item = QListWidgetItem(f"{c['name']}   —   AppID: {c['id']}")
            item.setData(Qt.UserRole, c)
            self._results_list.addItem(item)

    def _on_result_picked(self, item: QListWidgetItem):
        c = item.data(Qt.UserRole)
        if c:
            self._apply_candidate(c)
            # Collapse manual panel after picking
            self._manual_open = False
            self._manual_panel.setVisible(False)
            self._manual_btn.setText("Search Manually")
            self.adjustSize()

    # ── confirm ───────────────────────────────────────────────────────────────
    def _confirm(self):
        if self._best:
            self.result_app_id = self._best["id"]
            self.result_name   = self._best["name"]
            self.accept()