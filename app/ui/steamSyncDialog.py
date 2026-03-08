"""
app/ui/steamSyncDialog.py
"Sync to Steam" dialog.

Flow:
  1. Dialog opens — auto-fetches AppID for current game name in background.
  2. Shows: detected game name, AppID, Steam user accounts found, artworks
     that will be installed (one row per exported template).
  3. User can correct the game name / AppID manually.
  4. "Sync" button copies files → Steam grid folder.
  5. Shows per-file result with green ✔ / red ✖ indicators.
"""
from __future__ import annotations

import os
import threading
from typing import Optional, List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QFrame, QScrollArea, QWidget,
    QProgressBar, QMessageBox, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QObject, QThread
from PySide6.QtGui  import QFont, QColor

from app.services.appIdGetter import search_candidates
from app.services.steamSync   import (
    find_steam_userdata, list_steam_ids,
    get_grid_folder, sync_artwork, SyncResult,
)

# ── Async worker ──────────────────────────────────────────────────────────────
class _AppIdWorker(QObject):
    finished = Signal(list)   # list[dict]  candidates

    def __init__(self, game_name: str):
        super().__init__()
        self._name = game_name

    def run(self):
        results = search_candidates(self._name, limit=8)
        self.finished.emit(results)


# ── Divider helper ────────────────────────────────────────────────────────────
def _hline():
    f = QFrame(); f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color:#2a2a2a;")
    return f


# ── Dialog ────────────────────────────────────────────────────────────────────
DIALOG_STYLE = """
QDialog {
    background: #141414;
    color: #ccc;
    font-family: 'Courier New', monospace;
    font-size: 13px;
}
QLabel        { color: #aaa; font-size: 13px; }
QLabel#title  { color: #88cc88; font-size: 15px; font-weight: bold; letter-spacing: 2px; }
QLabel#section{ color: #666;   font-size: 11px; letter-spacing: 2px; padding-top: 6px; }
QLabel#ok     { color: #88cc88; }
QLabel#err    { color: #cc6666; }
QLabel#warn   { color: #ccaa44; }
QLineEdit {
    background: #1a1a1a; border: 1px solid #333; color: #ddd;
    font-family: 'Courier New'; font-size: 13px;
    padding: 4px 8px; border-radius: 2px;
}
QLineEdit:focus { border-color: #556; }
QComboBox {
    background: #1a1a1a; border: 1px solid #333; color: #ccc;
    font-family: 'Courier New'; font-size: 13px;
    padding: 4px 8px; border-radius: 2px; min-height: 26px;
}
QComboBox QAbstractItemView {
    background: #1a1a1a; border: 1px solid #444; color: #ccc;
    selection-background-color: #2a2a4a;
}
QPushButton {
    background: #1e1e2e; border: 1px solid #3a3a5a; color: #aaa;
    font-family: 'Courier New'; font-size: 13px;
    padding: 6px 16px; border-radius: 2px; min-height: 28px;
}
QPushButton:hover   { background: #2a2a4a; color: #ddd; border-color: #5566aa; }
QPushButton:pressed { background: #111; }
QPushButton#sync_btn {
    background: #1a2e1a; border: 1px solid #3a6e3a;
    color: #88cc88; font-weight: bold; font-size: 14px;
}
QPushButton#sync_btn:hover   { background: #223a22; border-color: #55aa55; }
QPushButton#sync_btn:disabled { background: #1a1a1a; color: #444; border-color: #2a2a2a; }
QProgressBar {
    background: #1a1a1a; border: 1px solid #333; border-radius: 2px;
    text-align: center; color: #666; font-size: 11px; height: 6px;
}
QProgressBar::chunk { background: #3a6e3a; border-radius: 2px; }
"""


class SteamSyncDialog(QDialog):
    def __init__(self, game_name: str, exports: dict[str, str], parent=None):
        """
        Parameters
        ----------
        game_name : the name currently in state (used for AppID lookup)
        exports   : {template_name: absolute_path_to_png}
                    only templates with a real file will be synced
        """
        super().__init__(parent)
        self.setWindowTitle("Sync to Steam")
        self.setMinimumWidth(580)
        self.setStyleSheet(DIALOG_STYLE)

        self._game_name  = game_name
        self._exports    = {k: v for k, v in exports.items()
                            if v and os.path.isfile(v)}
        self._candidates: List[dict] = []
        self._userdata   = find_steam_userdata()
        self._steam_ids  = list_steam_ids(self._userdata) if self._userdata else []
        self._worker_thread: Optional[QThread] = None

        self._build()
        self._start_lookup()

    # ── UI construction ───────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(20, 16, 20, 16)

        # Title
        title = QLabel("✦  SYNC TO STEAM")
        title.setObjectName("title")
        root.addWidget(title)
        root.addWidget(_hline())

        # ── GAME / APP ID ─────────────────────────────────────────────────────
        sec1 = QLabel("GAME IDENTIFICATION")
        sec1.setObjectName("section")
        root.addWidget(sec1)

        # Game name row
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Game name:"))
        self._name_edit = QLineEdit(self._game_name)
        self._name_edit.setPlaceholderText("Enter game name…")
        self._name_edit.textChanged.connect(self._on_name_changed)
        name_row.addWidget(self._name_edit, 1)
        btn_search = QPushButton("Search")
        btn_search.setFixedWidth(80)
        btn_search.clicked.connect(self._start_lookup)
        name_row.addWidget(btn_search)
        root.addLayout(name_row)

        # AppID row
        appid_row = QHBoxLayout()
        appid_row.addWidget(QLabel("AppID:"))
        self._appid_edit = QLineEdit()
        self._appid_edit.setPlaceholderText("Looking up…")
        self._appid_edit.setFixedWidth(130)
        appid_row.addWidget(self._appid_edit)

        # Candidate picker
        self._candidate_combo = QComboBox()
        self._candidate_combo.setPlaceholderText("— choose from results —")
        self._candidate_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._candidate_combo.currentIndexChanged.connect(self._on_candidate_picked)
        appid_row.addWidget(self._candidate_combo, 1)
        root.addLayout(appid_row)

        # Lookup status
        self._lookup_label = QLabel("Searching Steam Store…")
        self._lookup_label.setObjectName("warn")
        root.addWidget(self._lookup_label)

        # Progress bar (hidden after lookup)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # indeterminate
        self._progress.setFixedHeight(6)
        root.addWidget(self._progress)

        root.addWidget(_hline())

        # ── STEAM ACCOUNT ─────────────────────────────────────────────────────
        sec2 = QLabel("STEAM ACCOUNT")
        sec2.setObjectName("section")
        root.addWidget(sec2)

        if self._userdata and self._steam_ids:
            acc_row = QHBoxLayout()
            acc_row.addWidget(QLabel("SteamID:"))
            self._id_combo = QComboBox()
            for sid in self._steam_ids:
                self._id_combo.addItem(sid)
            acc_row.addWidget(self._id_combo, 1)
            root.addLayout(acc_row)

            # Show grid folder path
            self._folder_label = QLabel()
            self._folder_label.setStyleSheet(
                "color:#555; font-size:11px; font-family:'Courier New';")
            self._folder_label.setWordWrap(True)
            self._id_combo.currentTextChanged.connect(self._update_folder_label)
            self._update_folder_label(self._steam_ids[0])
            root.addWidget(self._folder_label)
        else:
            warn = QLabel("⚠  Steam installation not found.\n"
                          "Make sure Steam is installed and has been launched at least once.")
            warn.setObjectName("warn")
            warn.setWordWrap(True)
            root.addWidget(warn)
            self._id_combo = None

        root.addWidget(_hline())

        # ── FILES TO INSTALL ─────────────────────────────────────────────────
        sec3 = QLabel("FILES TO INSTALL")
        sec3.setObjectName("section")
        root.addWidget(sec3)

        self._files_widget = QWidget()
        self._files_layout = QVBoxLayout(self._files_widget)
        self._files_layout.setSpacing(3)
        self._files_layout.setContentsMargins(0, 0, 0, 0)
        self._rebuild_files_list()
        root.addWidget(self._files_widget)

        root.addWidget(_hline())

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_row.addStretch()

        self._sync_btn = QPushButton("⇪  Sync to Steam")
        self._sync_btn.setObjectName("sync_btn")
        self._sync_btn.setMinimumWidth(180)
        self._sync_btn.clicked.connect(self._do_sync)
        btn_row.addWidget(self._sync_btn)
        root.addLayout(btn_row)

        # Result area (hidden until sync runs)
        self._result_label = QLabel()
        self._result_label.setWordWrap(True)
        self._result_label.setVisible(False)
        root.addWidget(self._result_label)

    def _rebuild_files_list(self):
        # Clear
        while self._files_layout.count():
            item = self._files_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        _LABELS = {
            "cover":     "Cover       (600×900)",
            "vhs_cover": "VHS Cover   (600×900)",
            "wide":      "Wide Cover  (920×430)",
            "hero":      "Hero/BG     (3840×1240)",
            "logo":      "Logo        (1280×720)",
            "icon":      "Icon        (512×512)",
        }
        _SUFFIX = {
            "cover": "{id}.png", "vhs_cover": "{id}p.png",
            "wide": "{id}p.png", "hero": "{id}_hero.png",
            "logo": "{id}_logo.png", "icon": "{id}_icon.png",
        }
        app_id = self._appid_edit.text().strip() or "???"

        if not self._exports:
            lbl = QLabel("No exported files found. Export at least one template first.")
            lbl.setObjectName("warn")
            self._files_layout.addWidget(lbl)
            return

        for tpl, src in self._exports.items():
            row = QHBoxLayout()
            suffix = _SUFFIX.get(tpl, "").format(id=app_id)
            row.addWidget(QLabel(f"  {_LABELS.get(tpl, tpl)}"))
            arrow = QLabel("→")
            arrow.setStyleSheet("color:#3a6e3a;")
            row.addWidget(arrow)
            dest_lbl = QLabel(suffix)
            dest_lbl.setStyleSheet("color:#7788aa; font-size:12px;")
            row.addWidget(dest_lbl, 1)
            w = QWidget(); w.setLayout(row)
            self._files_layout.addWidget(w)

    # ── AppID lookup ──────────────────────────────────────────────────────────
    def _start_lookup(self):
        name = self._name_edit.text().strip()
        if not name:
            return
        self._lookup_label.setText("Searching Steam Store…")
        self._lookup_label.setObjectName("warn")
        self._lookup_label.setStyleSheet("")
        self._progress.setVisible(True)
        self._sync_btn.setEnabled(False)

        self._worker = _AppIdWorker(name)
        self._worker_thread = QThread()
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_lookup_done)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.start()

    def _on_lookup_done(self, candidates: list):
        self._progress.setVisible(False)
        self._candidates = candidates
        self._candidate_combo.blockSignals(True)
        self._candidate_combo.clear()

        if candidates:
            for c in candidates:
                self._candidate_combo.addItem(
                    f"{c['name']}  [{c['id']}]", userData=c)
            self._candidate_combo.blockSignals(False)
            # Auto-select best match
            best = candidates[0]
            self._appid_edit.setText(str(best["id"]))
            self._lookup_label.setText(
                f"✔  Found: {best['name']}  (AppID {best['id']})")
            self._lookup_label.setStyleSheet("color:#88cc88;")
            self._sync_btn.setEnabled(True)
        else:
            self._candidate_combo.blockSignals(False)
            self._lookup_label.setText(
                "✖  No results — enter the AppID manually.")
            self._lookup_label.setStyleSheet("color:#cc6666;")
            self._sync_btn.setEnabled(True)   # allow manual entry

        self._rebuild_files_list()

    def _on_candidate_picked(self, idx: int):
        data = self._candidate_combo.itemData(idx)
        if data and isinstance(data, dict):
            self._appid_edit.setText(str(data["id"]))
            self._rebuild_files_list()

    def _on_name_changed(self, _text: str):
        self._appid_edit.clear()
        self._candidate_combo.clear()

    def _update_folder_label(self, steam_id: str):
        if self._userdata:
            path = get_grid_folder(self._userdata, steam_id)
            self._folder_label.setText(f"Grid folder:  {path}")

    # ── Sync ─────────────────────────────────────────────────────────────────
    def _do_sync(self):
        # Validate AppID
        appid_txt = self._appid_edit.text().strip()
        if not appid_txt.isdigit():
            QMessageBox.warning(self, "Missing AppID",
                                "Please enter a valid numeric Steam AppID.")
            return

        app_id = int(appid_txt)

        if not self._userdata:
            QMessageBox.critical(self, "Steam Not Found",
                                 "Could not locate your Steam installation.")
            return

        steam_id = self._id_combo.currentText() if self._id_combo else None
        if not steam_id:
            QMessageBox.warning(self, "No Account",
                                "No Steam account folder found.")
            return

        result: SyncResult = sync_artwork(
            app_id=app_id,
            steam_id=steam_id,
            userdata_path=self._userdata,
            exports=self._exports,
            overwrite=True,
        )

        # Show result
        lines = []
        for path in result.installed:
            lines.append(f"<span style='color:#88cc88'>✔</span>  {os.path.basename(path)}")
        for tpl in result.skipped:
            lines.append(f"<span style='color:#666'>—</span>  {tpl}  (skipped)")
        for err in result.errors:
            lines.append(f"<span style='color:#cc6666'>✖</span>  {err}")

        self._result_label.setTextFormat(Qt.RichText)
        self._result_label.setText("<br>".join(lines))
        self._result_label.setVisible(True)

        if result.success:
            self._sync_btn.setText("✔  Synced!")
            self._sync_btn.setEnabled(False)
            # Show reminder to restart Steam
            QMessageBox.information(
                self, "Sync Complete",
                f"Installed {len(result.installed)} file(s) to:\n{result.grid_folder}\n\n"
                "Restart Steam or reload your library to see the new artwork."
            )